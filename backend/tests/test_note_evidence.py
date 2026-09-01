from __future__ import annotations

import json

from backend.app.llm import transcript_segment_id
from backend.app.models import Chapter, KeyMoment, NoteDraft, TranscriptSegment
from backend.app.note_evidence import (
    _extract_numeric_claims,
    _extract_technical_identifiers,
    audit_active_note_evidence,
    build_note_evidence_index,
)
from backend.app.note_versions import create_note_version_from_draft
from backend.app.models import JobConfig, NoteLanguage, TranscriptionMode


def write_transcript(job_dir, segments: list[TranscriptSegment]) -> None:
    (job_dir / "transcript.json").write_text(
        json.dumps(
            {
                "text": " ".join(segment.text for segment in segments),
                "segments": [segment.model_dump(mode="json") for segment in segments],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def fake_extract_frame(_video, output, timestamp, _duration) -> float:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(b"jpg")
    return timestamp


def note_config() -> JobConfig:
    return JobConfig(
        transcription_mode=TranscriptionMode.local_faster_whisper,
        transcription_model="small",
        note_api_key="secret",
        note_model="gpt-5.5",
        note_language=NoteLanguage.en,
        original_filename="input.mp4",
    )


def test_evidence_index_expands_chapter_segment_range(tmp_path) -> None:
    segments = [
        TranscriptSegment(start=0, end=5, text="Opening"),
        TranscriptSegment(start=5, end=10, text="Middle"),
        TranscriptSegment(start=10, end=15, text="Closing"),
    ]
    write_transcript(tmp_path, segments)
    draft = NoteDraft(
        title="Evidence",
        chapters=[
            Chapter(
                title="Whole",
                start_time=0,
                end_time=15,
                start_segment_id=transcript_segment_id(segments[0]),
                end_segment_id=transcript_segment_id(segments[2]),
            )
        ],
        key_moments=[
            KeyMoment(
                time=7,
                reason="Middle",
                segment_id=transcript_segment_id(segments[1]),
            )
        ],
    )

    evidence = build_note_evidence_index(tmp_path, draft)

    assert evidence.chapters[0].reference_valid is True
    assert evidence.chapters[0].segment_ids == [transcript_segment_id(segment) for segment in segments]
    assert evidence.key_moments[0].reference_valid is True


def test_evidence_audit_flags_claims_missing_from_bound_transcript(tmp_path, monkeypatch) -> None:
    segments = [
        TranscriptSegment(start=0, end=10, text="MCP supports 3 tools in this demonstration."),
    ]
    write_transcript(tmp_path, segments)
    video_path = tmp_path / "source_video" / "input.mp4"
    video_path.parent.mkdir(parents=True)
    video_path.write_bytes(b"video")
    segment_id = transcript_segment_id(segments[0])
    draft = NoteDraft(
        title="Evidence",
        chapters=[
            Chapter(
                title="MCP 2026",
                start_time=0,
                end_time=10,
                start_segment_id=segment_id,
                end_segment_id=segment_id,
                bullets=["The demo uses 9 tools and GPT-9."],
            )
        ],
        key_moments=[KeyMoment(time=5, reason="Demo", segment_id=segment_id)],
    )
    monkeypatch.setattr("backend.app.note_versions.extract_frame", fake_extract_frame)
    create_note_version_from_draft(
        job_dir=tmp_path,
        video_path=video_path,
        draft=draft,
        duration=10,
        config=note_config(),
        version_id="note_001",
    )

    audit = audit_active_note_evidence(tmp_path)

    assert audit is not None
    assert "9" in audit.unsupported_numeric_claims[0]
    assert "2026" in audit.unsupported_numeric_claims[0]
    assert "GPT-9" in audit.unsupported_technical_identifiers[0]
    assert audit.invalid_chapter_references == []


def test_evidence_claim_extractors_keep_versioned_identifiers_and_exact_numbers() -> None:
    assert _extract_technical_identifiers("MCP, GPT-9 and Claude-3.5") == [
        "MCP",
        "GPT-9",
        "Claude-3.5",
    ]
    assert _extract_numeric_claims("19 tools") == ["19"]


def test_evidence_audit_does_not_support_number_by_substring(tmp_path, monkeypatch) -> None:
    segments = [TranscriptSegment(start=0, end=10, text="The demo uses 19 tools.")]
    write_transcript(tmp_path, segments)
    video_path = tmp_path / "source_video" / "input.mp4"
    video_path.parent.mkdir(parents=True)
    video_path.write_bytes(b"video")
    segment_id = transcript_segment_id(segments[0])
    draft = NoteDraft(
        title="Evidence",
        chapters=[
            Chapter(
                title="Demo",
                start_time=0,
                end_time=10,
                start_segment_id=segment_id,
                end_segment_id=segment_id,
                bullets=["The demo uses 9 tools."],
            )
        ],
    )
    monkeypatch.setattr("backend.app.note_versions.extract_frame", fake_extract_frame)
    create_note_version_from_draft(
        job_dir=tmp_path,
        video_path=video_path,
        draft=draft,
        duration=10,
        config=note_config(),
        version_id="note_001",
    )

    audit = audit_active_note_evidence(tmp_path)

    assert audit is not None
    assert audit.unsupported_numeric_claims == {0: ["9"]}


def test_evidence_audit_detects_transcript_change_and_recomputes_references(tmp_path, monkeypatch) -> None:
    segments = [TranscriptSegment(start=0, end=10, text="MCP supports 3 tools.")]
    write_transcript(tmp_path, segments)
    video_path = tmp_path / "source_video" / "input.mp4"
    video_path.parent.mkdir(parents=True)
    video_path.write_bytes(b"video")
    segment_id = transcript_segment_id(segments[0])
    draft = NoteDraft(
        title="Evidence",
        chapters=[
            Chapter(
                title="MCP",
                start_time=0,
                end_time=10,
                start_segment_id=segment_id,
                end_segment_id=segment_id,
            )
        ],
        key_moments=[KeyMoment(time=5, reason="Demo", segment_id=segment_id)],
    )
    monkeypatch.setattr("backend.app.note_versions.extract_frame", fake_extract_frame)
    create_note_version_from_draft(
        job_dir=tmp_path,
        video_path=video_path,
        draft=draft,
        duration=10,
        config=note_config(),
        version_id="note_001",
    )
    write_transcript(
        tmp_path,
        [TranscriptSegment(start=0, end=10, text="MCP supports 4 tools.")],
    )

    audit = audit_active_note_evidence(tmp_path)

    assert audit is not None
    assert audit.transcript_changed is True
    assert audit.invalid_chapter_references == [0]
    assert audit.invalid_key_moment_references == [0]


def test_evidence_loader_ignores_path_outside_job_directory(tmp_path, monkeypatch) -> None:
    segments = [TranscriptSegment(start=0, end=10, text="MCP supports 3 tools.")]
    write_transcript(tmp_path, segments)
    video_path = tmp_path / "source_video" / "input.mp4"
    video_path.parent.mkdir(parents=True)
    video_path.write_bytes(b"video")
    segment_id = transcript_segment_id(segments[0])
    draft = NoteDraft(
        title="Evidence",
        chapters=[
            Chapter(
                title="MCP",
                start_time=0,
                end_time=10,
                start_segment_id=segment_id,
                end_segment_id=segment_id,
            )
        ],
    )
    monkeypatch.setattr("backend.app.note_versions.extract_frame", fake_extract_frame)
    create_note_version_from_draft(
        job_dir=tmp_path,
        video_path=video_path,
        draft=draft,
        duration=10,
        config=note_config(),
        version_id="note_001",
    )
    index_path = tmp_path / "note_versions" / "versions.json"
    payload = json.loads(index_path.read_text(encoding="utf-8"))
    payload["versions"][0]["evidence_path"] = "../outside.json"
    index_path.write_text(json.dumps(payload), encoding="utf-8")

    assert audit_active_note_evidence(tmp_path) is None
