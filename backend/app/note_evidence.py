from __future__ import annotations

import hashlib
import re
import unicodedata
from pathlib import Path

from pydantic import BaseModel, Field

from .llm import transcript_segment_id
from .models import NoteDraft, NoteVersionIndex, ReviewDraft, TranscriptPayload, TranscriptSegment
from .transcript_corrections import load_preferred_transcript_payload


EVIDENCE_FILENAME = "evidence.json"
NUMERIC_CLAIM_PATTERN = re.compile(
    r"(?<![\w])\d+(?:[.,]\d+)*(?:\s*(?:%|％|倍|个|年|月|日|小时|分钟|秒|元|美元|万元|亿元|GB|MB|TB|KB))?",
    re.IGNORECASE,
)
TECHNICAL_IDENTIFIER_PATTERN = re.compile(
    r"(?<!\w)(?:"
    r"[A-Za-z]+[-_.+]\d+(?:[.-]\d+)*[A-Za-z0-9]*"
    r"|[A-Za-z]*\d+[A-Za-z][A-Za-z0-9-]*"
    r"|[A-Z]{2,}"
    r")(?!\w)"
)


class ChapterEvidence(BaseModel):
    chapter_index: int
    title: str
    start_segment_id: str | None = None
    end_segment_id: str | None = None
    segment_ids: list[str] = Field(default_factory=list)
    reference_valid: bool = False


class KeyMomentEvidence(BaseModel):
    moment_index: int
    segment_id: str | None = None
    reference_valid: bool = False


class NoteEvidenceIndex(BaseModel):
    schema_version: int = 1
    transcript_sha256: str
    transcript_segment_count: int
    chapters: list[ChapterEvidence] = Field(default_factory=list)
    key_moments: list[KeyMomentEvidence] = Field(default_factory=list)


class EvidenceAudit(BaseModel):
    transcript_changed: bool = False
    invalid_chapter_references: list[int] = Field(default_factory=list)
    invalid_key_moment_references: list[int] = Field(default_factory=list)
    unsupported_numeric_claims: dict[int, list[str]] = Field(default_factory=dict)
    unsupported_technical_identifiers: dict[int, list[str]] = Field(default_factory=dict)


def build_note_evidence_index(job_dir: Path, draft: NoteDraft) -> NoteEvidenceIndex:
    try:
        transcript = TranscriptPayload.model_validate(load_preferred_transcript_payload(job_dir))
    except (FileNotFoundError, OSError, ValueError):
        transcript = TranscriptPayload()
    segments = sorted(transcript.segments, key=lambda segment: (segment.start, segment.end, segment.text))
    segment_ids = [transcript_segment_id(segment) for segment in segments]
    index_by_id = {segment_id: index for index, segment_id in enumerate(segment_ids)}
    chapters: list[ChapterEvidence] = []
    for chapter_index, chapter in enumerate(draft.chapters):
        start_index = index_by_id.get(str(chapter.start_segment_id or ""))
        end_index = index_by_id.get(str(chapter.end_segment_id or ""))
        reference_valid = start_index is not None and end_index is not None
        if reference_valid:
            lower, upper = sorted((start_index, end_index))
            covered_ids = segment_ids[lower : upper + 1]
        else:
            covered_ids = [
                segment_id
                for segment_id, segment in zip(segment_ids, segments)
                if segment.end >= chapter.start_time and segment.start <= chapter.end_time
            ]
        chapters.append(
            ChapterEvidence(
                chapter_index=chapter_index,
                title=chapter.title,
                start_segment_id=chapter.start_segment_id,
                end_segment_id=chapter.end_segment_id,
                segment_ids=covered_ids,
                reference_valid=reference_valid,
            )
        )

    key_moments = [
        KeyMomentEvidence(
            moment_index=index,
            segment_id=moment.segment_id,
            reference_valid=str(moment.segment_id or "") in index_by_id,
        )
        for index, moment in enumerate(draft.key_moments)
    ]
    return NoteEvidenceIndex(
        transcript_sha256=transcript_fingerprint(transcript),
        transcript_segment_count=len(segments),
        chapters=chapters,
        key_moments=key_moments,
    )


def load_note_version_evidence(
    job_dir: Path,
    version_id: str | None = None,
) -> tuple[NoteDraft, NoteEvidenceIndex, TranscriptPayload] | None:
    index_path = job_dir / "note_versions" / "versions.json"
    if not index_path.exists():
        return None
    try:
        version_index = NoteVersionIndex.model_validate_json(index_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    resolved_version_id = version_id or version_index.active_version_id
    if not resolved_version_id or not _safe_version_id(resolved_version_id):
        return None
    version = next((item for item in version_index.versions if item.id == resolved_version_id), None)
    if version is None:
        return None
    try:
        draft_path = _resolve_job_path(
            job_dir,
            version.draft_path or f"note_versions/{resolved_version_id}/draft.json",
        )
        evidence_path = _resolve_job_path(
            job_dir,
            version.evidence_path or f"note_versions/{resolved_version_id}/{EVIDENCE_FILENAME}",
        )
        draft = NoteDraft.model_validate_json(draft_path.read_text(encoding="utf-8"))
        evidence = NoteEvidenceIndex.model_validate_json(evidence_path.read_text(encoding="utf-8"))
        transcript = TranscriptPayload.model_validate(load_preferred_transcript_payload(job_dir))
    except (OSError, ValueError):
        return None
    return draft, evidence, transcript


def load_active_note_evidence(job_dir: Path) -> tuple[NoteDraft, NoteEvidenceIndex, TranscriptPayload] | None:
    return load_note_version_evidence(job_dir)


def audit_active_note_evidence(job_dir: Path) -> EvidenceAudit | None:
    loaded = load_active_note_evidence(job_dir)
    if loaded is None:
        return None
    draft, evidence, transcript = loaded
    segments_by_id = {
        transcript_segment_id(segment): segment
        for segment in transcript.segments
    }
    current_segment_ids = set(segments_by_id)
    transcript_changed = (
        evidence.transcript_sha256 != transcript_fingerprint(transcript)
        or evidence.transcript_segment_count != len(transcript.segments)
    )
    invalid_chapters = [
        chapter.chapter_index
        for chapter in evidence.chapters
        if (
            not chapter.reference_valid
            or str(chapter.start_segment_id or "") not in current_segment_ids
            or str(chapter.end_segment_id or "") not in current_segment_ids
            or any(segment_id not in current_segment_ids for segment_id in chapter.segment_ids)
        )
    ]
    invalid_moments = [
        moment.moment_index
        for moment in evidence.key_moments
        if not moment.reference_valid or str(moment.segment_id or "") not in current_segment_ids
    ]
    unsupported_numbers: dict[int, list[str]] = {}
    unsupported_identifiers: dict[int, list[str]] = {}
    for chapter_evidence in evidence.chapters:
        if chapter_evidence.chapter_index >= len(draft.chapters):
            continue
        chapter = draft.chapters[chapter_evidence.chapter_index]
        claim_text = "\n".join([chapter.title, *chapter.bullets, chapter.detail])
        evidence_text = " ".join(
            segments_by_id[segment_id].text
            for segment_id in chapter_evidence.segment_ids
            if segment_id in segments_by_id
        )
        missing_numbers = _unsupported_claims(
            _extract_numeric_claims(claim_text),
            _extract_numeric_claims(evidence_text),
        )
        missing_identifiers = _unsupported_claims(
            _extract_technical_identifiers(claim_text),
            _extract_technical_identifiers(evidence_text),
        )
        if missing_numbers:
            unsupported_numbers[chapter_evidence.chapter_index] = missing_numbers
        if missing_identifiers:
            unsupported_identifiers[chapter_evidence.chapter_index] = missing_identifiers

    return EvidenceAudit(
        transcript_changed=transcript_changed,
        invalid_chapter_references=invalid_chapters,
        invalid_key_moment_references=invalid_moments,
        unsupported_numeric_claims=unsupported_numbers,
        unsupported_technical_identifiers=unsupported_identifiers,
    )


def audit_review_draft_evidence(job_dir: Path, review_draft: ReviewDraft) -> EvidenceAudit:
    try:
        transcript = TranscriptPayload.model_validate(load_preferred_transcript_payload(job_dir))
    except (FileNotFoundError, OSError, ValueError):
        transcript = TranscriptPayload()
    segments_by_id = {
        transcript_segment_id(segment): segment
        for segment in transcript.segments
    }
    current_segment_ids = set(segments_by_id)
    current_fingerprint = transcript_fingerprint(transcript)
    transcript_changed = bool(
        review_draft.source_transcript_sha256
        and review_draft.source_transcript_sha256 != current_fingerprint
    )
    invalid_chapters: list[int] = []
    unsupported_numbers: dict[int, list[str]] = {}
    unsupported_identifiers: dict[int, list[str]] = {}
    for paragraph in review_draft.paragraphs:
        segment_ids = paragraph.evidence_segment_ids or [
            segment.segment_id
            for segment in paragraph.subtitle_segments
            if segment.segment_id
        ]
        reference_valid = bool(segment_ids) and all(
            segment_id in current_segment_ids
            for segment_id in segment_ids
        )
        if not paragraph.evidence_reference_valid or not reference_valid:
            invalid_chapters.append(paragraph.chapter_index)
        evidence_text = " ".join(
            segments_by_id[segment_id].text
            for segment_id in segment_ids
            if segment_id in segments_by_id
        )
        missing_numbers, missing_identifiers = audit_claim_text(
            "\n".join([paragraph.title, paragraph.body]),
            evidence_text,
        )
        if missing_numbers:
            unsupported_numbers[paragraph.chapter_index] = missing_numbers
        if missing_identifiers:
            unsupported_identifiers[paragraph.chapter_index] = missing_identifiers

    invalid_moments: list[int] = []
    loaded = load_note_version_evidence(job_dir, review_draft.note_version_id)
    if loaded is not None:
        _, evidence, _ = loaded
        invalid_moments = [
            moment.moment_index
            for moment in evidence.key_moments
            if not moment.reference_valid or str(moment.segment_id or "") not in current_segment_ids
        ]
    return EvidenceAudit(
        transcript_changed=transcript_changed,
        invalid_chapter_references=sorted(set(invalid_chapters)),
        invalid_key_moment_references=invalid_moments,
        unsupported_numeric_claims=unsupported_numbers,
        unsupported_technical_identifiers=unsupported_identifiers,
    )


def audit_claim_text(claim_text: str, evidence_text: str) -> tuple[list[str], list[str]]:
    return (
        _unsupported_claims(
            _extract_numeric_claims(claim_text),
            _extract_numeric_claims(evidence_text),
        ),
        _unsupported_claims(
            _extract_technical_identifiers(claim_text),
            _extract_technical_identifiers(evidence_text),
        ),
    )


def _extract_numeric_claims(text: str) -> list[str]:
    return _unique_matches(NUMERIC_CLAIM_PATTERN, text)


def _extract_technical_identifiers(text: str) -> list[str]:
    return [
        value
        for value in _unique_matches(TECHNICAL_IDENTIFIER_PATTERN, text)
        if not value.isdigit()
    ]


def _unique_matches(pattern: re.Pattern[str], text: str) -> list[str]:
    values: list[str] = []
    seen: set[str] = set()
    for match in pattern.finditer(text):
        value = match.group(0).strip()
        normalized = _normalize_evidence_text(value)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        values.append(value)
    return values


def _unsupported_claims(claims: list[str], evidence_claims: list[str]) -> list[str]:
    normalized_evidence = {
        _normalize_evidence_text(value)
        for value in evidence_claims
    }
    missing = [
        claim
        for claim in claims
        if _normalize_evidence_text(claim) not in normalized_evidence
    ]
    return missing[:8]


def _normalize_evidence_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    normalized = re.sub(r"(?<=\d),(?=\d)", "", normalized)
    return re.sub(r"\s+", "", normalized)


def transcript_fingerprint(transcript: TranscriptPayload) -> str:
    ordered = TranscriptPayload(
        text=transcript.text,
        segments=sorted(
            transcript.segments,
            key=lambda segment: (segment.start, segment.end, segment.text),
        ),
    )
    return hashlib.sha256(ordered.model_dump_json().encode("utf-8")).hexdigest()


def _safe_version_id(version_id: str) -> bool:
    return bool(version_id) and version_id not in {".", ".."} and "/" not in version_id and "\\" not in version_id


def _resolve_job_path(job_dir: Path, relative_path: str) -> Path:
    if not relative_path or Path(relative_path).is_absolute():
        raise ValueError("Evidence path must be job-relative.")
    root = job_dir.resolve()
    candidate = (root / relative_path).resolve()
    if candidate == root or root not in candidate.parents:
        raise ValueError("Evidence path escapes the job directory.")
    return candidate
