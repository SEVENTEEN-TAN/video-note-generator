from __future__ import annotations

import codecs
import json
from zipfile import ZipFile

import pytest

from backend.app import processor
from backend.app.ffmpeg_tools import FFmpegError, run_ffmpeg
from backend.app.job_store import JobStore
from backend.app.models import Chapter, JobConfig, JobStatus, KeyMoment, NoteDraft, NoteLanguage


def test_create_zip_includes_debug_logs(tmp_path) -> None:
    job_dir = tmp_path / "job"
    (job_dir / "debug").mkdir(parents=True)
    (job_dir / "note.md").write_text("# note", encoding="utf-8")
    (job_dir / "debug.log").write_text("pipeline log", encoding="utf-8")
    (job_dir / "debug" / "note-model-response-attempt-1.txt").write_text("bad json", encoding="utf-8")

    zip_path = processor.create_zip(job_dir)

    with ZipFile(zip_path) as archive:
        names = set(archive.namelist())
    assert "debug.log" in names
    assert "debug/note-model-response-attempt-1.txt" in names


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
    assert state.status == JobStatus.succeeded, state.error
    assert (job_dir / "transcript.json").exists()
    assert (job_dir / "subtitles.md").exists()
    assert "第 299 段字幕" in (job_dir / "subtitles.md").read_text(encoding="utf-8-sig")
    assert (job_dir / "download.zip").exists()
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
        "create_zip",
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
    assert state.status == JobStatus.succeeded
    assert (job_dir / "audio.mp3").exists()
    assert video_path.exists()
    assert (job_dir / "subtitles.srt").exists()
    assert (job_dir / "frames" / "frame_001.jpg").exists()
    assert (job_dir / "note.md").exists()
    assert (job_dir / "note_versions" / "note_001" / "note.md").exists()
    assert (job_dir / "note_versions" / "note_001" / "frames" / "frame_001.jpg").exists()
    assert (job_dir / "download.zip").exists()
    metadata = json.loads((job_dir / "metadata.json").read_text(encoding="utf-8"))
    assert "api_key" not in metadata
    metadata_text = (job_dir / "metadata.json").read_text(encoding="utf-8")
    assert "secret-transcription-key" not in metadata_text
    assert "secret-note-key" not in metadata_text
    assert metadata["transcription_model"] == "whisper-1"
    assert metadata["note_model"] == "qwen-plus"
    assert (job_dir / "note.md").read_bytes().startswith(codecs.BOM_UTF8)
    assert (job_dir / "subtitles.srt").read_bytes().startswith(codecs.BOM_UTF8)
    assert (job_dir / "subtitles.md").read_bytes().startswith(codecs.BOM_UTF8)
    assert "frames/frame_001.jpg" in (job_dir / "note.md").read_text(encoding="utf-8-sig")
    version_index = json.loads((job_dir / "note_versions" / "versions.json").read_text(encoding="utf-8"))
    assert version_index["active_version_id"] == "note_001"
    assert version_index["selected_version_ids"] == ["note_001"]

    with ZipFile(job_dir / "download.zip") as archive:
        names = set(archive.namelist())
    assert "notes/note_001/note.md" in names
    assert "notes/note_001/frames/frame_001.jpg" in names


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
    assert (job_dir / "subtitles.pending").exists()
    assert not (job_dir / "note.md").exists()
    assert not (job_dir / "download.zip").exists()
