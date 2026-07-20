from __future__ import annotations

import json
import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

from .frame_candidates import load_frame_candidate_index
from .models import ReviewDraft, ReviewDraftParagraph, ReviewSubtitleSegment, TranscriptPayload
from .note_versions import get_note_version, load_note_version_index, resolve_job_relative_path, safe_note_version_id


REVIEW_DRAFT_PATH = Path("review") / "review_draft.json"
HEADING_PATTERN = re.compile(r"^###\s+(.+?)\s*$")
TITLE_PATTERN = re.compile(r"^#\s+(.+?)\s*$")
TIME_RANGE_PATTERN = re.compile(r"`?(\d{2}:\d{2}:\d{2})\s+-\s+(\d{2}:\d{2}:\d{2})`?")
IMAGE_LINE_PATTERN = re.compile(r"^\s*!\[[^\]]*]\([^)]+\)\s*$")


@dataclass
class ParsedReviewChapter:
    index: int
    title: str
    start_time: float
    end_time: float
    body: str


def resolve_review_version_id(job_dir: Path, version_id: str | None = None) -> str | None:
    index = load_note_version_index(job_dir)
    resolved = version_id or index.active_version_id
    if resolved is None:
        return None
    safe_note_version_id(resolved)
    if get_note_version(index, resolved) is None:
        raise FileNotFoundError(f"Note version not found: {resolved}")
    return resolved


def review_note_path(job_dir: Path, version_id: str | None = None) -> Path:
    resolved = resolve_review_version_id(job_dir, version_id)
    if resolved is None:
        return job_dir / "note.md"
    version = get_note_version(load_note_version_index(job_dir), resolved)
    if version is None:
        raise FileNotFoundError(f"Note version not found: {resolved}")
    return resolve_job_relative_path(job_dir, version.note_path)


def review_draft_path(job_dir: Path, version_id: str | None = None) -> Path:
    resolved = resolve_review_version_id(job_dir, version_id)
    if resolved is not None:
        return job_dir / "note_versions" / resolved / REVIEW_DRAFT_PATH
    return job_dir / REVIEW_DRAFT_PATH


def load_review_draft(job_dir: Path, version_id: str | None = None) -> ReviewDraft | None:
    resolved = resolve_review_version_id(job_dir, version_id)
    path = review_draft_path(job_dir, resolved)
    if not path.exists():
        return None
    try:
        draft = ReviewDraft.model_validate_json(path.read_text(encoding="utf-8"))
        if resolved is not None and draft.note_version_id != resolved:
            return None
        return draft
    except (OSError, ValueError):
        return None


def write_review_draft(job_dir: Path, draft: ReviewDraft, version_id: str | None = None) -> Path:
    path = review_draft_path(job_dir, version_id or draft.note_version_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(draft.model_dump_json(indent=2), encoding="utf-8")
    return path


def build_review_draft(job_dir: Path, version_id: str | None = None) -> ReviewDraft:
    resolved = resolve_review_version_id(job_dir, version_id)
    note_path = review_note_path(job_dir, resolved)
    if not note_path.exists():
        raise FileNotFoundError("note.md is required to build a review draft.")
    note_text = note_path.read_text(encoding="utf-8-sig")
    title = _parse_note_title(note_text)
    transcript = _load_transcript(job_dir)
    selected_frames = _selected_frame_ids_by_chapter(job_dir)
    paragraphs = [
        ReviewDraftParagraph(
            id=f"paragraph_{chapter.index + 1:03d}",
            chapter_index=chapter.index,
            title=chapter.title,
            start_time=chapter.start_time,
            end_time=chapter.end_time,
            body=chapter.body,
            subtitle_segments=_subtitle_segments_for_range(transcript, chapter.start_time, chapter.end_time),
            selected_frame_ids=selected_frames.get(chapter.index, []),
        )
        for chapter in _parse_review_chapters(note_text)
    ]
    draft = ReviewDraft(
        note_version_id=resolved,
        source_note_sha256=hashlib.sha256(note_text.encode("utf-8")).hexdigest(),
        title=title,
        paragraphs=paragraphs,
    )
    write_review_draft(job_dir, draft, resolved)
    return draft


def get_or_build_review_draft(job_dir: Path, version_id: str | None = None) -> ReviewDraft:
    resolved = resolve_review_version_id(job_dir, version_id)
    draft = load_review_draft(job_dir, resolved)
    note_path = review_note_path(job_dir, resolved)
    if draft is not None and note_path.exists():
        note_text = note_path.read_text(encoding="utf-8-sig")
        source_hash = hashlib.sha256(note_text.encode("utf-8")).hexdigest()
        if draft.source_note_sha256 == source_hash:
            return draft
    return build_review_draft(job_dir, resolved)


def update_review_draft_paragraph(
    job_dir: Path,
    paragraph_id: str,
    *,
    body: str,
    selected_frame_ids: list[str],
    status: str,
    version_id: str | None = None,
) -> ReviewDraft:
    resolved = resolve_review_version_id(job_dir, version_id)
    draft = get_or_build_review_draft(job_dir, resolved)
    updated_paragraphs: list[ReviewDraftParagraph] = []
    found = False
    for paragraph in draft.paragraphs:
        if paragraph.id != paragraph_id:
            updated_paragraphs.append(paragraph)
            continue
        found = True
        updated_paragraphs.append(
            paragraph.model_copy(
                update={
                    "body": body.strip(),
                    "selected_frame_ids": selected_frame_ids,
                    "status": status,
                }
            )
        )
    if not found:
        raise FileNotFoundError(f"Review paragraph not found: {paragraph_id}")
    updated = draft.model_copy(update={"paragraphs": updated_paragraphs})
    write_review_draft(job_dir, updated, resolved)
    return updated


def _parse_note_title(note_text: str) -> str:
    for line in note_text.splitlines():
        match = TITLE_PATTERN.match(line)
        if match and not line.startswith("##"):
            return match.group(1).strip()
    return "Untitled note"


def _parse_review_chapters(note_text: str) -> list[ParsedReviewChapter]:
    chapters: list[ParsedReviewChapter] = []
    current_title: str | None = None
    current_lines: list[str] = []
    for line in note_text.splitlines():
        heading = HEADING_PATTERN.match(line)
        if heading:
            if current_title is not None:
                chapters.append(_chapter_from_lines(len(chapters), current_title, current_lines))
            current_title = heading.group(1).strip()
            current_lines = []
            continue
        if current_title is not None:
            current_lines.append(line)
    if current_title is not None:
        chapters.append(_chapter_from_lines(len(chapters), current_title, current_lines))
    return chapters


def _chapter_from_lines(index: int, title: str, lines: list[str]) -> ParsedReviewChapter:
    start_time = 0.0
    end_time = 0.0
    body_lines: list[str] = []
    for line in lines:
        time_match = TIME_RANGE_PATTERN.search(line)
        if time_match:
            start_time = _hhmmss_to_seconds(time_match.group(1))
            end_time = _hhmmss_to_seconds(time_match.group(2))
            continue
        stripped = line.strip()
        if not stripped:
            continue
        if IMAGE_LINE_PATTERN.match(stripped):
            continue
        if stripped.startswith(">"):
            continue
        body_lines.append(stripped)
    return ParsedReviewChapter(index=index, title=title, start_time=start_time, end_time=end_time, body="\n".join(body_lines))


def _load_transcript(job_dir: Path) -> TranscriptPayload:
    transcript_path = job_dir / "transcript.json"
    if not transcript_path.exists():
        return TranscriptPayload()
    try:
        return TranscriptPayload.model_validate(json.loads(transcript_path.read_text(encoding="utf-8")))
    except (OSError, ValueError, json.JSONDecodeError):
        return TranscriptPayload()


def _subtitle_segments_for_range(
    transcript: TranscriptPayload,
    start_time: float,
    end_time: float,
) -> list[ReviewSubtitleSegment]:
    return [
        ReviewSubtitleSegment(start=segment.start, end=segment.end, text=segment.text.strip())
        for segment in transcript.segments
        if segment.text.strip() and segment.end >= start_time and segment.start <= end_time
    ]


def _selected_frame_ids_by_chapter(job_dir: Path) -> dict[int, list[str]]:
    index = load_frame_candidate_index(job_dir)
    if index is None:
        return {}
    selected: dict[int, list[str]] = {}
    for candidate in sorted(index.candidates, key=lambda item: (item.chapter_index, item.time, item.id)):
        if candidate.selected and not candidate.rejected:
            selected.setdefault(candidate.chapter_index, []).append(candidate.id)
    return selected


def _hhmmss_to_seconds(value: str) -> float:
    hours, minutes, seconds = [int(part) for part in value.split(":")]
    return float(hours * 3600 + minutes * 60 + seconds)
