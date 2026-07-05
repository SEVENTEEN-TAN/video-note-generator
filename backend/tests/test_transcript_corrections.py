from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from backend.app import main
from backend.app.job_store import JobStore
from backend.app.llm import LLMError
from backend.app.main import app
from backend.app.models import Chapter, JobConfig, KeyMoment, NoteDraft, NoteLanguage, NoteStyle, TranscriptSegment, TranscriptionMode
from backend.app.note_versions import regenerate_note_version
from backend.app.transcript_corrections import (
    TRANSCRIPT_CORRECTED,
    TRANSCRIPT_CORRECTED_PENDING,
    TranscriptCorrectionError,
    apply_pending_transcript_correction,
    correct_transcript_segments,
    create_transcript_correction,
)


def make_config() -> JobConfig:
    return JobConfig(
        transcription_mode=TranscriptionMode.local_faster_whisper,
        transcription_model="small",
        note_api_key="note-key",
        note_base_url="https://api.openai.com/v1",
        note_model="gpt-5.5",
        note_language=NoteLanguage.zh,
        note_style=NoteStyle.detailed,
        frame_limit=6,
        original_filename="demo.mp4",
    )


def write_transcript(job_dir, text: str = "低贩 工作流") -> None:
    (job_dir / "transcript.json").write_text(
        json.dumps(
            {
                "text": text,
                "segments": [{"start": 0.0, "end": 2.0, "text": text}],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def test_create_transcript_correction_writes_pending_file(tmp_path, monkeypatch) -> None:
    write_transcript(tmp_path)

    def fake_correct(_config, _segments, _instructions=""):
        return [{"index": 0, "text": "Dify 工作流"}]

    monkeypatch.setattr("backend.app.transcript_corrections.correct_transcript_segments", fake_correct)

    result = create_transcript_correction(tmp_path, make_config())

    assert result.changed_count == 0
    assert result.segments[0].original_text == "Dify 工作流"
    assert result.segments[0].corrected_text == "Dify 工作流"
    assert (tmp_path / TRANSCRIPT_CORRECTED_PENDING).exists()


def test_correct_transcript_segments_accepts_provider_wrapped_segments(monkeypatch) -> None:
    def fake_call_json_model(_config, _messages, max_tokens=3000):
        return {"data": {"segments": [{"index": 0, "text": "Dify workflow"}]}}

    monkeypatch.setattr("backend.app.transcript_corrections.call_json_model", fake_call_json_model)

    corrections = correct_transcript_segments(
        make_config(),
        [TranscriptSegment(start=0.0, end=2.0, text="Dify work flow")],
    )

    assert corrections == [{"index": 0, "text": "Dify workflow"}]


def test_correct_transcript_segments_accepts_provider_wrapped_segments_json_string(monkeypatch) -> None:
    def fake_call_json_model(_config, _messages, max_tokens=3000):
        return {"output": '{"segments":[{"index":0,"text":"Dify workflow"}]}'}

    monkeypatch.setattr("backend.app.transcript_corrections.call_json_model", fake_call_json_model)

    corrections = correct_transcript_segments(
        make_config(),
        [TranscriptSegment(start=0, end=1, text="Dify 工作流")],
    )

    assert corrections == [{"index": 0, "text": "Dify workflow"}]


def test_correct_transcript_segments_accepts_corrections_list(monkeypatch) -> None:
    def fake_call_json_model(_config, _messages, max_tokens=3000):
        return {"corrections": [{"index": 0, "text": "Dify workflow"}]}

    monkeypatch.setattr("backend.app.transcript_corrections.call_json_model", fake_call_json_model)

    corrections = correct_transcript_segments(
        make_config(),
        [TranscriptSegment(start=0, end=1, text="Dify 工作流")],
    )

    assert corrections == [{"index": 0, "text": "Dify workflow"}]


def test_create_transcript_correction_rejects_missing_segment(tmp_path, monkeypatch) -> None:
    write_transcript(tmp_path)

    def fake_correct(_config, _segments, _instructions=""):
        return []

    monkeypatch.setattr("backend.app.transcript_corrections.correct_transcript_segments", fake_correct)

    with pytest.raises(TranscriptCorrectionError):
        create_transcript_correction(tmp_path, make_config())

    assert not (tmp_path / TRANSCRIPT_CORRECTED_PENDING).exists()


def test_create_transcript_correction_rejects_duplicate_segment_indexes(tmp_path, monkeypatch) -> None:
    write_transcript(tmp_path)

    def fake_correct(_config, _segments, _instructions=""):
        return [{"index": 0, "text": "Dify 工作流"}, {"index": 0, "text": "Dify 工作流"}]

    monkeypatch.setattr("backend.app.transcript_corrections.correct_transcript_segments", fake_correct)

    with pytest.raises(TranscriptCorrectionError):
        create_transcript_correction(tmp_path, make_config())


def test_create_transcript_correction_rejects_expanded_or_multiline_text(tmp_path, monkeypatch) -> None:
    write_transcript(tmp_path, text="hello")

    def fake_correct(_config, _segments, _instructions=""):
        return [{"index": 0, "text": "# Summary\n" + ("expanded " * 40)}]

    monkeypatch.setattr("backend.app.transcript_corrections.correct_transcript_segments", fake_correct)

    with pytest.raises(TranscriptCorrectionError):
        create_transcript_correction(tmp_path, make_config())

    assert not (tmp_path / TRANSCRIPT_CORRECTED_PENDING).exists()


def test_apply_pending_transcript_correction_writes_corrected_transcript_and_subtitles(tmp_path) -> None:
    write_transcript(tmp_path, text="hello")
    (tmp_path / TRANSCRIPT_CORRECTED_PENDING).write_text(
        json.dumps(
            {
                "text": "hello world",
                "segments": [{"start": 0.0, "end": 2.0, "text": "hello world"}],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    result = apply_pending_transcript_correction(tmp_path)

    assert result.changed_count == 1
    assert (tmp_path / TRANSCRIPT_CORRECTED).exists()
    assert "hello world" in (tmp_path / "subtitles.md").read_text(encoding="utf-8-sig")
    assert (tmp_path / "transcript.json").exists()


def test_transcript_correction_endpoint_returns_preview(tmp_path, monkeypatch) -> None:
    job_id = "job-1"
    job_dir = tmp_path / job_id
    job_dir.mkdir()
    write_transcript(job_dir, text="hello")
    monkeypatch.setattr(main, "OUTPUTS_ROOT", tmp_path)
    monkeypatch.setattr(main, "store", JobStore(tmp_path))
    monkeypatch.setattr(
        "backend.app.transcript_corrections.correct_transcript_segments",
        lambda _config, _segments, _instructions="": [{"index": 0, "text": "hello world"}],
    )

    response = TestClient(app, raise_server_exceptions=False).post(
        f"/api/jobs/{job_id}/transcript-corrections",
        json={"note_api_key": "key", "note_base_url": "https://api.openai.com/v1", "note_model": "gpt-5.5"},
    )

    assert response.status_code == 200
    assert response.json()["changed_count"] == 1


def test_transcript_correction_endpoint_returns_controlled_error_when_model_fails(tmp_path, monkeypatch) -> None:
    job_id = "job-1"
    job_dir = tmp_path / job_id
    job_dir.mkdir()
    write_transcript(job_dir, text="hello")
    monkeypatch.setattr(main, "OUTPUTS_ROOT", tmp_path)
    monkeypatch.setattr(main, "store", JobStore(tmp_path))

    def fail_model(_config, _segments, _instructions=""):
        raise LLMError("model returned invalid json")

    monkeypatch.setattr("backend.app.transcript_corrections.correct_transcript_segments", fail_model)

    response = TestClient(app, raise_server_exceptions=False).post(
        f"/api/jobs/{job_id}/transcript-corrections",
        json={"note_api_key": "key", "note_base_url": "https://api.openai.com/v1", "note_model": "gpt-5.5"},
    )

    assert response.status_code == 400
    assert "model returned invalid json" in response.json()["detail"]
    assert not (job_dir / TRANSCRIPT_CORRECTED_PENDING).exists()


def test_transcript_correction_apply_endpoint_applies_pending_and_queues_regeneration(tmp_path, monkeypatch) -> None:
    job_id = "job-1"
    job_dir = tmp_path / job_id
    job_dir.mkdir()
    source_video = job_dir / "source_video" / "input.mp4"
    source_video.parent.mkdir()
    source_video.write_bytes(b"video")
    write_transcript(job_dir, text="hello")
    (job_dir / TRANSCRIPT_CORRECTED_PENDING).write_text(
        json.dumps({"text": "hello world", "segments": [{"start": 0.0, "end": 2.0, "text": "hello world"}]}),
        encoding="utf-8",
    )
    monkeypatch.setattr(main, "OUTPUTS_ROOT", tmp_path)
    monkeypatch.setattr(main, "store", JobStore(tmp_path))
    monkeypatch.setattr(main, "regenerate_note_job", lambda **_kwargs: None)

    response = TestClient(app, raise_server_exceptions=False).post(
        f"/api/jobs/{job_id}/transcript-corrections/apply",
        json={
            "note_language": "zh",
            "note_style": "detailed",
            "extras": "",
            "note_api_key": "key",
            "note_base_url": "https://api.openai.com/v1",
            "note_model": "gpt-5.5",
            "frame_limit": 6,
        },
    )

    assert response.status_code == 200
    assert (job_dir / TRANSCRIPT_CORRECTED).exists()
    assert "hello world" in (job_dir / "subtitles.md").read_text(encoding="utf-8-sig")


def test_regenerate_note_version_prefers_corrected_transcript(tmp_path, monkeypatch) -> None:
    job_dir = tmp_path
    video_path = job_dir / "source_video" / "input.mp4"
    video_path.parent.mkdir(parents=True)
    video_path.write_bytes(b"video")
    write_transcript(job_dir, text="original text")
    (job_dir / TRANSCRIPT_CORRECTED).write_text(
        json.dumps({"text": "corrected text", "segments": [{"start": 0.0, "end": 2.0, "text": "corrected text"}]}),
        encoding="utf-8",
    )
    (job_dir / "metadata.json").write_text(
        json.dumps({"original_filename": "input.mp4", "duration_seconds": 10}),
        encoding="utf-8",
    )

    def fake_generate_note_draft(_config, duration, segments) -> NoteDraft:
        assert duration == 10
        assert segments[0].text == "corrected text"
        return NoteDraft(
            title="Corrected",
            summary="summary",
            chapters=[Chapter(title="Opening", start_time=0, end_time=2)],
            key_moments=[KeyMoment(time=1, reason="opening", chapter_index=0)],
        )

    def fake_extract_frame(_source_video, output_path, timestamp, _duration) -> float:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"jpg")
        return timestamp

    monkeypatch.setattr("backend.app.note_versions.generate_note_draft", fake_generate_note_draft)
    monkeypatch.setattr("backend.app.note_versions.extract_frame", fake_extract_frame)

    version = regenerate_note_version(job_dir, make_config())

    assert version.id == "note_001"
    assert (job_dir / "note.md").read_text(encoding="utf-8-sig").startswith("# Corrected")
