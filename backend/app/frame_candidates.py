from __future__ import annotations

import hashlib
import inspect
import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from collections.abc import Callable
from uuid import uuid4

from .atomic_io import atomic_replace_directory, atomic_write_json, atomic_write_text
from .ffmpeg_tools import extract_frame, extract_frames, require_ffmpeg
from .frame_quality import analyze_frame_visual_quality
from .frame_stability import (
    FrameStabilityRequest,
    FrameStabilitySelection,
    select_stable_frame_times,
)
from .models import FrameCandidate, FrameCandidateChapterContext, FrameCandidateIndex, NoteDraft, TranscriptPayload
from .note_versions import load_note_version_draft


FRAME_CANDIDATES_INDEX = Path("review") / "frame_candidates.json"
FRAME_CANDIDATES_CACHE = Path("review") / "frame_candidates.cache.json"
TIME_RANGE_PATTERN = re.compile(r"`?(\d{2}:\d{2}:\d{2})\s+-\s+(\d{2}:\d{2}:\d{2})`?")
KEY_FRAME_PATTERN = re.compile(r"关键帧：`?(\d{2}:\d{2}:\d{2})`?：?(.+)?")
HEADING_PATTERN = re.compile(r"^###\s+(.+?)\s*$")
HASH_DUPLICATE_DISTANCE = 6
HASH_BITS = 64
NOTE_FRAME_BLOCK_PATTERN = re.compile(
    r"!\[[^\]]*\]\(([^)]+)\)\s*(?:\r?\n\s*)+>\s*关键帧：`?(\d{2}:\d{2}:\d{2})`?",
    re.MULTILINE,
)


@dataclass(frozen=True)
class CandidateChapter:
    index: int
    title: str
    start_time: float
    end_time: float
    key_times: list[tuple[float, str]]
    note_excerpt: str = ""


@dataclass(frozen=True)
class CandidateSeed:
    time: float
    reason: str
    source: str


@dataclass(frozen=True)
class CandidatePlan:
    chapter: CandidateChapter
    candidate_number: int
    candidate_id: str
    relative_frame: Path
    seed: CandidateSeed
    stability: FrameStabilitySelection


def build_frame_candidate_index(
    job_dir: Path,
    video_path: Path,
    *,
    duration: float | None,
    candidates_per_chapter: int = 3,
    is_cancelled: Callable[[], bool] | None = None,
) -> FrameCandidateIndex:
    note_text = (job_dir / "note.md").read_text(encoding="utf-8-sig")
    note_draft = load_note_version_draft(job_dir)
    cache_key = _frame_candidate_cache_key(
        video_path,
        note_text,
        note_draft,
        duration,
        candidates_per_chapter,
    )
    cached = _load_compatible_frame_candidate_index(job_dir, cache_key)
    if cached is not None:
        return cached
    chapters = _candidate_chapters(note_text, note_draft, duration)
    transcript = _load_transcript(job_dir)
    final_root = job_dir / "review" / "frame_candidates"
    temporary_root = final_root.with_name(f".frame_candidates.{uuid4().hex}.tmp")
    candidates: list[FrameCandidate] = []
    try:
        prior_hashes: list[tuple[str, str]] = []
        reusable_note_frames = _reusable_note_frames(job_dir, note_text)
        plans = _candidate_plans(
            video_path,
            chapters,
            duration,
            candidates_per_chapter,
            is_cancelled,
        )
        batched_times: dict[Path, float] = {}
        if is_cancelled is not None and "is_cancelled" in inspect.signature(extract_frame).parameters:
            batch_requests: list[tuple[Path, float]] = []
            for plan in plans:
                reusable = reusable_note_frames.get(round(plan.stability.selected_time))
                if reusable is not None and abs(plan.stability.selected_time - plan.seed.time) < 0.25:
                    continue
                batch_requests.append(
                    (
                        temporary_root / plan.relative_frame,
                        plan.stability.selected_time,
                    )
                )
            batched_times = extract_frames(
                video_path,
                batch_requests,
                duration,
                is_cancelled=is_cancelled,
            )
        for plan in plans:
            if is_cancelled and is_cancelled():
                raise RuntimeError("Frame candidate extraction was cancelled.")
            rel_path = (Path("review") / "frame_candidates" / plan.relative_frame).as_posix()
            output_path = temporary_root / plan.relative_frame
            reusable = reusable_note_frames.get(round(plan.stability.selected_time))
            if (
                reusable is not None
                and reusable.exists()
                and abs(plan.stability.selected_time - plan.seed.time) < 0.25
            ):
                _materialize_reused_frame(reusable, output_path)
                actual_time = plan.stability.selected_time
            elif output_path in batched_times:
                actual_time = batched_times[output_path]
            else:
                actual_time = _extract_frame_with_cancellation(
                    video_path,
                    output_path,
                    plan.stability.selected_time,
                    duration,
                    is_cancelled,
                )
            hash_value = average_hash(output_path)
            duplicate_of, similarity = _nearest_duplicate(hash_value, prior_hashes)
            visual_quality = analyze_frame_visual_quality(output_path)
            risk_flags = list(visual_quality.risk_flags)
            if duplicate_of:
                risk_flags.append("duplicate_frame")
            if plan.stability.available and plan.stability.transition_score >= 0.55:
                risk_flags.append("transition_frame")
            candidates.append(
                FrameCandidate(
                    id=plan.candidate_id,
                    chapter_index=plan.chapter.index,
                    time=actual_time,
                    anchor_time=plan.seed.time,
                    time_offset=round(actual_time - plan.seed.time, 3),
                    path=rel_path,
                    reason=plan.seed.reason,
                    note_excerpt=plan.seed.reason,
                    subtitle_excerpt=_subtitle_excerpt_around_time(transcript, actual_time),
                    source=plan.seed.source,
                    hash=hash_value,
                    duplicate_of=duplicate_of,
                    similarity=similarity,
                    quality_score=visual_quality.score,
                    brightness=visual_quality.brightness,
                    contrast=visual_quality.contrast,
                    sharpness=visual_quality.sharpness,
                    dark_ratio=visual_quality.dark_ratio,
                    bright_ratio=visual_quality.bright_ratio,
                    stability_score=plan.stability.stability_score,
                    transition_score=plan.stability.transition_score,
                    scene_sample_count=plan.stability.sample_count,
                    risk_flags=risk_flags,
                    selected=False,
                    rejected=False,
                )
            )
            prior_hashes.append((plan.candidate_id, hash_value))
        candidates = _select_default_candidates(candidates)
        result = FrameCandidateIndex(
            candidates=candidates,
            chapter_contexts=_chapter_contexts(job_dir, chapters, _candidate_times_by_chapter(candidates)),
        )
        atomic_replace_directory(temporary_root, final_root)
    finally:
        shutil.rmtree(temporary_root, ignore_errors=True)
    write_frame_candidate_index(job_dir, result)
    _write_frame_candidate_cache(job_dir, cache_key)
    return result


def _frame_candidate_cache_key(
    video_path: Path,
    note_text: str,
    note_draft: NoteDraft | None,
    duration: float | None,
    candidates_per_chapter: int,
) -> dict:
    stat = video_path.stat()
    return {
        "version": 4,
        "video_size": stat.st_size,
        "video_mtime_ns": stat.st_mtime_ns,
        "note_hash": hashlib.sha256(note_text.encode("utf-8")).hexdigest(),
        "draft_hash": (
            hashlib.sha256(note_draft.model_dump_json().encode("utf-8")).hexdigest()
            if note_draft is not None
            else None
        ),
        "duration": duration,
        "candidates_per_chapter": candidates_per_chapter,
    }


def _candidate_plans(
    video_path: Path,
    chapters: list[CandidateChapter],
    duration: float | None,
    candidates_per_chapter: int,
    is_cancelled: Callable[[], bool] | None,
) -> list[CandidatePlan]:
    raw: list[tuple[CandidateChapter, int, str, Path, CandidateSeed]] = []
    stability_requests: list[FrameStabilityRequest] = []
    for chapter in chapters:
        for candidate_number, seed in enumerate(
            _candidate_seeds(chapter, candidates_per_chapter),
            start=1,
        ):
            candidate_id = f"chapter_{chapter.index + 1:03d}_candidate_{candidate_number:03d}"
            relative_frame = (
                Path(f"chapter_{chapter.index + 1:03d}")
                / f"candidate_{candidate_number:03d}.jpg"
            )
            raw.append((chapter, candidate_number, candidate_id, relative_frame, seed))
            stability_requests.append(
                FrameStabilityRequest(
                    key=candidate_id,
                    anchor_time=seed.time,
                    lower_bound=chapter.start_time,
                    upper_bound=chapter.end_time if chapter.end_time > chapter.start_time else None,
                )
            )
    selections = select_stable_frame_times(
        video_path,
        stability_requests,
        duration,
        is_cancelled=is_cancelled,
    )
    return [
        CandidatePlan(
            chapter=chapter,
            candidate_number=candidate_number,
            candidate_id=candidate_id,
            relative_frame=relative_frame,
            seed=seed,
            stability=selections[candidate_id],
        )
        for chapter, candidate_number, candidate_id, relative_frame, seed in raw
    ]


def _load_compatible_frame_candidate_index(job_dir: Path, cache_key: dict) -> FrameCandidateIndex | None:
    cache_path = job_dir / FRAME_CANDIDATES_CACHE
    index_path = job_dir / FRAME_CANDIDATES_INDEX
    try:
        cached_key = json.loads(cache_path.read_text(encoding="utf-8"))
        if cached_key != cache_key:
            return None
        index = FrameCandidateIndex.model_validate_json(index_path.read_text(encoding="utf-8"))
    except (OSError, TypeError, ValueError):
        return None
    root = job_dir.resolve()
    for candidate in index.candidates:
        path = (root / candidate.path).resolve()
        try:
            path.relative_to(root)
        except ValueError:
            return None
        if not path.is_file() or path.stat().st_size == 0:
            return None
    return index


def _write_frame_candidate_cache(job_dir: Path, cache_key: dict) -> None:
    path = job_dir / FRAME_CANDIDATES_CACHE
    atomic_write_json(path, cache_key)


def _reusable_note_frames(job_dir: Path, note_text: str) -> dict[int, Path]:
    root = job_dir.resolve()
    reusable: dict[int, Path] = {}
    for match in NOTE_FRAME_BLOCK_PATTERN.finditer(note_text):
        raw_path, raw_time = match.groups()
        candidate = (root / raw_path.strip()).resolve()
        try:
            candidate.relative_to(root)
        except ValueError:
            continue
        if candidate.is_file() and candidate.stat().st_size > 0:
            reusable[round(_hhmmss_to_seconds(raw_time))] = candidate
    return reusable


def _materialize_reused_frame(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        destination.unlink()
    try:
        os.link(source, destination)
    except OSError:
        shutil.copy2(source, destination)


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


def write_frame_candidate_index(job_dir: Path, index: FrameCandidateIndex) -> Path:
    path = job_dir / FRAME_CANDIDATES_INDEX
    atomic_write_text(path, index.model_dump_json(indent=2), encoding="utf-8")
    return path


def load_frame_candidate_index(job_dir: Path) -> FrameCandidateIndex | None:
    path = job_dir / FRAME_CANDIDATES_INDEX
    if not path.exists():
        return None
    try:
        index = FrameCandidateIndex.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return _with_chapter_contexts(job_dir, _with_candidate_references(job_dir, index))


def select_frame_candidate(job_dir: Path, candidate_id: str, frame_limit: int | None = None) -> FrameCandidateIndex:
    index = _require_frame_candidate_index(job_dir)
    target = _require_candidate(index, candidate_id)
    next_selected = not target.selected
    if next_selected and frame_limit is not None:
        selected_count = sum(1 for candidate in index.candidates if candidate.selected and not candidate.rejected)
        if selected_count >= frame_limit:
            raise ValueError(f"Cannot select more frame candidates because frame limit is {frame_limit}.")
    updated: list[FrameCandidate] = []
    for candidate in index.candidates:
        if candidate.id == candidate_id:
            updated.append(candidate.model_copy(update={"selected": next_selected, "rejected": False}))
        else:
            updated.append(candidate)
    new_index = FrameCandidateIndex(candidates=updated, chapter_contexts=index.chapter_contexts)
    write_frame_candidate_index(job_dir, new_index)
    return new_index


def reject_frame_candidate(job_dir: Path, candidate_id: str) -> FrameCandidateIndex:
    index = _require_frame_candidate_index(job_dir)
    _require_candidate(index, candidate_id)
    updated = [
        candidate.model_copy(update={"selected": False, "rejected": True})
        if candidate.id == candidate_id
        else candidate
        for candidate in index.candidates
    ]
    new_index = FrameCandidateIndex(candidates=updated, chapter_contexts=index.chapter_contexts)
    write_frame_candidate_index(job_dir, new_index)
    return new_index


def average_hash(path: Path) -> str:
    pixels = _read_grayscale_pixels(path)
    if len(pixels) == HASH_BITS:
        average = sum(pixels) / HASH_BITS
        bits = "".join("1" if pixel >= average else "0" for pixel in pixels)
        return f"{int(bits, 2):016x}"
    data = path.read_bytes()
    return hashlib.blake2b(data, digest_size=8).hexdigest() if data else ""


def _candidate_chapters(
    note_text: str,
    note_draft: NoteDraft | None,
    duration: float | None,
) -> list[CandidateChapter]:
    structured = _candidate_chapters_from_draft(note_draft, duration)
    if structured:
        return structured
    return _parse_candidate_chapters(note_text, duration)


def _candidate_chapters_from_draft(
    note_draft: NoteDraft | None,
    duration: float | None,
) -> list[CandidateChapter]:
    if note_draft is None or not note_draft.chapters:
        return []
    chapters: list[CandidateChapter] = []
    for chapter_index, chapter in enumerate(note_draft.chapters):
        start_time, end_time = _normalized_chapter_range(
            chapter.start_time,
            chapter.end_time,
            duration,
        )
        key_times = [
            (moment.time, moment.reason)
            for moment in note_draft.key_moments
            if (
                moment.chapter_index == chapter_index
                or start_time <= moment.time <= end_time
            )
        ]
        note_excerpt = " ".join(
            [
                *(bullet.strip() for bullet in chapter.bullets if bullet.strip()),
                chapter.detail.strip(),
            ]
        ).strip()[:260]
        chapters.append(
            CandidateChapter(
                index=chapter_index,
                title=chapter.title.strip() or f"第 {chapter_index + 1} 章",
                start_time=start_time,
                end_time=end_time,
                key_times=key_times,
                note_excerpt=note_excerpt,
            )
        )
    return chapters


def _normalized_chapter_range(
    start_time: float,
    end_time: float,
    duration: float | None,
) -> tuple[float, float]:
    upper = max(0.0, float(duration)) if duration is not None else None
    start = max(0.0, float(start_time))
    end = max(start, float(end_time))
    if upper is not None:
        start = min(start, upper)
        end = min(max(start, end), upper)
    return start, end


def _parse_candidate_chapters(note_text: str, duration: float | None) -> list[CandidateChapter]:
    lines = note_text.splitlines()
    headings = [(index, match.group(1).strip()) for index, line in enumerate(lines) if (match := HEADING_PATTERN.match(line))]
    chapters: list[CandidateChapter] = []
    for chapter_index, (line_index, title) in enumerate(headings):
        next_line_index = headings[chapter_index + 1][0] if chapter_index + 1 < len(headings) else len(lines)
        body_lines = lines[line_index + 1 : next_line_index]
        start_time, end_time = _find_time_range(body_lines, duration)
        chapters.append(
            CandidateChapter(
                index=chapter_index,
                title=title,
                start_time=start_time,
                end_time=end_time,
                key_times=_find_key_times(body_lines),
                note_excerpt=_note_excerpt_from_lines(body_lines),
            )
        )
    if chapters:
        return chapters
    return [
        CandidateChapter(
            index=0,
            title="全文",
            start_time=0.0,
            end_time=float(duration or 0),
            key_times=[],
            note_excerpt="",
        )
    ]


def _note_excerpt_from_lines(lines: list[str]) -> str:
    excerpt: list[str] = []
    for line in lines:
        stripped = line.strip()
        if (
            stripped
            and not stripped.startswith("!")
            and "关键帧：" not in stripped
            and TIME_RANGE_PATTERN.search(stripped) is None
        ):
            excerpt.append(stripped)
        if len(" ".join(excerpt)) > 220:
            break
    return " ".join(excerpt)[:260]


def _candidate_seeds(chapter: CandidateChapter, limit: int) -> list[CandidateSeed]:
    seeds: list[CandidateSeed] = [
        CandidateSeed(time=time, reason=reason or f"Key frame: {chapter.title}", source="note_key_moment")
        for time, reason in chapter.key_times
    ]
    if chapter.end_time > chapter.start_time:
        span = chapter.end_time - chapter.start_time
        fallback_times = [
            chapter.start_time + span * 0.25,
            chapter.start_time + span * 0.5,
            chapter.start_time + span * 0.75,
        ]
    else:
        fallback_times = [chapter.start_time]
    for timestamp in fallback_times:
        seeds.append(
            CandidateSeed(
                time=timestamp,
                reason=f"Chapter frame: {chapter.title}",
                source="chapter_fallback",
            )
        )

    unique: list[CandidateSeed] = []
    for seed in seeds:
        if any(abs(seed.time - existing.time) < 0.001 for existing in unique):
            continue
        unique.append(seed)
        if len(unique) >= limit:
            break
    return unique


def _chapter_contexts(
    job_dir: Path,
    chapters: list[CandidateChapter],
    candidate_times_by_chapter: dict[int, list[float]] | None = None,
) -> list[FrameCandidateChapterContext]:
    transcript = _load_transcript(job_dir)
    contexts: list[FrameCandidateChapterContext] = []
    for chapter in chapters:
        candidate_times = candidate_times_by_chapter.get(chapter.index, []) if candidate_times_by_chapter else []
        subtitle_excerpt = (
            _subtitle_excerpt_around_time(transcript, candidate_times[0])
            if candidate_times
            else _subtitle_excerpt_for_range(transcript, chapter.start_time, chapter.end_time)
        )
        contexts.append(
            FrameCandidateChapterContext(
                chapter_index=chapter.index,
                title=chapter.title,
                start_time=chapter.start_time,
                end_time=chapter.end_time,
                note_excerpt=chapter.note_excerpt or _note_excerpt_for_chapter(job_dir, chapter.title),
                subtitle_excerpt=subtitle_excerpt,
            )
        )
    return contexts


def _with_chapter_contexts(job_dir: Path, index: FrameCandidateIndex) -> FrameCandidateIndex:
    chapters = _chapters_for_existing_index(job_dir, index)
    if not chapters:
        return index
    return index.model_copy(
        update={"chapter_contexts": _chapter_contexts(job_dir, chapters, _candidate_times_by_chapter(index.candidates))}
    )


def _with_candidate_references(job_dir: Path, index: FrameCandidateIndex) -> FrameCandidateIndex:
    transcript = _load_transcript(job_dir)
    candidates: list[FrameCandidate] = []
    changed = False
    for candidate in index.candidates:
        note_excerpt = candidate.note_excerpt or candidate.reason
        subtitle_excerpt = candidate.subtitle_excerpt or _subtitle_excerpt_around_time(transcript, candidate.time)
        changed = changed or note_excerpt != candidate.note_excerpt or subtitle_excerpt != candidate.subtitle_excerpt
        candidates.append(candidate.model_copy(update={"note_excerpt": note_excerpt, "subtitle_excerpt": subtitle_excerpt}))
    if not changed:
        return index
    return index.model_copy(update={"candidates": candidates})


def _candidate_times_by_chapter(candidates: list[FrameCandidate]) -> dict[int, list[float]]:
    times_by_chapter: dict[int, list[float]] = {}
    for candidate in candidates:
        times_by_chapter.setdefault(candidate.chapter_index, []).append(candidate.time)
    for times in times_by_chapter.values():
        times.sort()
    return times_by_chapter


def _chapters_for_existing_index(job_dir: Path, index: FrameCandidateIndex) -> list[CandidateChapter]:
    duration = _duration_from_metadata(job_dir)
    note_path = job_dir / "note.md"
    if note_path.exists():
        chapters = _candidate_chapters(
            note_path.read_text(encoding="utf-8-sig"),
            load_note_version_draft(job_dir),
            duration,
        )
    else:
        chapters = _candidate_chapters_from_draft(load_note_version_draft(job_dir), duration)
    chapters_by_index = {chapter.index: chapter for chapter in chapters}
    candidate_indexes = sorted({candidate.chapter_index for candidate in index.candidates})
    for chapter_index in candidate_indexes:
        if chapter_index not in chapters_by_index:
            chapters_by_index[chapter_index] = CandidateChapter(
                index=chapter_index,
                title=f"第 {chapter_index + 1} 章",
                start_time=0.0,
                end_time=float(duration or 0),
                key_times=[],
                note_excerpt="",
            )
    return [chapters_by_index[index] for index in sorted(chapters_by_index)]


def _duration_from_metadata(job_dir: Path) -> float | None:
    metadata_path = job_dir / "metadata.json"
    if not metadata_path.exists():
        return None
    try:
        payload = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        return None
    duration = payload.get("duration_seconds")
    return float(duration) if isinstance(duration, (int, float)) else None


def _load_transcript(job_dir: Path) -> TranscriptPayload:
    transcript_path = job_dir / "transcript.json"
    if not transcript_path.exists():
        return TranscriptPayload()
    try:
        return TranscriptPayload.model_validate(json.loads(transcript_path.read_text(encoding="utf-8")))
    except (OSError, ValueError, json.JSONDecodeError):
        return TranscriptPayload()


def _note_excerpt_for_chapter(job_dir: Path, title: str) -> str:
    note_path = job_dir / "note.md"
    if not note_path.exists():
        return ""
    lines = note_path.read_text(encoding="utf-8-sig").splitlines()
    in_target = False
    excerpt: list[str] = []
    for line in lines:
        heading = HEADING_PATTERN.match(line)
        if heading:
            if in_target:
                break
            in_target = heading.group(1).strip() == title
            continue
        if in_target:
            stripped = line.strip()
            if stripped and not stripped.startswith("!") and "关键帧：" not in stripped:
                excerpt.append(stripped)
        if len(" ".join(excerpt)) > 220:
            break
    return " ".join(excerpt)[:260]


def _subtitle_excerpt_for_range(transcript: TranscriptPayload, start_time: float, end_time: float) -> str:
    lines = [
        segment.text.strip()
        for segment in transcript.segments
        if segment.text.strip() and segment.end >= start_time and segment.start <= end_time
    ]
    return " ".join(lines)[:260]


def _subtitle_excerpt_around_time(transcript: TranscriptPayload, timestamp: float, window_seconds: float = 30.0) -> str:
    start_time = max(0.0, timestamp - window_seconds)
    end_time = timestamp + window_seconds
    lines = [
        segment.text.strip()
        for segment in transcript.segments
        if segment.text.strip() and segment.end >= start_time and segment.start <= end_time
    ]
    if not lines:
        nearest = min(
            (segment for segment in transcript.segments if segment.text.strip()),
            key=lambda segment: abs(((segment.start + segment.end) / 2) - timestamp),
            default=None,
        )
        if nearest is not None:
            lines = [nearest.text.strip()]
    return " ".join(lines)[:320]


def _find_time_range(lines: list[str], duration: float | None) -> tuple[float, float]:
    for line in lines[:8]:
        match = TIME_RANGE_PATTERN.search(line)
        if match:
            return _hhmmss_to_seconds(match.group(1)), _hhmmss_to_seconds(match.group(2))
    return 0.0, float(duration or 0)


def _find_key_times(lines: list[str]) -> list[tuple[float, str]]:
    key_times: list[tuple[float, str]] = []
    for line in lines:
        match = KEY_FRAME_PATTERN.search(line)
        if match:
            key_times.append((_hhmmss_to_seconds(match.group(1)), (match.group(2) or "").strip()))
    return key_times


def _hhmmss_to_seconds(value: str) -> float:
    hours, minutes, seconds = [int(part) for part in value.split(":")]
    return float(hours * 3600 + minutes * 60 + seconds)


def _nearest_duplicate(hash_value: str, prior_hashes: list[tuple[str, str]]) -> tuple[str | None, float]:
    for candidate_id, prior_hash in prior_hashes:
        distance = _hamming_distance(hash_value, prior_hash)
        if distance <= HASH_DUPLICATE_DISTANCE:
            similarity = 1.0 - (distance / HASH_BITS)
            return candidate_id, round(max(0.0, min(1.0, similarity)), 2)
    return None, 0.0


def _select_default_candidates(candidates: list[FrameCandidate]) -> list[FrameCandidate]:
    best_by_chapter: dict[int, str] = {}
    for candidate in candidates:
        current_id = best_by_chapter.get(candidate.chapter_index)
        current = next((item for item in candidates if item.id == current_id), None)
        if current is None or _candidate_selection_rank(candidate) > _candidate_selection_rank(current):
            best_by_chapter[candidate.chapter_index] = candidate.id
    selected_ids = set(best_by_chapter.values())
    return [
        candidate.model_copy(update={"selected": candidate.id in selected_ids})
        for candidate in candidates
    ]


def _candidate_selection_rank(candidate: FrameCandidate) -> tuple[float, float, float]:
    severe_risk = any(
        flag in {"black_frame", "white_frame", "transition_frame"}
        for flag in candidate.risk_flags
    )
    duplicate_penalty = 1.0 if candidate.duplicate_of else 0.0
    severe_penalty = 1.0 if severe_risk else 0.0
    source_bonus = 0.05 if candidate.source == "note_key_moment" else 0.0
    combined_quality = (
        candidate.quality_score * 0.7
        + candidate.stability_score * 0.3
        - candidate.transition_score * 0.2
    )
    return (
        -severe_penalty,
        -duplicate_penalty,
        combined_quality + source_bonus,
    )


def _hamming_distance(left: str, right: str) -> int:
    if left == right:
        return 0
    try:
        return (int(left, 16) ^ int(right, 16)).bit_count()
    except ValueError:
        return HASH_BITS


def _require_frame_candidate_index(job_dir: Path) -> FrameCandidateIndex:
    index = load_frame_candidate_index(job_dir)
    if index is None:
        raise FileNotFoundError("Frame candidates are not available.")
    return index


def _require_candidate(index: FrameCandidateIndex, candidate_id: str) -> FrameCandidate:
    for candidate in index.candidates:
        if candidate.id == candidate_id:
            return candidate
    raise FileNotFoundError(f"Frame candidate not found: {candidate_id}")


def _read_grayscale_pixels(path: Path) -> bytes:
    ffmpeg_path = require_ffmpeg()
    command = [
        ffmpeg_path,
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        str(path),
        "-vf",
        "scale=8:8,format=gray",
        "-frames:v",
        "1",
        "-f",
        "rawvideo",
        "pipe:1",
    ]
    kwargs: dict[str, object] = {"capture_output": True}
    if sys.platform == "win32":
        kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
    try:
        completed = subprocess.run(command, **kwargs)
    except OSError:
        return b""
    if completed.returncode != 0:
        return b""
    return completed.stdout[:HASH_BITS]
