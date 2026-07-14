from __future__ import annotations

from types import SimpleNamespace

from backend.app import transcription
from backend.app.ffmpeg_tools import PreparedAudio
from backend.app.job_store import JobStore
from backend.app.models import (
    JobConfig,
    NoteLanguage,
    TranscriptionMode,
    TranscriptionWorkProgress,
)
from backend.app.transcription_checkpoints import ChunkSpec
from backend.app.transcription_plans import HardwareProfile


def _write_model_files(model_dir) -> None:
    model_dir.mkdir(parents=True)
    for name in ("config.json", "model.bin", "tokenizer.json", "vocabulary.txt"):
        (model_dir / name).write_text("x", encoding="utf-8")


def _local_config() -> JobConfig:
    return JobConfig(
        transcription_mode=TranscriptionMode.local_faster_whisper,
        transcription_model="small",
        local_whisper_device="cpu",
        local_whisper_compute_type="int8",
        note_api_key="note-key",
        note_model="gpt-5.5",
        note_language=NoteLanguage.zh,
        original_filename="input.mp4",
    )


def test_internal_local_transcription_emits_structured_work_progress(tmp_path, monkeypatch) -> None:
    audio_path = tmp_path / "audio.mp3"
    audio_path.write_bytes(b"public audio")
    _write_model_files(tmp_path / "models" / "small")
    chunk_dir = tmp_path / "work" / "asr" / "chunks"
    chunk_dir.mkdir(parents=True)
    first_chunk = chunk_dir / "chunk_000.flac"
    second_chunk = chunk_dir / "chunk_001.flac"
    first_chunk.write_bytes(b"first")
    second_chunk.write_bytes(b"second")

    class FakeWhisperModel:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        def transcribe(self, file_path, **_kwargs):
            end = 600 if file_path.endswith("chunk_000.flac") else 590
            return [SimpleNamespace(start=0, end=end, text="text")], SimpleNamespace(language="en")

    monkeypatch.setattr(transcription, "WhisperModel", FakeWhisperModel)
    monkeypatch.setenv("FASTER_WHISPER_MODEL_DIR", str(tmp_path / "models"))
    prepared = PreparedAudio(
        mp3_path=audio_path,
        chunks=[
            ChunkSpec(index=0, start=0, end=600, path=first_chunk),
            ChunkSpec(index=1, start=600, end=1200, path=second_chunk),
        ],
        duration=1200,
    )
    updates: list[TranscriptionWorkProgress] = []

    transcription.transcribe_with_faster_whisper(
        audio_path,
        _local_config(),
        tmp_path,
        prepared_audio=prepared,
        hardware_profile=HardwareProfile(8, 16 * 1024**3, False, None),
        work_progress_callback=updates.append,
    )

    assert updates
    assert updates[0].total_seconds == 1200
    assert updates[0].total_chunks == 2
    assert updates[0].cache_hits == 0
    assert updates[-1].completed_seconds == 1200
    assert updates[-1].completed_chunks == 2
    assert updates[-1].current_chunk is None
    assert updates[-1].device == "cpu"
    assert updates[-1].compute_type == "int8"
    assert updates[-1].resumable is True


def test_job_store_exposes_and_persists_cancelled_work_progress(tmp_path) -> None:
    job_id = "progress-job"
    job_dir = tmp_path / job_id
    job_dir.mkdir()
    (job_dir / "metadata.json").write_text(
        '{"job_id":"progress-job","title":"Progress","original_filename":"input.mp4","transcription_mode":"local_faster_whisper"}',
        encoding="utf-8",
    )
    store = JobStore(tmp_path)
    store.create(job_id)
    work_progress = TranscriptionWorkProgress(
        completed_seconds=615,
        total_seconds=1200,
        completed_chunks=1,
        total_chunks=2,
        current_chunk=1,
        realtime_factor=0.4,
        eta_seconds=234,
        resumable=True,
        cache_hits=0,
        device="cpu",
        compute_type="int8",
    )

    store.update(job_id, work_progress=work_progress)
    store.request_cancel(job_id)
    store.mark_cancelled(job_id)

    assert store.get(job_id).work_progress == work_progress
    reloaded = JobStore(tmp_path).load_from_disk(job_id)
    assert reloaded is not None
    assert reloaded.work_progress is not None
    assert reloaded.work_progress.completed_seconds == 615
    assert reloaded.work_progress.resumable is True


def test_interrupted_local_job_loaded_from_disk_is_resumable(tmp_path) -> None:
    job_id = "interrupted-local"
    job_dir = tmp_path / job_id
    source_dir = job_dir / "source_video"
    source_dir.mkdir(parents=True)
    (source_dir / "input.mp4").write_bytes(b"video")
    (job_dir / "metadata.json").write_text(
        '{"job_id":"interrupted-local","title":"Interrupted","original_filename":"input.mp4",'
        '"transcription_mode":"local_faster_whisper","duration_seconds":3600}',
        encoding="utf-8",
    )
    (job_dir / "debug.log").write_text(
        '{"stage":"process_transcription_job","message":"started"}\n',
        encoding="utf-8",
    )

    reloaded = JobStore(tmp_path).load_from_disk(job_id)

    assert reloaded is not None
    assert reloaded.status.value == "failed"
    assert reloaded.work_progress is not None
    assert reloaded.work_progress.total_seconds == 3600
    assert reloaded.work_progress.resumable is True
