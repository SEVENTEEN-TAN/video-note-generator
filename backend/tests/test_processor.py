from __future__ import annotations

import codecs
import json
from pathlib import Path
from zipfile import ZipFile

import pytest

from backend.app import processor
from backend.app.ffmpeg_tools import FFmpegError, run_ffmpeg
from backend.app.job_store import JobStore
from backend.app.models import (
    Chapter,
    FrameCandidateIndex,
    JobConfig,
    JobStatus,
    KeyMoment,
    NoteDraft,
    NoteLanguage,
    TranscriptionMode,
    TranscriptionWorkProgress,
)


def test_create_zip_excludes_debug_logs_and_model_responses(tmp_path) -> None:
    job_dir = tmp_path / "job"
    (job_dir / "debug").mkdir(parents=True)
    (job_dir / "note.md").write_text("# note", encoding="utf-8")
    (job_dir / "debug.log").write_text("pipeline log", encoding="utf-8")
    (job_dir / "debug" / "note-model-response-attempt-1.txt").write_text("bad json", encoding="utf-8")

    zip_path = processor.create_zip(job_dir)

    with ZipFile(zip_path) as archive:
        names = set(archive.namelist())
    assert "note.md" in names
    assert "debug.log" not in names
    assert "debug/note-model-response-attempt-1.txt" not in names


def test_create_diagnostics_zip_includes_debug_and_recovery_state(tmp_path) -> None:
    job_dir = tmp_path / "job"
    (job_dir / "debug").mkdir(parents=True)
    (job_dir / "review").mkdir()
    checkpoint_dir = job_dir / "work" / "asr" / "transcription_checkpoints"
    checkpoint_dir.mkdir(parents=True)
    (job_dir / "debug.log").write_text("pipeline log", encoding="utf-8")
    (job_dir / "debug" / "note-model-response-attempt-1.txt").write_text("bad json", encoding="utf-8")
    (job_dir / ".job-state.json").write_text('{"status":"failed"}', encoding="utf-8")
    (job_dir / ".operation.json").write_text('{"status":"failed"}', encoding="utf-8")
    (job_dir / "review" / "quality_report.json").write_text('{"status":"needs_attention"}', encoding="utf-8")
    (checkpoint_dir / "manifest.json").write_text('{"chunks":[]}', encoding="utf-8")

    zip_path = processor.create_diagnostics_zip(job_dir)

    with ZipFile(zip_path) as archive:
        names = set(archive.namelist())
    assert names >= {
        "debug.log",
        "debug/note-model-response-attempt-1.txt",
        ".job-state.json",
        ".operation.json",
        "review/quality_report.json",
        "work/asr/transcription_checkpoints/manifest.json",
    }
    assert "note.md" not in names


def test_process_uploaded_subtitle_job_writes_transcript_without_audio_extraction(tmp_path, monkeypatch) -> None:
    job_id = "uploaded-subtitle-job"
    outputs_root = tmp_path / "outputs"
    job_dir = outputs_root / job_id
    source_dir = job_dir / "source_video"
    subtitle_dir = job_dir / "source_subtitles"
    source_dir.mkdir(parents=True)
    subtitle_dir.mkdir(parents=True)
    video_path = source_dir / "input.mp4"
    subtitle_path = subtitle_dir / "input.srt"
    video_path.write_bytes(b"video")
    subtitle_path.write_text(
        "1\n00:00:00,000 --> 00:00:01,500\nhello world\n\n"
        "2\n00:00:02,000 --> 00:00:03,000\nsecond line\n",
        encoding="utf-8",
    )

    def fail_unexpected_call(*_args, **_kwargs) -> None:
        raise AssertionError("uploaded subtitle jobs must not extract audio or transcribe")

    monkeypatch.setattr(processor, "probe_duration", lambda _path: 12.5)
    monkeypatch.setattr(processor, "extract_mp3", fail_unexpected_call)
    monkeypatch.setattr(processor, "transcribe_audio", fail_unexpected_call)

    store = JobStore(outputs_root)
    store.create(job_id)
    config = JobConfig(
        transcription_mode=TranscriptionMode.local_faster_whisper,
        transcription_api_key="",
        transcription_base_url="",
        transcription_model="small",
        note_api_key="secret-note-key",
        note_base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        note_model="qwen-plus",
        note_language=NoteLanguage.zh,
        frame_limit=1,
        original_filename="input.mp4",
    )

    processor.process_uploaded_subtitle_job(
        job_id=job_id,
        job_dir=job_dir,
        video_path=video_path,
        subtitle_path=subtitle_path,
        uploaded_subtitle_filename="input.srt",
        config=config,
        store=store,
    )

    state = store.get(job_id)
    assert state is not None
    assert state.status == JobStatus.awaiting_subtitle_confirmation
    assert not (job_dir / "audio.mp3").exists()
    assert (job_dir / "transcript.json").exists()
    assert (job_dir / "subtitles.srt").exists()
    assert (job_dir / "subtitles.vtt").exists()
    assert (job_dir / "subtitles.md").exists()
    assert (job_dir / "subtitles.pending").exists()
    assert "hello world" in (job_dir / "subtitles.md").read_text(encoding="utf-8-sig")
    metadata = json.loads((job_dir / "metadata.json").read_text(encoding="utf-8"))
    assert metadata["duration_seconds"] == 12.5
    assert metadata["subtitle_source"] == "uploaded"
    assert metadata["uploaded_subtitle_filename"] == "input.srt"


def test_process_transcription_job_stops_after_active_transcription_is_cancelled(tmp_path, monkeypatch) -> None:
    job_id = "cancel-during-transcription"
    outputs_root = tmp_path / "outputs"
    job_dir = outputs_root / job_id
    source_dir = job_dir / "source_video"
    source_dir.mkdir(parents=True)
    video_path = source_dir / "input.mp4"
    video_path.write_bytes(b"video")
    store = JobStore(outputs_root)
    store.create(job_id)

    config = JobConfig(
        transcription_mode=TranscriptionMode.audio_transcriptions,
        transcription_api_key="transcription-key",
        transcription_base_url="https://api.openai.com/v1",
        transcription_model="whisper-1",
        note_api_key="note-key",
        note_base_url="https://api.openai.com/v1",
        note_model="gpt-5.5",
        note_language=NoteLanguage.zh,
        frame_limit=1,
        original_filename="input.mp4",
    )

    monkeypatch.setattr(processor, "probe_duration", lambda _path: 12.5)
    monkeypatch.setattr(processor, "extract_mp3", lambda _video, audio: audio.write_bytes(b"audio"))

    def transcribe_and_cancel(*_args, **_kwargs) -> dict:
        cancellation = store.request_cancel(job_id)
        assert cancellation is not None
        assert cancellation.status == JobStatus.cancelling
        return {"text": "discard me", "segments": [{"start": 0.0, "end": 1.0, "text": "discard me"}]}

    monkeypatch.setattr(processor, "transcribe_audio", transcribe_and_cancel)

    processor.process_transcription_job(
        job_id=job_id,
        job_dir=job_dir,
        video_path=video_path,
        config=config,
        store=store,
    )

    state = store.get(job_id)
    assert state is not None
    assert state.status == JobStatus.cancelled
    assert state.step == "已取消"
    assert (job_dir / "audio.mp3").exists()
    assert not (job_dir / "transcript.json").exists()
    assert not (job_dir / "subtitles.pending").exists()


def test_transcription_callbacks_opt_into_throttled_state_persistence(tmp_path, monkeypatch) -> None:
    job_id = "throttled-callback-contract"
    outputs_root = tmp_path / "outputs"
    job_dir = outputs_root / job_id
    source_dir = job_dir / "source_video"
    source_dir.mkdir(parents=True)
    video_path = source_dir / "input.mp4"
    video_path.write_bytes(b"video")
    update_calls: list[dict] = []

    class RecordingStore(JobStore):
        def update(self, current_job_id: str, **kwargs) -> None:
            update_calls.append(dict(kwargs))
            super().update(current_job_id, **kwargs)

    def fake_transcribe(*_args, **kwargs) -> dict:
        kwargs["progress_callback"]("字幕生成中：00:10 / 10:00", 36)
        work_progress_callback = kwargs.get("work_progress_callback")
        if work_progress_callback is not None:
            work_progress_callback(
                TranscriptionWorkProgress(
                    completed_seconds=10,
                    total_seconds=600,
                    completed_chunks=0,
                    total_chunks=1,
                    current_chunk=0,
                    resumable=True,
                    device="cpu",
                    compute_type="int8",
                )
            )
        return {
            "text": "hello",
            "segments": [{"start": 0, "end": 1, "text": "hello"}],
        }

    monkeypatch.setattr(processor, "probe_duration", lambda _path: 600.0)
    monkeypatch.setattr(processor, "extract_mp3", lambda _video, audio: audio.write_bytes(b"audio"))
    monkeypatch.setattr(processor, "transcribe_audio", fake_transcribe)
    store = RecordingStore(outputs_root)
    store.create(job_id)
    config = JobConfig(
        transcription_mode=TranscriptionMode.audio_transcriptions,
        transcription_api_key="transcription-key",
        transcription_base_url="https://api.openai.com/v1",
        transcription_model="whisper-1",
        note_api_key="note-key",
        note_base_url="https://api.openai.com/v1",
        note_model="gpt-5.5",
        note_language=NoteLanguage.zh,
        frame_limit=1,
        original_filename="input.mp4",
    )

    processor.process_transcription_job(
        job_id=job_id,
        job_dir=job_dir,
        video_path=video_path,
        config=config,
        store=store,
    )

    progress_call = next(
        call for call in update_calls if call.get("step") == "字幕生成中：00:10 / 10:00"
    )
    work_progress_call = next(
        call for call in update_calls if isinstance(call.get("work_progress"), TranscriptionWorkProgress)
    )
    assert progress_call["throttle_persistence"] is True
    assert work_progress_call["throttle_persistence"] is True

    update_calls.clear()
    processor.regenerate_subtitles_job(
        job_id=job_id,
        job_dir=job_dir,
        video_path=video_path,
        config=config,
        store=store,
    )

    regenerated_progress_call = next(
        call for call in update_calls if call.get("step") == "字幕生成中：00:10 / 10:00"
    )
    assert regenerated_progress_call["throttle_persistence"] is True


def test_cancelled_queued_subtitle_regeneration_preserves_reviewed_outputs(tmp_path, monkeypatch) -> None:
    job_id = "cancel-queued-subtitle-regeneration"
    outputs_root = tmp_path / "outputs"
    job_dir = outputs_root / job_id
    source_dir = job_dir / "source_video"
    source_dir.mkdir(parents=True)
    video_path = source_dir / "input.mp4"
    video_path.write_bytes(b"video")
    (job_dir / "note.md").write_text("# reviewed note", encoding="utf-8")
    (job_dir / "download.zip").write_bytes(b"zip")
    (job_dir / "note_versions").mkdir()
    (job_dir / "note_versions" / "keep.txt").write_text("keep", encoding="utf-8")
    (job_dir / "review").mkdir()
    (job_dir / "review" / "keep.txt").write_text("keep", encoding="utf-8")

    store = JobStore(outputs_root)
    store.create(job_id)
    store.request_cancel(job_id)
    config = JobConfig(
        transcription_mode=TranscriptionMode.audio_transcriptions,
        transcription_api_key="transcription-key",
        transcription_base_url="https://api.openai.com/v1",
        transcription_model="whisper-1",
        note_api_key="placeholder",
        note_base_url="https://api.openai.com/v1",
        note_model="placeholder",
        note_language=NoteLanguage.zh,
        frame_limit=1,
        original_filename="input.mp4",
    )
    monkeypatch.setattr(
        processor,
        "extract_mp3",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("cancelled jobs must not start FFmpeg")),
    )

    processor.regenerate_subtitles_job(
        job_id=job_id,
        job_dir=job_dir,
        video_path=video_path,
        config=config,
        store=store,
    )

    state = store.get(job_id)
    assert state is not None
    assert state.status == JobStatus.cancelled
    assert (job_dir / "note.md").read_text(encoding="utf-8") == "# reviewed note"
    assert (job_dir / "download.zip").exists()
    assert (job_dir / "note_versions" / "keep.txt").exists()
    assert (job_dir / "review" / "keep.txt").exists()


def test_process_job_handles_many_transcript_segments(tmp_path, monkeypatch) -> None:
    job_id = "many-segments-job"
    outputs_root = tmp_path / "outputs"
    job_dir = outputs_root / job_id
    source_dir = job_dir / "source_video"
    source_dir.mkdir(parents=True)
    video_path = source_dir / "input.mp4"
    video_path.write_bytes(b"video")

    segments = [
        {"start": index * 2, "end": index * 2 + 1, "text": f"第 {index} 段字幕"}
        for index in range(300)
    ]

    monkeypatch.setattr(processor, "probe_duration", lambda _path: 600.0)
    monkeypatch.setattr(processor, "extract_mp3", lambda _video, audio: audio.write_bytes(b"audio"))
    monkeypatch.setattr(
        processor,
        "transcribe_audio",
        lambda *_args, **_kwargs: {"text": "\n".join(item["text"] for item in segments), "segments": segments},
    )
    monkeypatch.setattr(
        processor,
        "generate_chunked_note_draft_with_chunks",
        lambda *_args, **_kwargs: (NoteDraft(
            title="长视频",
            summary="summary",
            chapters=[],
            key_moments=[],
            key_takeaways=[],
            action_items=[],
            markdown_body="",
        ), [], [])
    )
    monkeypatch.setattr(
        processor,
        "create_note_version_from_draft",
        lambda **kwargs: (kwargs["job_dir"] / "note.md").write_text("# 长视频\n", encoding="utf-8-sig"),
    )
    monkeypatch.setattr(processor, "build_frame_candidate_index", lambda *_args, **_kwargs: FrameCandidateIndex(), raising=False)
    monkeypatch.setattr(
        processor,
        "write_frame_candidate_index",
        lambda job_dir, index: (
            (job_dir / "review").mkdir(parents=True, exist_ok=True),
            (job_dir / "review" / "frame_candidates.json").write_text(index.model_dump_json(), encoding="utf-8"),
        ),
        raising=False,
    )

    store = JobStore(outputs_root)
    store.create(job_id)
    config = JobConfig(
        transcription_api_key="secret-transcription-key",
        transcription_base_url="https://api.openai.com/v1",
        transcription_model="whisper-1",
        note_api_key="secret-note-key",
        note_base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        note_model="qwen-plus",
        note_language=NoteLanguage.zh,
        frame_limit=1,
        original_filename="input.mp4",
    )

    processor.process_transcription_job(
        job_id=job_id,
        job_dir=job_dir,
        video_path=video_path,
        config=config,
        store=store,
    )
    processor.continue_job_to_notes(
        job_id=job_id,
        job_dir=job_dir,
        video_path=video_path,
        config=config,
        store=store,
    )

    state = store.get(job_id)
    assert state is not None
    assert state.status == JobStatus.awaiting_note_review, state.error
    assert (job_dir / "transcript.json").exists()
    assert (job_dir / "subtitles.md").exists()
    assert "第 299 段字幕" in (job_dir / "subtitles.md").read_text(encoding="utf-8-sig")
    assert (job_dir / ".note-review.pending").exists()
    assert (job_dir / "review" / "quality_report.json").exists()
    assert (job_dir / "review" / "frame_candidates.json").exists()
    assert not (job_dir / "download.zip").exists()
    debug_text = (job_dir / "debug.log").read_text(encoding="utf-8")
    for stage in [
        "process_job",
        "probe_duration",
        "extract_mp3",
        "transcribe_audio",
        "write_transcript",
        "write_subtitles",
        "generate_note_draft",
        "create_note_version",
        "await_note_review",
    ]:
        assert stage in debug_text
    assert "secret-transcription-key" not in debug_text
    assert "secret-note-key" not in debug_text


def test_process_job_generates_artifacts_without_persisting_api_key(tmp_path, monkeypatch) -> None:
    job_id = "test-job"
    outputs_root = tmp_path / "outputs"
    job_dir = outputs_root / job_id
    source_dir = job_dir / "source_video"
    source_dir.mkdir(parents=True)
    video_path = source_dir / "input.mp4"

    try:
        run_ffmpeg(
            [
                "-y",
                "-f",
                "lavfi",
                "-i",
                "testsrc=size=320x180:rate=15",
                "-f",
                "lavfi",
                "-i",
                "sine=frequency=1000:sample_rate=44100",
                "-t",
                "1.2",
                "-pix_fmt",
                "yuv420p",
                "-c:v",
                "libx264",
                "-c:a",
                "aac",
                str(video_path),
            ]
        )
    except FFmpegError as exc:
        pytest.skip(f"FFmpeg test video generation is unavailable: {exc}")

    def fake_transcribe_audio(*args, **kwargs) -> dict:
        return {"text": "hello world", "segments": [{"start": 0, "end": 1, "text": "hello world"}]}

    def fake_generate_note_draft(*args, **kwargs):
        return (NoteDraft(
            title="Mock Note",
            summary="Mock summary",
            chapters=[
                Chapter(
                    title="Opening",
                    start_time=0,
                    end_time=1,
                    bullets=["Mock point"],
                    detail="Mock detail",
                )
            ],
            key_moments=[KeyMoment(time=0.5, reason="Opening frame", chapter_index=0)],
        ), [], [])

    monkeypatch.setattr(processor, "transcribe_audio", fake_transcribe_audio)
    monkeypatch.setattr(processor, "generate_chunked_note_draft_with_chunks", fake_generate_note_draft)

    store = JobStore(outputs_root)
    store.create(job_id)
    config = JobConfig(
        transcription_api_key="secret-transcription-key",
        transcription_base_url="https://api.openai.com/v1",
        transcription_model="whisper-1",
        note_api_key="secret-note-key",
        note_base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        note_model="qwen-plus",
        note_language=NoteLanguage.zh,
        frame_limit=1,
        original_filename="input.mp4",
    )

    processor.process_transcription_job(
        job_id=job_id,
        job_dir=job_dir,
        video_path=video_path,
        config=config,
        store=store,
    )
    processor.continue_job_to_notes(
        job_id=job_id,
        job_dir=job_dir,
        video_path=video_path,
        config=config,
        store=store,
    )

    state = store.get(job_id)
    assert state is not None
    assert state.status == JobStatus.awaiting_note_review
    assert (job_dir / "audio.mp3").exists()
    assert video_path.exists()
    assert (job_dir / "subtitles.srt").exists()
    assert (job_dir / "frames" / "frame_001.jpg").exists()
    assert (job_dir / "note.md").exists()
    assert (job_dir / "note_versions" / "note_001" / "note.md").exists()
    assert (job_dir / "note_versions" / "note_001" / "frames" / "frame_001.jpg").exists()
    assert (job_dir / ".note-review.pending").exists()
    assert (job_dir / "review" / "quality_report.json").exists()
    assert (job_dir / "review" / "frame_candidates.json").exists()
    assert not (job_dir / "download.zip").exists()
    metadata = json.loads((job_dir / "metadata.json").read_text(encoding="utf-8"))
    assert "api_key" not in metadata
    metadata_text = (job_dir / "metadata.json").read_text(encoding="utf-8")
    assert "secret-transcription-key" not in metadata_text
    assert "secret-note-key" not in metadata_text
    assert metadata["transcription_model"] == "whisper-1"
    assert metadata["note_model"] == "qwen-plus"
    assert metadata["note_api_protocol"] == "openai_chat_completions"
    assert (job_dir / "note.md").read_bytes().startswith(codecs.BOM_UTF8)
    assert (job_dir / "subtitles.srt").read_bytes().startswith(codecs.BOM_UTF8)
    assert (job_dir / "subtitles.md").read_bytes().startswith(codecs.BOM_UTF8)
    assert "frames/frame_001.jpg" in (job_dir / "note.md").read_text(encoding="utf-8-sig")
    version_index = json.loads((job_dir / "note_versions" / "versions.json").read_text(encoding="utf-8"))
    assert version_index["active_version_id"] == "note_001"
    assert version_index["selected_version_ids"] == ["note_001"]



def test_process_job_persists_draft_title_before_frame_failure(tmp_path, monkeypatch) -> None:
    job_id = "title-before-failure"
    outputs_root = tmp_path / "outputs"
    job_dir = outputs_root / job_id
    source_dir = job_dir / "source_video"
    source_dir.mkdir(parents=True)
    video_path = source_dir / "input.mp4"
    video_path.write_bytes(b"video")

    monkeypatch.setattr(processor, "probe_duration", lambda _path: 12.0)
    monkeypatch.setattr(processor, "extract_mp3", lambda _video, audio: audio.write_bytes(b"audio"))
    monkeypatch.setattr(
        processor,
        "transcribe_audio",
        lambda *_args, **_kwargs: {"text": "hello", "segments": [{"start": 0, "end": 1, "text": "hello"}]},
    )
    monkeypatch.setattr(
        processor,
        "generate_chunked_note_draft_with_chunks",
        lambda *_args, **_kwargs: (NoteDraft(
            title="梯度消失问题讲解",
            summary="summary",
            chapters=[],
            key_moments=[],
            key_takeaways=[],
            action_items=[],
            markdown_body="",
        ), [], [])
    )
    monkeypatch.setattr(
        processor,
        "create_note_version_from_draft",
        lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("frame failed")),
    )

    store = JobStore(outputs_root)
    store.create(job_id)
    config = JobConfig(
        transcription_api_key="secret-transcription-key",
        transcription_base_url="https://api.openai.com/v1",
        transcription_model="whisper-1",
        note_api_key="secret-note-key",
        note_base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        note_model="qwen-plus",
        note_language=NoteLanguage.zh,
        frame_limit=1,
        original_filename="input.mp4",
    )

    processor.process_transcription_job(
        job_id=job_id,
        job_dir=job_dir,
        video_path=video_path,
        config=config,
        store=store,
    )
    processor.continue_job_to_notes(
        job_id=job_id,
        job_dir=job_dir,
        video_path=video_path,
        config=config,
        store=store,
    )

    state = store.get(job_id)
    assert state is not None
    assert state.status == JobStatus.failed
    metadata = json.loads((job_dir / "metadata.json").read_text(encoding="utf-8"))
    assert metadata["title"] == "梯度消失问题讲解"
    assert metadata["original_filename"] == "input.mp4"
    assert "secret-transcription-key" not in (job_dir / "metadata.json").read_text(encoding="utf-8")
    assert store.list_history()[0].title == "梯度消失问题讲解"
    debug_text = (job_dir / "debug.log").read_text(encoding="utf-8")
    assert "create_note_version" in debug_text
    assert "frame failed" in debug_text
    assert "traceback" in debug_text



def test_phase_one_pauses_for_subtitle_confirmation(tmp_path, monkeypatch) -> None:
    job_id = "pause-job"
    outputs_root = tmp_path / "outputs"
    job_dir = outputs_root / job_id
    source_dir = job_dir / "source_video"
    source_dir.mkdir(parents=True)
    video_path = source_dir / "input.mp4"
    video_path.write_bytes(b"video")

    monkeypatch.setattr(processor, "probe_duration", lambda _path: 10.0)
    monkeypatch.setattr(processor, "extract_mp3", lambda _video, audio: audio.write_bytes(b"audio"))
    monkeypatch.setattr(
        processor,
        "transcribe_audio",
        lambda *_args, **_kwargs: {"text": "hello", "segments": [{"start": 0, "end": 1, "text": "hello"}]},
    )

    store = JobStore(outputs_root)
    store.create(job_id)
    config = JobConfig(
        transcription_api_key="secret",
        transcription_base_url="https://api.openai.com/v1",
        transcription_model="whisper-1",
        note_api_key="note-key",
        note_base_url="https://api.openai.com/v1",
        note_model="gpt-5.5",
        note_language=NoteLanguage.zh,
        frame_limit=1,
        original_filename="input.mp4",
    )

    processor.process_transcription_job(
        job_id=job_id,
        job_dir=job_dir,
        video_path=video_path,
        config=config,
        store=store,
    )

    state = store.get(job_id)
    assert state is not None
    assert state.status == JobStatus.awaiting_subtitle_confirmation
    assert state.step == "等待确认字幕"
    assert (job_dir / "subtitles.md").exists()
    assert (job_dir / "subtitles.pending").exists()
    assert not (job_dir / "note.md").exists()
    # phase 2 must not have run yet
    assert not (job_dir / "download.zip").exists()


def test_regenerate_subtitles_removes_old_notes_and_pauses_again(tmp_path, monkeypatch) -> None:
    job_id = "regen-job"
    outputs_root = tmp_path / "outputs"
    job_dir = outputs_root / job_id
    source_dir = job_dir / "source_video"
    source_dir.mkdir(parents=True)
    video_path = source_dir / "input.mp4"
    video_path.write_bytes(b"video")

    monkeypatch.setattr(processor, "probe_duration", lambda _path: 10.0)
    monkeypatch.setattr(processor, "extract_mp3", lambda _video, audio: audio.write_bytes(b"audio"))
    monkeypatch.setattr(
        processor,
        "transcribe_audio",
        lambda *_args, **_kwargs: {"text": "hello", "segments": [{"start": 0, "end": 1, "text": "hello"}]},
    )

    store = JobStore(outputs_root)
    store.create(job_id)
    config = JobConfig(
        transcription_api_key="secret",
        transcription_base_url="https://api.openai.com/v1",
        transcription_model="whisper-1",
        note_api_key="note-key",
        note_base_url="https://api.openai.com/v1",
        note_model="gpt-5.5",
        note_language=NoteLanguage.zh,
        frame_limit=1,
        original_filename="input.mp4",
    )

    # Seed a previously completed note to prove regenerate clears it.
    (job_dir / "note.md").write_text("# old note", encoding="utf-8")
    (job_dir / "download.zip").write_bytes(b"old zip")
    (job_dir / "subtitles.pending").write_text("1", encoding="utf-8")
    (job_dir / "note_chunks").mkdir()
    (job_dir / "note_chunks" / "index.json").write_text("{}", encoding="utf-8")

    processor.regenerate_subtitles_job(
        job_id=job_id,
        job_dir=job_dir,
        video_path=video_path,
        config=config,
        store=store,
    )

    state = store.get(job_id)
    assert state is not None
    assert state.status == JobStatus.awaiting_subtitle_confirmation
    assert state.step == "等待确认字幕"
    assert (job_dir / "subtitles.pending").exists()
    assert not (job_dir / "note.md").exists()
    assert not (job_dir / "download.zip").exists()
    assert not (job_dir / "note_chunks").exists()


def test_regenerate_note_job_rebuilds_review_artifacts_and_waits_for_review(tmp_path, monkeypatch) -> None:
    job_id = "regenerate-review-job"
    outputs_root = tmp_path / "outputs"
    job_dir = outputs_root / job_id
    source_dir = job_dir / "source_video"
    source_dir.mkdir(parents=True)
    (source_dir / "input.mp4").write_bytes(b"video")
    (job_dir / "metadata.json").write_text(
        json.dumps({"original_filename": "input.mp4", "duration_seconds": 10}),
        encoding="utf-8",
    )
    (job_dir / "transcript.json").write_text(
        json.dumps({"text": "hello", "segments": [{"start": 0, "end": 2, "text": "hello"}]}),
        encoding="utf-8",
    )
    (job_dir / "download.zip").write_bytes(b"stale zip")

    def fake_regenerate_note_version(*_args, **_kwargs) -> None:
        (job_dir / "note.md").write_text(
            "# Regenerated\n\n### Opening\n\n`00:00:00 - 00:00:02`\n\nNew note\n",
            encoding="utf-8-sig",
        )
        frames_dir = job_dir / "frames"
        frames_dir.mkdir(exist_ok=True)
        (frames_dir / "frame_001.jpg").write_bytes(b"jpg")

    monkeypatch.setattr(processor, "regenerate_note_version", fake_regenerate_note_version)
    monkeypatch.setattr(
        processor,
        "build_frame_candidate_index",
        lambda *_args, **_kwargs: FrameCandidateIndex(candidates=[]),
    )

    store = JobStore(outputs_root)
    store.create(job_id)
    store.update(job_id, status=JobStatus.succeeded, step="完成", progress=100)
    config = JobConfig(
        transcription_mode=TranscriptionMode.local_faster_whisper,
        transcription_model="reuse-transcript",
        note_api_key="note-key",
        note_base_url="https://api.openai.com/v1",
        note_model="gpt-5.5",
        note_language=NoteLanguage.zh,
        frame_limit=1,
        original_filename="input.mp4",
    )

    processor.regenerate_note_job(
        job_id=job_id,
        job_dir=job_dir,
        config=config,
        store=store,
    )

    state = store.get(job_id)
    assert state is not None
    assert state.status == JobStatus.awaiting_note_review
    assert state.stage.value == "awaiting_note_review"
    assert (job_dir / ".note-review.pending").exists()
    assert (job_dir / "review" / "frame_candidates.json").exists()
    assert (job_dir / "review" / "quality_report.json").exists()
    assert not (job_dir / "download.zip").exists()
    assert "awaiting_review" in (job_dir / "debug.log").read_text(encoding="utf-8")


def test_processor_progress_labels_do_not_contain_placeholder_question_marks() -> None:
    processor_source = Path(processor.__file__).read_text(encoding="utf-8")

    assert '"????' not in processor_source
    assert 'step="??"' not in processor_source
