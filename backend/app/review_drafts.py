from __future__ import annotations

import json
import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

from .atomic_io import atomic_write_text
from .frame_candidates import load_frame_candidate_index
from .llm import transcript_segment_id
from .models import NoteDraft, ReviewDraft, ReviewDraftParagraph, ReviewSubtitleSegment, TranscriptPayload
from .note_evidence import (
    NoteEvidenceIndex,
    audit_claim_text,
    load_note_version_evidence,
    transcript_fingerprint,
)
from .note_versions import (
    get_note_version,
    load_note_version_draft,
    load_note_version_index,
    resolve_job_relative_path,
    safe_note_version_id,
)
from .transcript_corrections import load_preferred_transcript_payload


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
    atomic_write_text(path, draft.model_dump_json(indent=2), encoding="utf-8")
    return path


def build_review_draft(job_dir: Path, version_id: str | None = None) -> ReviewDraft:
    resolved = resolve_review_version_id(job_dir, version_id)
    note_path = review_note_path(job_dir, resolved)
    if not note_path.exists():
        raise FileNotFoundError("note.md is required to build a review draft.")
    note_text = note_path.read_text(encoding="utf-8-sig")
    note_draft = load_note_version_draft(job_dir, resolved)
    title = note_draft.title.strip() if note_draft is not None and note_draft.title.strip() else _parse_note_title(note_text)
    transcript = _load_transcript(job_dir)
    selected_frames = _selected_frame_ids_by_chapter(job_dir)
    loaded_evidence = load_note_version_evidence(job_dir, resolved)
    evidence = loaded_evidence[1] if loaded_evidence is not None else None
    paragraphs = []
    chapters = _review_chapters_from_draft(note_draft) or _parse_review_chapters(note_text)
    for chapter in chapters:
        paragraph = ReviewDraftParagraph(
            id=f"paragraph_{chapter.index + 1:03d}",
            chapter_index=chapter.index,
            title=chapter.title,
            start_time=chapter.start_time,
            end_time=chapter.end_time,
            body=chapter.body,
            selected_frame_ids=selected_frames.get(chapter.index, []),
        )
        paragraphs.append(_enrich_paragraph_evidence(paragraph, transcript, evidence))
    draft = ReviewDraft(
        schema_version=2,
        note_version_id=resolved,
        source_note_sha256=hashlib.sha256(note_text.encode("utf-8")).hexdigest(),
        source_transcript_sha256=transcript_fingerprint(transcript),
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
            if draft.schema_version >= 2 and draft.source_transcript_sha256:
                return draft
            return upgrade_review_draft_evidence(job_dir, draft, resolved)
    return build_review_draft(job_dir, resolved)


def upgrade_review_draft_evidence(
    job_dir: Path,
    draft: ReviewDraft,
    version_id: str | None = None,
) -> ReviewDraft:
    resolved = resolve_review_version_id(job_dir, version_id or draft.note_version_id)
    transcript = _load_transcript(job_dir)
    loaded_evidence = load_note_version_evidence(job_dir, resolved)
    evidence = loaded_evidence[1] if loaded_evidence is not None else None
    upgraded = draft.model_copy(
        update={
            "schema_version": 2,
            "source_transcript_sha256": transcript_fingerprint(transcript),
            "paragraphs": [
                _enrich_paragraph_evidence(paragraph, transcript, evidence)
                for paragraph in draft.paragraphs
            ],
        }
    )
    write_review_draft(job_dir, upgraded, resolved)
    return upgraded


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
        updated_paragraph = paragraph.model_copy(
            update={
                "body": body.strip(),
                "selected_frame_ids": selected_frame_ids,
                "status": status,
            }
        )
        updated_paragraphs.append(
            _refresh_paragraph_claim_audit(
                updated_paragraph,
                _load_transcript(job_dir),
                draft.source_transcript_sha256,
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


def _review_chapters_from_draft(note_draft: NoteDraft | None) -> list[ParsedReviewChapter]:
    if note_draft is None or not note_draft.chapters:
        return []
    chapters: list[ParsedReviewChapter] = []
    for index, chapter in enumerate(note_draft.chapters):
        body_lines = [f"- {bullet.strip()}" for bullet in chapter.bullets if bullet.strip()]
        if chapter.detail.strip():
            body_lines.append(chapter.detail.strip())
        if chapter.quote_times:
            body_lines.append("参考时间：")
            body_lines.extend(f"- `{quote_time.strip()}`" for quote_time in chapter.quote_times if quote_time.strip())
        chapters.append(
            ParsedReviewChapter(
                index=index,
                title=chapter.title.strip() or f"第 {index + 1} 章",
                start_time=max(0.0, float(chapter.start_time)),
                end_time=max(float(chapter.start_time), float(chapter.end_time)),
                body="\n".join(body_lines),
            )
        )
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
    try:
        return TranscriptPayload.model_validate(load_preferred_transcript_payload(job_dir))
    except (FileNotFoundError, OSError, ValueError, json.JSONDecodeError):
        return TranscriptPayload()


def _subtitle_segments_for_range(
    transcript: TranscriptPayload,
    start_time: float,
    end_time: float,
) -> list[ReviewSubtitleSegment]:
    return [
        ReviewSubtitleSegment(
            start=segment.start,
            end=segment.end,
            text=segment.text.strip(),
            segment_id=transcript_segment_id(segment),
        )
        for segment in transcript.segments
        if segment.text.strip() and segment.end >= start_time and segment.start <= end_time
    ]


def _subtitle_segments_for_ids(
    transcript: TranscriptPayload,
    segment_ids: list[str],
) -> list[ReviewSubtitleSegment]:
    wanted = set(segment_ids)
    return [
        ReviewSubtitleSegment(
            start=segment.start,
            end=segment.end,
            text=segment.text.strip(),
            segment_id=segment_id,
        )
        for segment in sorted(
            transcript.segments,
            key=lambda item: (item.start, item.end, item.text),
        )
        if segment.text.strip()
        and (segment_id := transcript_segment_id(segment)) in wanted
    ]


def _enrich_paragraph_evidence(
    paragraph: ReviewDraftParagraph,
    transcript: TranscriptPayload,
    evidence: NoteEvidenceIndex | None,
) -> ReviewDraftParagraph:
    chapter_evidence = next(
        (
            chapter
            for chapter in evidence.chapters
            if chapter.chapter_index == paragraph.chapter_index
        ),
        None,
    ) if evidence is not None else None
    fallback_segments = _subtitle_segments_for_range(
        transcript,
        paragraph.start_time,
        paragraph.end_time,
    )
    segment_ids = (
        list(chapter_evidence.segment_ids)
        if chapter_evidence is not None and chapter_evidence.segment_ids
        else [segment.segment_id for segment in fallback_segments if segment.segment_id]
    )
    subtitle_segments = _subtitle_segments_for_ids(transcript, segment_ids) or fallback_segments
    current_ids = {
        transcript_segment_id(segment)
        for segment in transcript.segments
    }
    references_resolve = bool(segment_ids) and all(
        segment_id in current_ids
        for segment_id in segment_ids
    )
    if chapter_evidence is not None:
        references_resolve = (
            references_resolve
            and chapter_evidence.reference_valid
            and evidence is not None
            and evidence.transcript_sha256 == transcript_fingerprint(transcript)
        )
    evidence_text = " ".join(segment.text for segment in subtitle_segments)
    missing_numbers, missing_identifiers = audit_claim_text(
        "\n".join([paragraph.title, paragraph.body]),
        evidence_text,
    )
    return paragraph.model_copy(
        update={
            "subtitle_segments": subtitle_segments,
            "evidence_segment_ids": segment_ids,
            "evidence_reference_valid": references_resolve,
            "unsupported_numeric_claims": missing_numbers,
            "unsupported_technical_identifiers": missing_identifiers,
        }
    )


def _refresh_paragraph_claim_audit(
    paragraph: ReviewDraftParagraph,
    transcript: TranscriptPayload,
    source_transcript_sha256: str,
) -> ReviewDraftParagraph:
    segments_by_id = {
        transcript_segment_id(segment): segment
        for segment in transcript.segments
    }
    segment_ids = paragraph.evidence_segment_ids or [
        segment.segment_id
        for segment in paragraph.subtitle_segments
        if segment.segment_id
    ]
    subtitle_segments = _subtitle_segments_for_ids(transcript, segment_ids)
    evidence_text = " ".join(segment.text for segment in subtitle_segments)
    missing_numbers, missing_identifiers = audit_claim_text(
        "\n".join([paragraph.title, paragraph.body]),
        evidence_text,
    )
    references_resolve = (
        bool(segment_ids)
        and source_transcript_sha256 == transcript_fingerprint(transcript)
        and all(segment_id in segments_by_id for segment_id in segment_ids)
    )
    return paragraph.model_copy(
        update={
            "subtitle_segments": subtitle_segments,
            "evidence_segment_ids": segment_ids,
            "evidence_reference_valid": references_resolve,
            "unsupported_numeric_claims": missing_numbers,
            "unsupported_technical_identifiers": missing_identifiers,
        }
    )


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
