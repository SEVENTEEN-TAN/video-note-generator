from __future__ import annotations

import hashlib
import json
import re
import shutil
from collections import defaultdict
from pathlib import Path
from uuid import uuid4

from .atomic_io import atomic_replace_directory, atomic_write_json, atomic_write_text
from .frame_candidates import load_frame_candidate_index
from .models import FrameCandidate, ReviewDraft
from .note_evidence import audit_review_draft_evidence
from .note_versions import get_note_version, load_note_version_index, resolve_job_relative_path
from .operation_leases import assert_current_operation_lease
from .review_drafts import load_review_draft, upgrade_review_draft_evidence, write_review_draft
from .time_utils import seconds_to_hhmmss


NOTE_REVIEW_PENDING_MARKER = ".note-review.pending"
FINALIZATION_MANIFEST_PATH = Path("review") / "finalization.json"
FINALIZATION_STAGING_PATH = Path("review") / "finalization_staging"
IMAGE_LINE_PATTERN = re.compile(r"^\s*!\[[^\]]*]\([^)]+\)\s*$")
HEADING_PATTERN = re.compile(r"^###\s+")
TIME_RANGE_PATTERN = re.compile(r"`?\d{2}:\d{2}:\d{2}\s+-\s+\d{2}:\d{2}:\d{2}`?")


def mark_note_review_pending(job_dir: Path) -> None:
    _discard_finalization_transaction(job_dir)
    atomic_write_text(job_dir / NOTE_REVIEW_PENDING_MARKER, "1", encoding="utf-8")


def is_note_review_pending(job_dir: Path) -> bool:
    return (job_dir / NOTE_REVIEW_PENDING_MARKER).exists()


def finalize_reviewed_note(job_dir: Path, version_id: str | None = None) -> None:
    assert_current_operation_lease()
    marker = job_dir / NOTE_REVIEW_PENDING_MARKER
    if not marker.exists():
        raise PermissionError("note review is not pending.")
    existing_manifest = _load_finalization_manifest(job_dir)
    if existing_manifest is not None and existing_manifest.get("status") in {
        "prepared",
        "note_committed",
        "completed",
    }:
        _commit_prepared_finalization(job_dir, existing_manifest, version_id)
        return

    review_draft = load_review_draft(job_dir, version_id)
    source_note = (job_dir / "note.md").read_text(encoding="utf-8-sig")
    if review_draft is not None:
        source_hash = hashlib.sha256(source_note.encode("utf-8")).hexdigest()
        if review_draft.source_note_sha256 != source_hash:
            raise ValueError("The note changed after the review draft was created. Reload the review draft before finalizing.")
        if review_draft.schema_version < 2 or not review_draft.source_transcript_sha256:
            review_draft = upgrade_review_draft_evidence(job_dir, review_draft, version_id)
        evidence_audit = audit_review_draft_evidence(job_dir, review_draft)
        if evidence_audit.transcript_changed or evidence_audit.invalid_chapter_references:
            raise ValueError(
                "The transcript changed after the review draft was created. Reload or regenerate the review draft before finalizing."
            )
    selected = _selected_candidates_from_review_draft(job_dir, review_draft) if review_draft else _selected_candidates(job_dir)
    if not selected:
        raise ValueError("No selected frame candidates.")
    manifest = _prepare_finalization(job_dir, version_id, source_note, review_draft, selected)
    _commit_prepared_finalization(job_dir, manifest, version_id)


def complete_review_finalization(job_dir: Path) -> None:
    manifest = _load_finalization_manifest(job_dir)
    if manifest is not None:
        completed = dict(manifest)
        completed["status"] = "completed"
        atomic_write_json(job_dir / FINALIZATION_MANIFEST_PATH, completed)
    assert_current_operation_lease()
    (job_dir / NOTE_REVIEW_PENDING_MARKER).unlink(missing_ok=True)
    shutil.rmtree(job_dir / FINALIZATION_STAGING_PATH, ignore_errors=True)


def _prepare_finalization(
    job_dir: Path,
    version_id: str | None,
    source_note: str,
    review_draft: ReviewDraft | None,
    selected: list[FrameCandidate],
) -> dict:
    review_root = job_dir / "review"
    review_root.mkdir(parents=True, exist_ok=True)
    transaction_id = uuid4().hex
    temporary = review_root / f".finalization_staging.{transaction_id}.tmp"
    staged_frames = temporary / "frames"
    staged_frames.mkdir(parents=True)
    try:
        frame_map = _stage_selected_frames(job_dir, selected, staged_frames)
        final_note = (
            _render_note_with_review_draft(source_note, review_draft, selected, frame_map)
            if review_draft
            else _render_note_with_selected_frames(source_note, selected, frame_map)
        )
        atomic_write_text(temporary / "note.md", final_note, encoding="utf-8-sig")
        if review_draft is not None:
            finalized_review_draft = review_draft.model_copy(
                update={
                    "finalized_note_sha256": hashlib.sha256(final_note.encode("utf-8")).hexdigest(),
                }
            )
            atomic_write_text(
                temporary / "review_draft.json",
                finalized_review_draft.model_dump_json(indent=2),
                encoding="utf-8",
            )
        atomic_replace_directory(temporary, job_dir / FINALIZATION_STAGING_PATH)
    finally:
        if temporary.exists():
            shutil.rmtree(temporary, ignore_errors=True)

    active_version_id = load_note_version_index(job_dir).active_version_id
    resolved_version_id = version_id or (review_draft.note_version_id if review_draft else None) or active_version_id
    manifest = {
        "schema_version": 1,
        "transaction_id": transaction_id,
        "status": "prepared",
        "version_id": resolved_version_id or "",
        "source_note_sha256": hashlib.sha256(source_note.encode("utf-8")).hexdigest(),
        "final_note_sha256": hashlib.sha256(final_note.encode("utf-8")).hexdigest(),
        "selected_frame_ids": [candidate.id for candidate in selected],
    }
    atomic_write_json(job_dir / FINALIZATION_MANIFEST_PATH, manifest)
    return manifest


def _commit_prepared_finalization(job_dir: Path, manifest: dict, version_id: str | None) -> None:
    staging = job_dir / FINALIZATION_STAGING_PATH
    staged_note_path = staging / "note.md"
    staged_frames = staging / "frames"
    if not staged_note_path.is_file() or not staged_frames.is_dir():
        raise FileNotFoundError("Prepared finalization files are incomplete. Rebuild the review before finalizing.")

    manifest_version_id = str(manifest.get("version_id") or "")
    if version_id and manifest_version_id and version_id != manifest_version_id:
        raise ValueError("The prepared finalization belongs to a different note version. Reload the review before finalizing.")
    active_version_id = load_note_version_index(job_dir).active_version_id or ""
    if manifest_version_id and active_version_id and manifest_version_id != active_version_id:
        raise ValueError("The active note version changed after finalization was prepared. Reload the review before finalizing.")

    final_note = staged_note_path.read_text(encoding="utf-8-sig")
    final_hash = hashlib.sha256(final_note.encode("utf-8")).hexdigest()
    if final_hash != str(manifest.get("final_note_sha256") or ""):
        raise ValueError("Prepared finalization note failed its integrity check.")
    current_note = (job_dir / "note.md").read_text(encoding="utf-8-sig")
    current_hash = hashlib.sha256(current_note.encode("utf-8")).hexdigest()
    allowed_hashes = {
        str(manifest.get("source_note_sha256") or ""),
        final_hash,
    }
    if current_hash not in allowed_hashes:
        raise ValueError("The note changed after finalization was prepared. Reload the review before finalizing.")

    _publish_staged_frames(job_dir, staged_frames)
    atomic_write_text(job_dir / "note.md", final_note, encoding="utf-8-sig")
    _sync_active_note_version(job_dir, final_note)
    staged_review_draft = staging / "review_draft.json"
    if staged_review_draft.is_file():
        finalized_review_draft = ReviewDraft.model_validate_json(staged_review_draft.read_text(encoding="utf-8"))
        write_review_draft(job_dir, finalized_review_draft, manifest_version_id or version_id)

    committed = dict(manifest)
    committed["status"] = "note_committed"
    atomic_write_json(job_dir / FINALIZATION_MANIFEST_PATH, committed)


def _load_finalization_manifest(job_dir: Path) -> dict | None:
    path = job_dir / FINALIZATION_MANIFEST_PATH
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return payload if isinstance(payload, dict) else None


def _discard_finalization_transaction(job_dir: Path) -> None:
    assert_current_operation_lease()
    (job_dir / FINALIZATION_MANIFEST_PATH).unlink(missing_ok=True)
    shutil.rmtree(job_dir / FINALIZATION_STAGING_PATH, ignore_errors=True)


def _stage_selected_frames(
    job_dir: Path,
    selected: list[FrameCandidate],
    destination: Path,
) -> dict[str, str]:
    frame_map: dict[str, str] = {}
    for index, candidate in enumerate(selected, start=1):
        source_path = resolve_job_relative_path(job_dir, candidate.path)
        if not source_path.exists() or not source_path.is_file():
            raise FileNotFoundError(f"Selected frame is missing: {candidate.id}")
        frame_rel = f"frames/frame_{index:03d}.jpg"
        shutil.copyfile(source_path, destination / f"frame_{index:03d}.jpg")
        frame_map[candidate.id] = frame_rel
    return frame_map


def _publish_staged_frames(job_dir: Path, staged_frames: Path) -> None:
    temporary = job_dir / f".frames.{uuid4().hex}.finalizing"
    try:
        shutil.copytree(staged_frames, temporary)
        atomic_replace_directory(temporary, job_dir / "frames")
    finally:
        if temporary.exists():
            shutil.rmtree(temporary, ignore_errors=True)


def _selected_candidates(job_dir: Path) -> list[FrameCandidate]:
    index = load_frame_candidate_index(job_dir)
    if index is None:
        raise FileNotFoundError("Frame candidates are not available.")
    return sorted(
        [candidate for candidate in index.candidates if candidate.selected and not candidate.rejected],
        key=lambda candidate: (candidate.chapter_index, candidate.time, candidate.id),
    )


def _selected_candidates_from_review_draft(job_dir: Path, draft: ReviewDraft | None) -> list[FrameCandidate]:
    if draft is None:
        return _selected_candidates(job_dir)
    index = load_frame_candidate_index(job_dir)
    if index is None:
        raise FileNotFoundError("Frame candidates are not available.")
    candidate_by_id = {candidate.id: candidate for candidate in index.candidates}
    selected_ids: list[str] = []
    for paragraph in draft.paragraphs:
        selected_ids.extend(paragraph.selected_frame_ids)
    missing_ids = [candidate_id for candidate_id in selected_ids if candidate_id not in candidate_by_id]
    if missing_ids:
        raise FileNotFoundError(f"Selected frame candidate is missing: {missing_ids[0]}")
    return sorted(
        [candidate_by_id[candidate_id] for candidate_id in selected_ids],
        key=lambda candidate: (candidate.chapter_index, candidate.time, candidate.id),
    )


def _render_note_with_selected_frames(
    note_text: str,
    selected: list[FrameCandidate],
    frame_map: dict[str, str],
) -> str:
    by_chapter: dict[int, list[FrameCandidate]] = defaultdict(list)
    for candidate in selected:
        by_chapter[candidate.chapter_index].append(candidate)

    rendered: list[str] = []
    current_chapter = -1
    inserted_chapters: set[int] = set()
    for line in note_text.splitlines():
        if HEADING_PATTERN.match(line):
            current_chapter += 1
        if _is_existing_frame_line(line):
            continue
        rendered.append(line)
        if current_chapter >= 0 and current_chapter not in inserted_chapters and TIME_RANGE_PATTERN.search(line):
            rendered.extend(_candidate_markdown_lines(by_chapter.get(current_chapter, []), frame_map))
            inserted_chapters.add(current_chapter)
    return "\n".join(rendered).rstrip() + "\n"


def _render_note_with_review_draft(
    note_text: str,
    draft: ReviewDraft,
    selected: list[FrameCandidate],
    frame_map: dict[str, str],
) -> str:
    by_chapter: dict[int, list[FrameCandidate]] = defaultdict(list)
    for candidate in selected:
        by_chapter[candidate.chapter_index].append(candidate)
    paragraphs_by_chapter = {paragraph.chapter_index: paragraph for paragraph in draft.paragraphs}

    rendered: list[str] = []
    current_chapter = -1
    inserted_chapters: set[int] = set()
    skipping_old_body = False
    for line in note_text.splitlines():
        if HEADING_PATTERN.match(line):
            current_chapter += 1
            skipping_old_body = False
            rendered.append(line)
            continue
        if current_chapter >= 0 and current_chapter in paragraphs_by_chapter:
            paragraph = paragraphs_by_chapter[current_chapter]
            if _is_existing_frame_line(line):
                continue
            if current_chapter not in inserted_chapters and TIME_RANGE_PATTERN.search(line):
                rendered.append(line)
                rendered.extend(_candidate_markdown_lines(by_chapter.get(current_chapter, []), frame_map))
                body = paragraph.body.strip()
                if body:
                    rendered.extend(["", body, ""])
                inserted_chapters.add(current_chapter)
                skipping_old_body = True
                continue
            if skipping_old_body:
                continue
        if _is_existing_frame_line(line):
            continue
        rendered.append(line)
    return "\n".join(rendered).rstrip() + "\n"


def _is_existing_frame_line(line: str) -> bool:
    if IMAGE_LINE_PATTERN.match(line):
        return True
    stripped = line.strip()
    return stripped.startswith(">") and ("关键帧" in stripped or "Key frame" in stripped)


def _candidate_markdown_lines(candidates: list[FrameCandidate], frame_map: dict[str, str]) -> list[str]:
    lines: list[str] = []
    for candidate in candidates:
        frame_path = frame_map[candidate.id]
        reason = candidate.reason.replace("]", ")").strip() or "Selected frame"
        lines.extend(
            [
                "",
                f"![{reason}]({frame_path})",
                "",
                f"> 关键帧：`{seconds_to_hhmmss(candidate.time)}`：{reason}",
                "",
            ]
        )
    return lines


def _sync_active_note_version(job_dir: Path, final_note: str) -> None:
    index = load_note_version_index(job_dir)
    if not index.active_version_id:
        return
    version = get_note_version(index, index.active_version_id)
    if not version:
        return
    try:
        note_path = resolve_job_relative_path(job_dir, version.note_path)
        frame_dir = resolve_job_relative_path(job_dir, version.frame_dir)
    except ValueError:
        return
    atomic_write_text(note_path, final_note, encoding="utf-8-sig")
    root_frames = job_dir / "frames"
    if root_frames.exists():
        frame_dir.parent.mkdir(parents=True, exist_ok=True)
        temporary_frames = frame_dir.with_name(f".{frame_dir.name}.{uuid4().hex}.finalizing")
        try:
            shutil.copytree(root_frames, temporary_frames)
            atomic_replace_directory(temporary_frames, frame_dir)
        finally:
            if temporary_frames.exists():
                shutil.rmtree(temporary_frames, ignore_errors=True)
