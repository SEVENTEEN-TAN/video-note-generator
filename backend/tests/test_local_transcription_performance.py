from __future__ import annotations

from types import SimpleNamespace

from backend.app import transcription
from backend.app.ffmpeg_tools import PreparedAudio
from backend.app.models import JobConfig, NoteLanguage, TranscriptionMode
from backend.app.transcription_checkpoints import ChunkSpec
from backend.app.transcription_plans import HardwareProfile


def _write_model_files(model_dir) -> None:
    model_dir.mkdir(parents=True)
    for name in ("config.json", "model.bin", "tokenizer.json", "vocabulary.txt"):
        (model_dir / name).write_text("x", encoding="utf-8")


def test_simulated_two_hour_local_job_loads_once_and_restart_decodes_nothing(tmp_path, monkeypatch) -> None:
    audio_path = tmp_path / "audio.mp3"
    audio_path.write_bytes(b"public audio")
    _write_model_files(tmp_path / "models" / "small")
    chunk_dir = tmp_path / "work" / "asr" / "chunks"
    chunk_dir.mkdir(parents=True)
    chunks = []
    for index in range(8):
        path = chunk_dir / f"chunk_{index:03d}.flac"
        path.write_bytes(f"chunk-{index}".encode())
        chunks.append(ChunkSpec(index=index, start=index * 900, end=(index + 1) * 900, path=path))

    model_loads = 0
    decoded_paths: list[str] = []

    class CountingWhisperModel:
        def __init__(self, *_args, **_kwargs) -> None:
            nonlocal model_loads
            model_loads += 1

        def transcribe(self, file_path, **_kwargs):
            decoded_paths.append(file_path)
            return [SimpleNamespace(start=0, end=900, text="chunk")], SimpleNamespace(language="en")

    monkeypatch.setattr(transcription, "WhisperModel", CountingWhisperModel)
    monkeypatch.setenv("FASTER_WHISPER_MODEL_DIR", str(tmp_path / "models"))
    config = JobConfig(
        transcription_mode=TranscriptionMode.local_faster_whisper,
        transcription_model="small",
        local_whisper_device="cpu",
        local_whisper_compute_type="int8",
        note_api_key="note-key",
        note_model="gpt-5.5",
        note_language=NoteLanguage.zh,
        original_filename="two-hours.mp4",
    )
    prepared = PreparedAudio(mp3_path=audio_path, chunks=chunks, duration=7200)
    hardware = HardwareProfile(8, 16 * 1024**3, False, None)

    first = transcription.transcribe_with_faster_whisper(
        audio_path,
        config,
        tmp_path,
        prepared_audio=prepared,
        hardware_profile=hardware,
    )
    second = transcription.transcribe_with_faster_whisper(
        audio_path,
        config,
        tmp_path,
        prepared_audio=prepared,
        hardware_profile=hardware,
    )

    assert model_loads == 1
    assert len(decoded_paths) == 8
    assert len(first.segments) == 8
    assert second == first


def test_compatible_internal_model_is_reused_across_jobs_and_can_be_released(tmp_path, monkeypatch) -> None:
    model_root = tmp_path / "models"
    _write_model_files(model_root / "small")
    monkeypatch.setenv("FASTER_WHISPER_MODEL_DIR", str(model_root))
    model_loads = 0

    class CachedWhisperModel:
        def __init__(self, *_args, **_kwargs) -> None:
            nonlocal model_loads
            model_loads += 1

        def transcribe(self, _file_path, **_kwargs):
            return [SimpleNamespace(start=0, end=1, text="ok")], SimpleNamespace(language="en")

    monkeypatch.setattr(transcription, "WhisperModel", CachedWhisperModel)
    transcription.clear_internal_whisper_model_cache()
    config = JobConfig(
        transcription_mode=TranscriptionMode.local_faster_whisper,
        transcription_model="small",
        local_whisper_device="cpu",
        local_whisper_compute_type="int8",
        note_api_key="note-key",
        note_model="gpt-5.5",
        note_language=NoteLanguage.zh,
        original_filename="job.mp4",
    )
    hardware = HardwareProfile(8, 16 * 1024**3, False, None)

    for job_number in (1, 2):
        job_dir = tmp_path / f"job-{job_number}"
        audio_path = job_dir / "audio.mp3"
        chunk_path = job_dir / "work" / "asr" / "chunks" / "chunk_000.flac"
        chunk_path.parent.mkdir(parents=True)
        audio_path.write_bytes(f"audio-{job_number}".encode())
        chunk_path.write_bytes(f"chunk-{job_number}".encode())
        transcription.transcribe_with_faster_whisper(
            audio_path,
            config,
            job_dir,
            prepared_audio=PreparedAudio(
                mp3_path=audio_path,
                chunks=[ChunkSpec(index=0, start=0, end=60, path=chunk_path)],
                duration=60,
            ),
            hardware_profile=hardware,
        )

    assert model_loads == 1
    assert transcription.clear_internal_whisper_model_cache() == 1
