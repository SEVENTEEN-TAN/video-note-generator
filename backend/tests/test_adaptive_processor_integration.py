from __future__ import annotations

import json
from types import SimpleNamespace

from backend.app import processor
from backend.app.ffmpeg_tools import PreparedAudio
from backend.app.job_store import JobStore
from backend.app.models import JobConfig, JobStatus, NoteLanguage, PerformanceMode, TranscriptionLanguage, TranscriptionMode
from backend.app.transcription import TranscriptionCancelled
from backend.app.transcription_checkpoints import ChunkSpec


def _local_config() -> JobConfig:
    return JobConfig(
        transcription_mode=TranscriptionMode.local_faster_whisper,
        transcription_model="small",
        local_whisper_device="cpu",
        local_whisper_compute_type="int8",
        performance_mode=PerformanceMode.fast,
        transcription_language=TranscriptionLanguage.zh,
        note_api_key="note-key",
        note_model="gpt-5.5",
        note_language=NoteLanguage.zh,
        original_filename="input.mp4",
    )


def test_processor_prepares_direct_local_audio_and_passes_live_cancellation(tmp_path, monkeypatch) -> None:
    job_id = "adaptive-local"
    outputs_root = tmp_path / "outputs"
    job_dir = outputs_root / job_id
    video_path = job_dir / "source_video" / "input.mp4"
    video_path.parent.mkdir(parents=True)
    video_path.write_bytes(b"video")
    store = JobStore(outputs_root)
    store.create(job_id)
    prepared_calls: list[tuple] = []

    monkeypatch.setattr(processor, "probe_duration", lambda _path: 3600.0)
    monkeypatch.setattr(
        processor,
        "resolve_local_transcription_plan",
        lambda *_args, **_kwargs: SimpleNamespace(chunk_seconds=900, device="cpu", compute_type="int8"),
    )

    def fake_prepare(video, mp3, asr_dir, chunk_seconds, *, duration_seconds=None, is_cancelled=None):
        assert is_cancelled is not None and is_cancelled() is False
        prepared_calls.append((video, mp3, asr_dir, chunk_seconds, duration_seconds))
        mp3.write_bytes(b"audio")
        chunk = asr_dir / "chunks" / "chunk_000.flac"
        chunk.parent.mkdir(parents=True)
        chunk.write_bytes(b"flac")
        return PreparedAudio(mp3_path=mp3, chunks=[ChunkSpec(index=0, start=0, end=3600, path=chunk)], duration=3600)

    monkeypatch.setattr(processor, "prepare_audio_artifacts", fake_prepare)

    def fake_transcribe(_audio, _config, _work_dir, **kwargs):
        assert kwargs["prepared_audio"].chunks[0].path.suffix == ".flac"
        assert kwargs["is_cancelled"]() is False
        store.request_cancel(job_id)
        assert kwargs["is_cancelled"]() is True
        raise TranscriptionCancelled("cancelled in test")

    monkeypatch.setattr(processor, "transcribe_audio", fake_transcribe)

    processor.process_transcription_job(
        job_id=job_id,
        job_dir=job_dir,
        video_path=video_path,
        config=_local_config(),
        store=store,
    )

    assert prepared_calls == [
        (video_path, job_dir / "audio.mp3", job_dir / "work" / "asr", 900, 3600.0)
    ]
    assert store.get(job_id).status == JobStatus.cancelled


def test_processor_reuses_existing_local_asr_artifacts_on_resume(tmp_path, monkeypatch) -> None:
    job_id = "resume-local"
    outputs_root = tmp_path / "outputs"
    job_dir = outputs_root / job_id
    video_path = job_dir / "source_video" / "input.mp4"
    video_path.parent.mkdir(parents=True)
    video_path.write_bytes(b"video")
    audio_path = job_dir / "audio.mp3"
    audio_path.write_bytes(b"existing audio")
    chunk = job_dir / "work" / "asr" / "chunks" / "chunk_000.flac"
    chunk.parent.mkdir(parents=True)
    chunk.write_bytes(b"existing flac")
    store = JobStore(outputs_root)
    store.create(job_id)

    monkeypatch.setattr(processor, "probe_duration", lambda _path: 600.0)
    monkeypatch.setattr(
        processor,
        "resolve_local_transcription_plan",
        lambda *_args, **_kwargs: SimpleNamespace(chunk_seconds=0, device="cpu", compute_type="int8"),
    )
    monkeypatch.setattr(
        processor,
        "prepare_audio_artifacts",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("resume must not recreate checkpoint inputs")),
    )
    monkeypatch.setattr(
        processor,
        "load_prepared_audio_artifacts",
        lambda mp3, asr, chunk_seconds, *, duration_seconds: PreparedAudio(
            mp3_path=mp3,
            chunks=[ChunkSpec(index=0, start=0, end=duration_seconds, path=chunk)],
            duration=duration_seconds,
        ),
    )

    def fake_transcribe(_audio, _config, _work_dir, **kwargs):
        assert kwargs["prepared_audio"].chunks[0].path == chunk
        return {"text": "resumed", "segments": [{"start": 0, "end": 1, "text": "resumed"}]}

    monkeypatch.setattr(processor, "transcribe_audio", fake_transcribe)

    processor.process_transcription_job(
        job_id=job_id,
        job_dir=job_dir,
        video_path=video_path,
        config=_local_config(),
        store=store,
    )

    assert store.get(job_id).status == JobStatus.awaiting_subtitle_confirmation
    metadata = json.loads((job_dir / "metadata.json").read_text(encoding="utf-8"))
    assert metadata["performance_mode"] == "fast"
    assert metadata["transcription_language"] == "zh"


def test_processor_fails_before_ffmpeg_when_local_storage_is_insufficient(tmp_path, monkeypatch) -> None:
    job_id = "low-storage"
    outputs_root = tmp_path / "outputs"
    job_dir = outputs_root / job_id
    video_path = job_dir / "source_video" / "input.mp4"
    video_path.parent.mkdir(parents=True)
    video_path.write_bytes(b"video")
    store = JobStore(outputs_root)
    store.create(job_id)

    monkeypatch.setattr(processor, "probe_duration", lambda _path: 7200.0)
    monkeypatch.setattr(
        processor,
        "resolve_local_transcription_plan",
        lambda *_args, **_kwargs: SimpleNamespace(chunk_seconds=900, device="cpu", compute_type="int8"),
    )
    monkeypatch.setattr(processor, "available_storage_bytes", lambda _path: 1)
    monkeypatch.setattr(
        processor,
        "prepare_audio_artifacts",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("FFmpeg must not start without space")),
    )

    processor.process_transcription_job(
        job_id=job_id,
        job_dir=job_dir,
        video_path=video_path,
        config=_local_config(),
        store=store,
    )

    state = store.get(job_id)
    assert state is not None
    assert state.status == JobStatus.failed
    assert "Insufficient disk space" in (state.error or "")
