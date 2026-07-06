from __future__ import annotations

import hashlib
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from .ffmpeg_tools import extract_frame, require_ffmpeg
from .models import FrameCandidate, FrameCandidateIndex


FRAME_CANDIDATES_INDEX = Path("review") / "frame_candidates.json"
TIME_RANGE_PATTERN = re.compile(r"`?(\d{2}:\d{2}:\d{2})\s+-\s+(\d{2}:\d{2}:\d{2})`?")
KEY_FRAME_PATTERN = re.compile(r"关键帧：`?(\d{2}:\d{2}:\d{2})`?：?(.+)?")
HEADING_PATTERN = re.compile(r"^###\s+(.+?)\s*$")
HASH_DUPLICATE_DISTANCE = 6
HASH_BITS = 64


@dataclass(frozen=True)
class CandidateChapter:
    index: int
    title: str
    start_time: float
    end_time: float
    key_times: list[tuple[float, str]]


@dataclass(frozen=True)
class CandidateSeed:
    time: float
    reason: str
    source: str


def build_frame_candidate_index(
    job_dir: Path,
    video_path: Path,
    *,
    duration: float | None,
    candidates_per_chapter: int = 3,
) -> FrameCandidateIndex:
    note_text = (job_dir / "note.md").read_text(encoding="utf-8-sig")
    chapters = _parse_candidate_chapters(note_text, duration)
    candidates: list[FrameCandidate] = []
    selected_by_chapter: set[int] = set()
    prior_hashes: list[tuple[str, str]] = []

    for chapter in chapters:
        for candidate_number, seed in enumerate(_candidate_seeds(chapter, candidates_per_chapter), start=1):
            candidate_id = f"chapter_{chapter.index + 1:03d}_candidate_{candidate_number:03d}"
            rel_path = f"review/frame_candidates/chapter_{chapter.index + 1:03d}/candidate_{candidate_number:03d}.jpg"
            actual_time = extract_frame(video_path, job_dir / rel_path, seed.time, duration)
            hash_value = average_hash(job_dir / rel_path)
            duplicate_of, similarity = _nearest_duplicate(hash_value, prior_hashes)
            risk_flags = ["duplicate_frame"] if duplicate_of else []
            selected = duplicate_of is None and chapter.index not in selected_by_chapter
            if selected:
                selected_by_chapter.add(chapter.index)
            candidates.append(
                FrameCandidate(
                    id=candidate_id,
                    chapter_index=chapter.index,
                    time=actual_time,
                    path=rel_path,
                    reason=seed.reason,
                    source=seed.source,
                    hash=hash_value,
                    duplicate_of=duplicate_of,
                    similarity=similarity,
                    risk_flags=risk_flags,
                    selected=selected,
                    rejected=False,
                )
            )
            prior_hashes.append((candidate_id, hash_value))
    return FrameCandidateIndex(candidates=candidates)


def write_frame_candidate_index(job_dir: Path, index: FrameCandidateIndex) -> Path:
    path = job_dir / FRAME_CANDIDATES_INDEX
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(index.model_dump_json(indent=2), encoding="utf-8")
    return path


def load_frame_candidate_index(job_dir: Path) -> FrameCandidateIndex | None:
    path = job_dir / FRAME_CANDIDATES_INDEX
    if not path.exists():
        return None
    try:
        return FrameCandidateIndex.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def select_frame_candidate(job_dir: Path, candidate_id: str) -> FrameCandidateIndex:
    index = _require_frame_candidate_index(job_dir)
    target = _require_candidate(index, candidate_id)
    updated: list[FrameCandidate] = []
    for candidate in index.candidates:
        if candidate.chapter_index != target.chapter_index:
            updated.append(candidate)
        elif candidate.id == candidate_id:
            updated.append(candidate.model_copy(update={"selected": True, "rejected": False}))
        else:
            updated.append(candidate.model_copy(update={"selected": False}))
    new_index = FrameCandidateIndex(candidates=updated)
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
    new_index = FrameCandidateIndex(candidates=updated)
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
        )
    ]


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
