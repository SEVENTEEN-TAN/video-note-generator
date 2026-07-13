from __future__ import annotations

import json
import inspect
import os
import re
import shutil
from collections.abc import Callable
from pathlib import Path
from uuid import uuid4

from .ffmpeg_tools import extract_frame
from .frame_selection import select_key_frame_moments
from .llm import generate_note_draft
from .markdown import render_note_markdown
from .models import JobConfig, NoteDraft, NoteStyle, NoteVersion, NoteVersionIndex
from .subtitles import transcript_segments_from_payload
from .task_debug_log import TaskDebugLog
from .transcript_corrections import load_preferred_transcript_payload


NOTE_VERSIONS_DIR = "note_versions"
NOTE_VERSION_INDEX = "versions.json"
NOTE_FRAME_BLOCK_PATTERN = re.compile(
    r"!\[[^\]]*\]\(([^)]+)\)\s*(?:\r?\n\s*)+>\s*关键帧：`?(\d{2}:\d{2}:\d{2})`?",
    re.MULTILINE,
)


def safe_note_version_id(version_id: str) -> str:
    if not version_id or version_id in {".", ".."} or "/" in version_id or "\\" in version_id:
        raise ValueError(f"Unsafe note version id: {version_id}")
    return version_id


def resolve_job_relative_path(job_dir: Path, relative_path: str) -> Path:
    if not relative_path or Path(relative_path).is_absolute():
        raise ValueError(f"Unsafe note version path: {relative_path}")
    root = job_dir.resolve()
    candidate = (root / relative_path).resolve()
    if candidate == root or root not in candidate.parents:
        raise ValueError(f"Unsafe note version path: {relative_path}")
    return candidate


def is_safe_note_version(job_dir: Path, version: NoteVersion) -> bool:
    try:
        safe_note_version_id(version.id)
        resolve_job_relative_path(job_dir, version.note_path)
        resolve_job_relative_path(job_dir, version.frame_dir)
    except ValueError:
        return False
    return True


def atomic_write_text(path: Path, text: str, *, encoding: str = "utf-8") -> None:
    tmp_path = path.with_name(f"{path.name}.tmp")
    try:
        tmp_path.write_text(text, encoding=encoding)
        tmp_path.replace(path)
    finally:
        if tmp_path.exists():
            tmp_path.unlink()


def note_version_index_path(job_dir: Path) -> Path:
    return job_dir / NOTE_VERSIONS_DIR / NOTE_VERSION_INDEX


def load_note_version_index(job_dir: Path) -> NoteVersionIndex:
    path = note_version_index_path(job_dir)
    if not path.exists():
        return NoteVersionIndex()
    try:
        raw_index = NoteVersionIndex.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return NoteVersionIndex()

    safe_versions = [version for version in raw_index.versions if is_safe_note_version(job_dir, version)]
    return normalize_note_version_index(
        NoteVersionIndex(
            active_version_id=raw_index.active_version_id,
            selected_version_ids=raw_index.selected_version_ids,
            versions=safe_versions,
        )
    )


def write_note_version_index(job_dir: Path, index: NoteVersionIndex) -> NoteVersionIndex:
    normalized = normalize_note_version_index(
        NoteVersionIndex(
            active_version_id=index.active_version_id,
            selected_version_ids=index.selected_version_ids,
            versions=[version for version in index.versions if is_safe_note_version(job_dir, version)],
        )
    )
    path = note_version_index_path(job_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(path, normalized.model_dump_json(indent=2), encoding="utf-8")
    return normalized


def add_note_version(job_dir: Path, version: NoteVersion) -> NoteVersionIndex:
    index = load_note_version_index(job_dir)
    versions = [item for item in index.versions if item.id != version.id]
    versions.append(version.model_copy(update={"active": True, "selected": True}))
    selected_version_ids = [item for item in index.selected_version_ids if item != version.id]
    selected_version_ids.append(version.id)
    return write_note_version_index(
        job_dir,
        NoteVersionIndex(
            active_version_id=version.id,
            selected_version_ids=selected_version_ids,
            versions=versions,
        ),
    )


def normalize_note_version_index(index: NoteVersionIndex) -> NoteVersionIndex:
    known_ids = [version.id for version in index.versions]
    active_version_id = index.active_version_id if index.active_version_id in known_ids else None
    selected_version_ids = [version_id for version_id in index.selected_version_ids if version_id in known_ids]
    if active_version_id and active_version_id not in selected_version_ids:
        selected_version_ids.append(active_version_id)
    versions = [
        version.model_copy(
            update={
                "active": version.id == active_version_id,
                "selected": version.id in selected_version_ids,
            }
        )
        for version in index.versions
    ]
    return NoteVersionIndex(
        active_version_id=active_version_id,
        selected_version_ids=selected_version_ids,
        versions=versions,
    )


def next_note_version_id(job_dir: Path) -> str:
    index = load_note_version_index(job_dir)
    used_numbers: list[int] = []
    for version in index.versions:
        if version.id.startswith("note_"):
            try:
                used_numbers.append(int(version.id.removeprefix("note_")))
            except ValueError:
                continue
    return f"note_{(max(used_numbers, default=0) + 1):03d}"


def next_manual_version_id(job_dir: Path) -> str:
    index = load_note_version_index(job_dir)
    used_numbers: list[int] = []
    for version in index.versions:
        if version.id.startswith("manual_"):
            try:
                used_numbers.append(int(version.id.removeprefix("manual_")))
            except ValueError:
                continue
    return f"manual_{(max(used_numbers, default=0) + 1):03d}"


def get_note_version(index: NoteVersionIndex, version_id: str) -> NoteVersion | None:
    for version in index.versions:
        if version.id == version_id:
            return version
    return None


def set_note_version_selection(
    job_dir: Path,
    selected_version_ids: list[str],
    active_version_id: str | None = None,
) -> NoteVersionIndex:
    index = load_note_version_index(job_dir)
    known_ids = {version.id for version in index.versions}
    selected = [version_id for version_id in selected_version_ids if version_id in known_ids]
    active = active_version_id if active_version_id in known_ids else index.active_version_id
    if active and active not in selected:
        selected.append(active)
    return write_note_version_index(
        job_dir,
        NoteVersionIndex(active_version_id=active, selected_version_ids=selected, versions=index.versions),
    )


def activate_note_version(job_dir: Path, version_id: str) -> NoteVersionIndex:
    current_index = load_note_version_index(job_dir)
    version = get_note_version(current_index, version_id)
    if not version:
        raise FileNotFoundError(f"Note version not found: {version_id}")

    source_note = resolve_job_relative_path(job_dir, version.note_path)
    if not source_note.exists() or not source_note.is_file():
        raise FileNotFoundError(f"Note version file is missing: {version_id}")

    source_frames = resolve_job_relative_path(job_dir, version.frame_dir)
    if not source_frames.exists() or not source_frames.is_dir():
        raise FileNotFoundError(f"Note version frames are missing: {version_id}")

    selected_ids = list(current_index.selected_version_ids)
    if version_id not in selected_ids:
        selected_ids.append(version_id)
    next_index = NoteVersionIndex(
        active_version_id=version_id,
        selected_version_ids=selected_ids,
        versions=current_index.versions,
    )
    root_note = job_dir / "note.md"
    root_frames = job_dir / "frames"
    token = uuid4().hex
    temporary_note = job_dir / f".note.{token}.tmp"
    temporary_frames = job_dir / f".frames.{token}.tmp"
    backup_note = job_dir / f".note.{token}.backup"
    backup_frames = job_dir / f".frames.{token}.backup"
    try:
        shutil.copyfile(source_note, temporary_note)
        shutil.copytree(source_frames, temporary_frames)
        if root_note.exists():
            root_note.replace(backup_note)
        if root_frames.exists():
            root_frames.replace(backup_frames)
        temporary_note.replace(root_note)
        temporary_frames.replace(root_frames)
        try:
            index = write_note_version_index(job_dir, next_index)
        except Exception:
            root_note.unlink(missing_ok=True)
            shutil.rmtree(root_frames, ignore_errors=True)
            if backup_note.exists():
                backup_note.replace(root_note)
            if backup_frames.exists():
                backup_frames.replace(root_frames)
            raise
        backup_note.unlink(missing_ok=True)
        shutil.rmtree(backup_frames, ignore_errors=True)
        return index
    finally:
        temporary_note.unlink(missing_ok=True)
        shutil.rmtree(temporary_frames, ignore_errors=True)


def ensure_root_note_has_version(job_dir: Path) -> NoteVersionIndex:
    root_note = job_dir / "note.md"
    if not root_note.exists() or not root_note.is_file():
        return load_note_version_index(job_dir)

    index = load_note_version_index(job_dir)
    root_text = root_note.read_text(encoding="utf-8-sig")
    for version in index.versions:
        try:
            version_note = resolve_job_relative_path(job_dir, version.note_path)
        except ValueError:
            continue
        if version_note.exists() and version_note.read_text(encoding="utf-8-sig") == root_text:
            if version.id == index.active_version_id:
                return index
            return set_note_version_selection(job_dir, index.selected_version_ids, version.id)

    return snapshot_root_note_as_manual_version(job_dir)


def snapshot_root_note_as_manual_version(job_dir: Path) -> NoteVersionIndex:
    version_id = next_manual_version_id(job_dir)
    version_dir = job_dir / NOTE_VERSIONS_DIR / version_id
    frames_dir = version_dir / "frames"
    frames_dir.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(job_dir / "note.md", version_dir / "note.md")

    root_frames = job_dir / "frames"
    if root_frames.exists():
        if frames_dir.exists():
            shutil.rmtree(frames_dir)
        shutil.copytree(root_frames, frames_dir)

    metadata = _read_metadata(job_dir)
    try:
        note_style = NoteStyle(str(metadata.get("note_style") or NoteStyle.detailed.value))
    except ValueError:
        note_style = NoteStyle.detailed
    frame_limit = int(metadata.get("frame_limit") or 6)
    version = NoteVersion(
        id=version_id,
        label=f"{version_id} · 手工版本",
        note_style=note_style,
        note_language=str(metadata.get("note_language") or "zh"),
        note_model=str(metadata.get("note_model") or "manual"),
        note_base_url=str(metadata.get("note_base_url") or ""),
        frame_limit=frame_limit,
        note_path=f"{NOTE_VERSIONS_DIR}/{version_id}/note.md",
        frame_dir=f"{NOTE_VERSIONS_DIR}/{version_id}/frames",
        selected=True,
        active=True,
        extras_present=bool(metadata.get("extras_present") or False),
        extras_length=int(metadata.get("extras_length") or 0),
    )
    index = load_note_version_index(job_dir)
    selected_version_ids = [item for item in index.selected_version_ids if item != version_id]
    selected_version_ids.append(version_id)
    versions = [item for item in index.versions if item.id != version_id]
    versions.append(version)
    return write_note_version_index(
        job_dir,
        NoteVersionIndex(active_version_id=version_id, selected_version_ids=selected_version_ids, versions=versions),
    )


def create_note_version_from_draft(
    *,
    job_dir: Path,
    video_path: Path,
    draft: NoteDraft,
    duration: float | None,
    config: JobConfig,
    version_id: str | None = None,
    is_cancelled: Callable[[], bool] | None = None,
) -> NoteVersion:
    version_id = safe_note_version_id(version_id or next_note_version_id(job_dir))
    version_dir = job_dir / NOTE_VERSIONS_DIR / version_id
    if version_dir.exists():
        raise ValueError(f"Note version already exists: {version_id}")
    temporary_dir = version_dir.with_name(f".{version_id}.{uuid4().hex}.tmp")
    frames_dir = temporary_dir / "frames"
    frames_dir.mkdir(parents=True, exist_ok=True)

    try:
        version_draft = draft.model_copy(deep=True)
        selected_moments = select_key_frame_moments(version_draft, duration, config.frame_limit)
        reusable_frames = _existing_version_frames(job_dir)
        for index, moment in enumerate(selected_moments, start=1):
            if is_cancelled and is_cancelled():
                raise RuntimeError("Note frame extraction was cancelled.")
            frame_rel = f"frames/frame_{index:03d}.jpg"
            destination = temporary_dir / frame_rel
            reusable = reusable_frames.get(round(moment.time))
            if reusable is not None and reusable.exists():
                _materialize_version_frame(reusable, destination)
                actual_time = moment.time
            else:
                actual_time = _extract_frame_with_cancellation(
                    video_path,
                    destination,
                    moment.time,
                    duration,
                    is_cancelled,
                )
            moment.time = actual_time
            moment.frame_path = frame_rel
        version_draft.key_moments = selected_moments

        note_path = temporary_dir / "note.md"
        note_path.write_text(render_note_markdown(version_draft), encoding="utf-8-sig")
        temporary_dir.replace(version_dir)
    finally:
        if temporary_dir.exists():
            shutil.rmtree(temporary_dir, ignore_errors=True)
    version = NoteVersion(
        id=version_id,
        label=f"{version_id} · {config.note_style.value}",
        note_style=config.note_style,
        note_language=config.note_language.value,
        note_model=config.note_model,
        note_base_url=config.note_base_url,
        frame_limit=config.frame_limit,
        note_path=f"{NOTE_VERSIONS_DIR}/{version_id}/note.md",
        frame_dir=f"{NOTE_VERSIONS_DIR}/{version_id}/frames",
        selected=True,
        active=True,
        extras_present=bool(config.extras),
        extras_length=len(config.extras),
    )
    add_note_version(job_dir, version)
    activate_note_version(job_dir, version.id)
    return version


def _existing_version_frames(job_dir: Path) -> dict[int, Path]:
    root = job_dir.resolve()
    reusable: dict[int, Path] = {}
    versions_root = root / NOTE_VERSIONS_DIR
    if not versions_root.exists():
        return reusable
    for note_path in versions_root.glob("*/note.md"):
        try:
            note_text = note_path.read_text(encoding="utf-8-sig")
        except OSError:
            continue
        for match in NOTE_FRAME_BLOCK_PATTERN.finditer(note_text):
            raw_path, raw_time = match.groups()
            frame_path = (note_path.parent / raw_path.strip()).resolve()
            try:
                frame_path.relative_to(root)
            except ValueError:
                continue
            if frame_path.is_file() and frame_path.stat().st_size > 0:
                reusable[round(_hhmmss_to_seconds(raw_time))] = frame_path
    return reusable


def _materialize_version_frame(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.link(source, destination)
    except OSError:
        shutil.copy2(source, destination)


def _hhmmss_to_seconds(value: str) -> float:
    hours, minutes, seconds = value.split(":")
    return int(hours) * 3600 + int(minutes) * 60 + int(seconds)


def _extract_frame_with_cancellation(
    video_path: Path,
    output_path: Path,
    timestamp: float,
    duration: float | None,
    is_cancelled: Callable[[], bool] | None,
) -> float:
    if is_cancelled is not None and "is_cancelled" in inspect.signature(extract_frame).parameters:
        return extract_frame(video_path, output_path, timestamp, duration, is_cancelled=is_cancelled)
    return extract_frame(video_path, output_path, timestamp, duration)


def regenerate_note_version(
    job_dir: Path,
    config: JobConfig,
    debug_log: TaskDebugLog | None = None,
    *,
    is_cancelled: Callable[[], bool] | None = None,
) -> NoteVersion:
    segments = transcript_segments_from_payload(load_preferred_transcript_payload(job_dir))
    if not segments:
        raise ValueError("Cannot regenerate notes because transcript.json has no usable segments.")

    metadata = _read_metadata(job_dir)
    duration = metadata.get("duration_seconds")
    video_path = find_source_video(job_dir)
    if debug_log:
        draft = generate_note_draft(config, float(duration) if duration is not None else None, segments, debug_log=debug_log)
    else:
        draft = generate_note_draft(config, float(duration) if duration is not None else None, segments)
    return create_note_version_from_draft(
        job_dir=job_dir,
        video_path=video_path,
        draft=draft,
        duration=float(duration) if duration is not None else None,
        config=config,
        is_cancelled=is_cancelled,
    )


def find_source_video(job_dir: Path) -> Path:
    source_dir = job_dir / "source_video"
    for path in sorted(source_dir.glob("input.*")):
        if path.is_file():
            return path
    raise FileNotFoundError("Cannot regenerate note frames because the source video is missing.")


def _read_metadata(job_dir: Path) -> dict:
    metadata_path = job_dir / "metadata.json"
    if not metadata_path.exists():
        return {}
    return json.loads(metadata_path.read_text(encoding="utf-8"))
