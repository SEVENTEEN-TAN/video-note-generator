import subprocess
from types import SimpleNamespace
from pathlib import Path

import pytest
from pydantic import ValidationError

from backend.app import local_whisper_worker, transcription
from backend.app.ffmpeg_tools import PreparedAudio
from backend.app.models import JobConfig, NoteLanguage, TranscriptPayload, TranscriptSegment, TranscriptionLanguage, TranscriptionMode
from backend.app.transcription_checkpoints import ChunkSpec
from backend.app.transcription import (
    faster_whisper_segments_to_payload,
    parse_chat_audio_payload,
    parse_transcription_payload,
    resolve_local_faster_whisper_model,
)
from backend.app.transcription_plans import HardwareProfile


def write_model_files(model_dir) -> None:
    model_dir.mkdir(parents=True)
    for name in ("config.json", "model.bin", "tokenizer.json", "vocabulary.txt"):
        (model_dir / name).write_text("x", encoding="utf-8")


def test_parse_chat_audio_payload_offsets_relative_times() -> None:
    payload = '{"segments":[{"start":1,"end":2,"text":"hello"}]}'
    parsed = parse_chat_audio_payload(payload, offset_seconds=120)
    assert parsed.segments[0].start == 121
    assert parsed.segments[0].end == 122
    assert parsed.segments[0].text == "hello"


def test_parse_chat_audio_payload_keeps_absolute_times() -> None:
    payload = '{"segments":[{"start":121,"end":122,"text":"hello"}]}'
    parsed = parse_chat_audio_payload(payload, offset_seconds=120)
    assert parsed.segments[0].start == 121
    assert parsed.segments[0].end == 122


def test_parse_chat_audio_payload_skips_non_transcript_json_candidates() -> None:
    payload = 'Example: {"format":"demo"}\nActual:\n{"segments":[{"start":1,"end":2,"text":"hello"}]}'
    parsed = parse_chat_audio_payload(payload, offset_seconds=120)

    assert parsed.segments[0].start == 121
    assert parsed.segments[0].end == 122
    assert parsed.segments[0].text == "hello"


def test_parse_chat_audio_payload_accepts_provider_wrapped_segments_json_string() -> None:
    payload = '{"output":"{\\"segments\\":[{\\"start\\":1,\\"end\\":2,\\"text\\":\\"hello\\"}]}"}'
    parsed = parse_chat_audio_payload(payload, offset_seconds=120)

    assert parsed.segments[0].start == 121
    assert parsed.segments[0].end == 122
    assert parsed.segments[0].text == "hello"


def test_parse_chat_audio_payload_uses_text_fallback_when_segments_missing() -> None:
    parsed = parse_chat_audio_payload('{"text":"hello from audio"}', offset_seconds=120)

    assert parsed.text == "hello from audio"
    assert len(parsed.segments) == 1
    assert parsed.segments[0].start == 120
    assert parsed.segments[0].end == 120
    assert parsed.segments[0].text == "hello from audio"


def test_faster_whisper_segments_to_payload_maps_segments() -> None:
    parsed = faster_whisper_segments_to_payload(
        [
            SimpleNamespace(start=0, end=1.2, text=" hello "),
            SimpleNamespace(start=1.2, end=2.4, text="world"),
        ]
    )

    assert parsed.text == "hello world"
    assert parsed.segments[0].start == 0
    assert parsed.segments[0].end == 1.2
    assert parsed.segments[0].text == "hello"


def test_faster_whisper_segments_to_payload_skips_blank_text() -> None:
    parsed = faster_whisper_segments_to_payload(
        [
            SimpleNamespace(start=0, end=1, text=" "),
            SimpleNamespace(start=1, end=2, text="kept"),
        ]
    )

    assert len(parsed.segments) == 1
    assert parsed.segments[0].text == "kept"


class CountingSegmentIterator:
    def __init__(self, items) -> None:
        self.items = iter(items)
        self.next_calls = 0

    def __iter__(self):
        return self

    def __next__(self):
        self.next_calls += 1
        return next(self.items)


def test_faster_whisper_cancellation_is_checked_before_first_next() -> None:
    segments = CountingSegmentIterator([SimpleNamespace(start=0, end=1, text="unused")])

    with pytest.raises(transcription.TranscriptionCancelled):
        faster_whisper_segments_to_payload(segments, is_cancelled=lambda: True)

    assert segments.next_calls == 0


def test_faster_whisper_cancellation_after_one_segment_avoids_next_decode() -> None:
    segments = CountingSegmentIterator(
        [
            SimpleNamespace(start=0, end=1, text="first"),
            SimpleNamespace(start=1, end=2, text="second"),
        ]
    )
    checks = iter([False, True])

    with pytest.raises(transcription.TranscriptionCancelled):
        faster_whisper_segments_to_payload(segments, is_cancelled=lambda: next(checks))

    assert segments.next_calls == 1


def test_parse_transcription_payload_accepts_provider_wrapped_segments_json_string() -> None:
    parsed = parse_transcription_payload(
        {"output": '{"text":"hello","segments":[{"start":0,"end":1,"text":"hello"}]}'}
    )

    assert parsed.text == "hello"
    assert parsed.segments[0].start == 0
    assert parsed.segments[0].end == 1
    assert parsed.segments[0].text == "hello"


def test_local_faster_whisper_allows_empty_transcription_api_key() -> None:
    config = JobConfig(
        transcription_mode=TranscriptionMode.local_faster_whisper,
        transcription_api_key="",
        transcription_base_url="",
        transcription_model="small",
        note_api_key="note-key",
        note_base_url="https://api.openai.com/v1",
        note_model="gpt-5.5",
        note_language=NoteLanguage.zh,
        original_filename="input.mp4",
    )

    assert config.transcription_api_key == ""


def test_remote_transcription_requires_api_key() -> None:
    with pytest.raises(ValidationError):
        JobConfig(
            transcription_mode=TranscriptionMode.audio_transcriptions,
            transcription_api_key="",
            transcription_base_url="https://api.openai.com/v1",
            transcription_model="whisper-1",
            note_api_key="note-key",
            note_base_url="https://api.openai.com/v1",
            note_model="gpt-5.5",
            note_language=NoteLanguage.zh,
            original_filename="input.mp4",
        )


def test_transcribe_audio_dispatches_local_faster_whisper(tmp_path, monkeypatch) -> None:
    audio_path = tmp_path / "audio.mp3"
    audio_path.write_bytes(b"fake audio")
    write_model_files(tmp_path / "models" / "small")

    class FakeWhisperModel:
        def __init__(self, model_name, **kwargs):
            assert model_name == str(tmp_path / "models" / "small")
            assert kwargs["download_root"] == str(tmp_path / "models")
            assert kwargs["device"] == "cuda"
            assert kwargs["compute_type"] == "float16"

        def transcribe(self, file_path, **_kwargs):
            assert file_path == str(audio_path)
            return [SimpleNamespace(start=0, end=1, text="local text")], SimpleNamespace(language="zh")

    monkeypatch.setattr(transcription, "WhisperModel", FakeWhisperModel)
    monkeypatch.setenv("FASTER_WHISPER_MODEL_DIR", str(tmp_path / "models"))

    config = JobConfig(
        transcription_mode=TranscriptionMode.local_faster_whisper,
        transcription_api_key="",
        transcription_base_url="",
        transcription_model="small",
        local_whisper_device="cuda",
        local_whisper_compute_type="float16",
        note_api_key="note-key",
        note_base_url="https://api.openai.com/v1",
        note_model="gpt-5.5",
        note_language=NoteLanguage.zh,
        original_filename="input.mp4",
    )

    parsed = transcription.transcribe_audio(audio_path, config, tmp_path)

    assert parsed["text"] == "local text"
    assert parsed["segments"] == [{"start": 0.0, "end": 1.0, "text": "local text"}]


def test_internal_cuda_faster_whisper_configures_cuda_dll_paths_before_model_load(tmp_path, monkeypatch) -> None:
    audio_path = tmp_path / "audio.mp3"
    audio_path.write_bytes(b"fake audio")
    write_model_files(tmp_path / "models" / "small")
    events: list[str] = []

    def fake_configure_cuda_dll_paths() -> None:
        events.append("dll")

    class FakeWhisperModel:
        def __init__(self, *_args, **_kwargs):
            assert events == ["dll"]
            events.append("model")

        def transcribe(self, _file_path, **_kwargs):
            return [SimpleNamespace(start=0, end=1, text="cuda text")], SimpleNamespace(language="zh")

    monkeypatch.setattr(local_whisper_worker, "configure_cuda_dll_paths", fake_configure_cuda_dll_paths)
    monkeypatch.setattr(transcription, "WhisperModel", FakeWhisperModel)
    monkeypatch.setenv("FASTER_WHISPER_MODEL_DIR", str(tmp_path / "models"))

    config = JobConfig(
        transcription_mode=TranscriptionMode.local_faster_whisper,
        transcription_api_key="",
        transcription_base_url="",
        transcription_model="small",
        local_whisper_device="cuda",
        local_whisper_compute_type="float16",
        note_api_key="note-key",
        note_base_url="https://api.openai.com/v1",
        note_model="gpt-5.5",
        note_language=NoteLanguage.zh,
        original_filename="input.mp4",
    )

    parsed = transcription.transcribe_audio(audio_path, config, tmp_path)

    assert parsed["text"] == "cuda text"
    assert events == ["dll", "model"]


def test_transcribe_audio_reports_progress_for_internal_local_faster_whisper(tmp_path, monkeypatch) -> None:
    audio_path = tmp_path / "audio.mp3"
    audio_path.write_bytes(b"fake audio")
    write_model_files(tmp_path / "models" / "small")

    class FakeWhisperModel:
        def __init__(self, *_args, **_kwargs):
            pass

        def transcribe(self, _file_path, **_kwargs):
            return [SimpleNamespace(start=0, end=1, text="local text")], SimpleNamespace(language="zh")

    monkeypatch.setattr(transcription, "WhisperModel", FakeWhisperModel)
    monkeypatch.setenv("FASTER_WHISPER_MODEL_DIR", str(tmp_path / "models"))

    updates: list[tuple[str, int]] = []
    config = JobConfig(
        transcription_mode=TranscriptionMode.local_faster_whisper,
        transcription_api_key="",
        transcription_base_url="",
        transcription_model="small",
        local_whisper_device="cuda",
        local_whisper_compute_type="float16",
        note_api_key="note-key",
        note_base_url="https://api.openai.com/v1",
        note_model="gpt-5.5",
        note_language=NoteLanguage.zh,
        original_filename="input.mp4",
    )

    transcription.transcribe_audio(
        audio_path,
        config,
        tmp_path,
        progress_callback=lambda step, progress: updates.append((step, progress)),
    )

    assert updates == [
        ("字幕生成中：加载 Faster Whisper 模型 small", 36),
        ("字幕生成中：本地 Faster Whisper 转写中", 38),
    ]


def test_long_internal_local_transcription_loads_model_once(tmp_path, monkeypatch) -> None:
    audio_path = tmp_path / "audio.mp3"
    audio_path.write_bytes(b"public audio")
    write_model_files(tmp_path / "models" / "small")
    chunk_dir = tmp_path / "work" / "asr" / "chunks"
    chunk_dir.mkdir(parents=True)
    chunk_zero = chunk_dir / "chunk_000.flac"
    chunk_one = chunk_dir / "chunk_001.flac"
    chunk_zero.write_bytes(b"zero")
    chunk_one.write_bytes(b"one")
    load_count = 0

    class FakeWhisperModel:
        def __init__(self, *_args, **_kwargs):
            nonlocal load_count
            load_count += 1

        def transcribe(self, file_path, **_kwargs):
            text = "first" if file_path.endswith("chunk_000.flac") else "second"
            return [SimpleNamespace(start=0, end=10, text=text)], SimpleNamespace(language="en")

    monkeypatch.setattr(transcription, "WhisperModel", FakeWhisperModel)
    monkeypatch.setenv("FASTER_WHISPER_MODEL_DIR", str(tmp_path / "models"))
    config = JobConfig(
        transcription_mode=TranscriptionMode.local_faster_whisper,
        transcription_model="small",
        local_whisper_device="cpu",
        local_whisper_compute_type="int8",
        note_api_key="note-key",
        note_model="gpt-5.5",
        note_language=NoteLanguage.zh,
        original_filename="input.mp4",
    )
    prepared = PreparedAudio(
        mp3_path=audio_path,
        chunks=[
            ChunkSpec(index=0, start=0, end=600, path=chunk_zero),
            ChunkSpec(index=1, start=600, end=1200, path=chunk_one),
        ],
        duration=1200,
    )

    result = transcription.transcribe_with_faster_whisper(
        audio_path,
        config,
        tmp_path,
        prepared_audio=prepared,
        hardware_profile=HardwareProfile(8, 16 * 1024**3, False, None),
    )

    assert load_count == 1
    assert result.text == "first second"
    assert [segment.start for segment in result.segments] == [0.0, 600.0]


def test_completed_local_checkpoints_skip_model_loading(tmp_path, monkeypatch) -> None:
    audio_path = tmp_path / "audio.mp3"
    audio_path.write_bytes(b"public audio")
    write_model_files(tmp_path / "models" / "small")
    chunk_path = tmp_path / "work" / "asr" / "chunks" / "chunk_000.flac"
    chunk_path.parent.mkdir(parents=True)
    chunk_path.write_bytes(b"chunk")

    class FirstModel:
        def __init__(self, *_args, **_kwargs):
            pass

        def transcribe(self, _file_path, **_kwargs):
            return [SimpleNamespace(start=0, end=5, text="cached")], SimpleNamespace(language="en")

    monkeypatch.setattr(transcription, "WhisperModel", FirstModel)
    monkeypatch.setenv("FASTER_WHISPER_MODEL_DIR", str(tmp_path / "models"))
    config = JobConfig(
        transcription_mode=TranscriptionMode.local_faster_whisper,
        transcription_model="small",
        local_whisper_device="cpu",
        local_whisper_compute_type="int8",
        note_api_key="note-key",
        note_model="gpt-5.5",
        note_language=NoteLanguage.zh,
        original_filename="input.mp4",
    )
    prepared = PreparedAudio(
        mp3_path=audio_path,
        chunks=[ChunkSpec(index=0, start=0, end=600, path=chunk_path)],
        duration=600,
    )
    hardware = HardwareProfile(8, 16 * 1024**3, False, None)
    transcription.transcribe_with_faster_whisper(
        audio_path,
        config,
        tmp_path,
        prepared_audio=prepared,
        hardware_profile=hardware,
    )

    class MustNotLoadModel:
        def __init__(self, *_args, **_kwargs):
            raise AssertionError("model should not load for completed checkpoints")

    monkeypatch.setattr(transcription, "WhisperModel", MustNotLoadModel)

    result = transcription.transcribe_with_faster_whisper(
        audio_path,
        config,
        tmp_path,
        prepared_audio=prepared,
        hardware_profile=hardware,
    )

    assert result.text == "cached"


def test_internal_local_progress_uses_segment_end_times(tmp_path, monkeypatch) -> None:
    audio_path = tmp_path / "audio.mp3"
    audio_path.write_bytes(b"public audio")
    write_model_files(tmp_path / "models" / "small")

    class FakeWhisperModel:
        def __init__(self, *_args, **_kwargs):
            pass

        def transcribe(self, _file_path, **_kwargs):
            return iter(
                [
                    SimpleNamespace(start=0, end=100, text="first"),
                    SimpleNamespace(start=100, end=500, text="second"),
                ]
            ), SimpleNamespace(language="en")

    monkeypatch.setattr(transcription, "WhisperModel", FakeWhisperModel)
    monkeypatch.setenv("FASTER_WHISPER_MODEL_DIR", str(tmp_path / "models"))
    monkeypatch.setattr(transcription, "probe_duration", lambda _path: 600.0)
    updates: list[tuple[str, int]] = []
    config = JobConfig(
        transcription_mode=TranscriptionMode.local_faster_whisper,
        transcription_model="small",
        local_whisper_device="cpu",
        local_whisper_compute_type="int8",
        note_api_key="note-key",
        note_model="gpt-5.5",
        note_language=NoteLanguage.zh,
        original_filename="input.mp4",
    )

    transcription.transcribe_with_faster_whisper(
        audio_path,
        config,
        tmp_path,
        progress_callback=lambda step, progress: updates.append((step, progress)),
        hardware_profile=HardwareProfile(8, 16 * 1024**3, False, None),
    )

    segment_progress = [progress for step, progress in updates if "已处理" in step]
    assert segment_progress == sorted(segment_progress)
    assert len(segment_progress) == 2
    assert segment_progress[-1] > segment_progress[0] > 38


def test_internal_local_cancellation_stops_before_model_loading(tmp_path, monkeypatch) -> None:
    audio_path = tmp_path / "audio.mp3"
    audio_path.write_bytes(b"public audio")
    write_model_files(tmp_path / "models" / "small")

    class MustNotLoadModel:
        def __init__(self, *_args, **_kwargs):
            raise AssertionError("cancelled transcription must not load a model")

    monkeypatch.setattr(transcription, "WhisperModel", MustNotLoadModel)
    monkeypatch.setenv("FASTER_WHISPER_MODEL_DIR", str(tmp_path / "models"))
    monkeypatch.setattr(transcription, "probe_duration", lambda _path: 60.0)
    config = JobConfig(
        transcription_mode=TranscriptionMode.local_faster_whisper,
        transcription_model="small",
        local_whisper_device="cpu",
        local_whisper_compute_type="int8",
        note_api_key="note-key",
        note_model="gpt-5.5",
        note_language=NoteLanguage.zh,
        original_filename="input.mp4",
    )

    with pytest.raises(transcription.TranscriptionCancelled):
        transcription.transcribe_with_faster_whisper(
            audio_path,
            config,
            tmp_path,
            is_cancelled=lambda: True,
            hardware_profile=HardwareProfile(8, 16 * 1024**3, False, None),
        )


def test_internal_local_runtime_preserves_environment_overrides(tmp_path, monkeypatch) -> None:
    audio_path = tmp_path / "audio.mp3"
    audio_path.write_bytes(b"public audio")
    write_model_files(tmp_path / "models" / "small")
    captured: dict[str, object] = {}

    class FakeWhisperModel:
        def __init__(self, *_args, **kwargs):
            captured.update(kwargs)

        def transcribe(self, _file_path, **_kwargs):
            return [SimpleNamespace(start=0, end=1, text="environment")], SimpleNamespace(language="en")

    monkeypatch.setattr(transcription, "WhisperModel", FakeWhisperModel)
    monkeypatch.setenv("FASTER_WHISPER_MODEL_DIR", str(tmp_path / "models"))
    monkeypatch.setenv("FASTER_WHISPER_DEVICE", "cuda")
    monkeypatch.setenv("FASTER_WHISPER_COMPUTE_TYPE", "float16")
    monkeypatch.setattr(transcription, "probe_duration", lambda _path: 60.0)
    config = JobConfig(
        transcription_mode=TranscriptionMode.local_faster_whisper,
        transcription_model="small",
        local_whisper_device="",
        local_whisper_compute_type="",
        note_api_key="note-key",
        note_model="gpt-5.5",
        note_language=NoteLanguage.zh,
        original_filename="input.mp4",
    )

    transcription.transcribe_with_faster_whisper(
        audio_path,
        config,
        tmp_path,
        hardware_profile=HardwareProfile(8, 16 * 1024**3, False, None),
    )

    assert captured["device"] == "cuda"
    assert captured["compute_type"] == "float16"


def test_cancelled_incomplete_chunk_is_not_checkpointed(tmp_path, monkeypatch) -> None:
    audio_path = tmp_path / "audio.mp3"
    audio_path.write_bytes(b"public audio")
    write_model_files(tmp_path / "models" / "small")
    chunk_path = tmp_path / "work" / "asr" / "chunks" / "chunk_000.flac"
    chunk_path.parent.mkdir(parents=True)
    chunk_path.write_bytes(b"chunk")
    iterator = CountingSegmentIterator(
        [
            SimpleNamespace(start=0, end=1, text="first"),
            SimpleNamespace(start=1, end=2, text="second"),
        ]
    )

    class FakeWhisperModel:
        def __init__(self, *_args, **_kwargs):
            pass

        def transcribe(self, _file_path, **_kwargs):
            return iterator, SimpleNamespace(language="en")

    monkeypatch.setattr(transcription, "WhisperModel", FakeWhisperModel)
    monkeypatch.setenv("FASTER_WHISPER_MODEL_DIR", str(tmp_path / "models"))
    config = JobConfig(
        transcription_mode=TranscriptionMode.local_faster_whisper,
        transcription_model="small",
        local_whisper_device="cpu",
        local_whisper_compute_type="int8",
        note_api_key="note-key",
        note_model="gpt-5.5",
        note_language=NoteLanguage.zh,
        original_filename="input.mp4",
    )
    prepared = PreparedAudio(
        mp3_path=audio_path,
        chunks=[ChunkSpec(index=0, start=0, end=600, path=chunk_path)],
        duration=600,
    )
    checks = 0

    def is_cancelled() -> bool:
        nonlocal checks
        checks += 1
        return checks >= 5

    with pytest.raises(transcription.TranscriptionCancelled):
        transcription.transcribe_with_faster_whisper(
            audio_path,
            config,
            tmp_path,
            prepared_audio=prepared,
            is_cancelled=is_cancelled,
            hardware_profile=HardwareProfile(8, 16 * 1024**3, False, None),
        )

    result_dir = tmp_path / "work" / "asr" / "transcription_checkpoints" / "results"
    assert iterator.next_calls == 1
    assert not list(result_dir.glob("*.json"))


def test_transcribe_audio_uses_bundled_local_model_directory(tmp_path, monkeypatch) -> None:
    audio_path = tmp_path / "audio.mp3"
    audio_path.write_bytes(b"fake audio")
    bundled_model = tmp_path / "models" / "small"
    write_model_files(bundled_model)

    class FakeWhisperModel:
        def __init__(self, model_name, **kwargs):
            assert model_name == str(bundled_model)
            assert kwargs["download_root"] == str(tmp_path / "models")

        def transcribe(self, file_path, **_kwargs):
            assert file_path == str(audio_path)
            return [SimpleNamespace(start=0, end=1, text="bundled text")], SimpleNamespace(language="zh")

    monkeypatch.setattr(transcription, "WhisperModel", FakeWhisperModel)
    monkeypatch.setenv("FASTER_WHISPER_MODEL_DIR", str(tmp_path / "models"))

    config = JobConfig(
        transcription_mode=TranscriptionMode.local_faster_whisper,
        transcription_api_key="",
        transcription_base_url="",
        transcription_model="small",
        note_api_key="note-key",
        note_base_url="https://api.openai.com/v1",
        note_model="gpt-5.5",
        note_language=NoteLanguage.zh,
        original_filename="input.mp4",
    )

    parsed = transcription.transcribe_audio(audio_path, config, tmp_path)

    assert parsed["text"] == "bundled text"


def test_resolve_local_faster_whisper_model_uses_huggingface_snapshot(tmp_path) -> None:
    model_root = tmp_path / "models"
    snapshot_id = "abc123"
    repo_dir = model_root / "models--Systran--faster-whisper-small"
    (repo_dir / "refs").mkdir(parents=True)
    (repo_dir / "refs" / "main").write_text(snapshot_id, encoding="utf-8")
    snapshot_dir = repo_dir / "snapshots" / snapshot_id
    write_model_files(snapshot_dir)

    resolved = resolve_local_faster_whisper_model("small", model_root)

    assert resolved == str(snapshot_dir)


def test_resolve_local_faster_whisper_model_accepts_large_v3_vocabulary_json(tmp_path) -> None:
    model_root = tmp_path / "models"
    snapshot_id = "abc123"
    repo_dir = model_root / "models--Systran--faster-whisper-large-v3"
    (repo_dir / "refs").mkdir(parents=True)
    (repo_dir / "refs" / "main").write_text(snapshot_id, encoding="utf-8")
    snapshot_dir = repo_dir / "snapshots" / snapshot_id
    snapshot_dir.mkdir(parents=True)
    for name in ("config.json", "model.bin", "tokenizer.json", "vocabulary.json"):
        (snapshot_dir / name).write_text("x", encoding="utf-8")

    resolved = resolve_local_faster_whisper_model("large-v3", model_root)
    worker_resolved = local_whisper_worker.resolve_local_faster_whisper_model("large-v3", model_root)

    assert resolved == str(snapshot_dir)
    assert worker_resolved == str(snapshot_dir)


def test_resolve_local_faster_whisper_model_requires_local_files(tmp_path) -> None:
    with pytest.raises(transcription.TranscriptionError) as exc_info:
        resolve_local_faster_whisper_model("small", tmp_path / "models")

    message = str(exc_info.value)
    assert "Local Faster Whisper model 'small' is not available" in message
    assert str(tmp_path / "models") in message


def test_local_faster_whisper_missing_dependency_reports_import_error(tmp_path, monkeypatch) -> None:
    audio_path = tmp_path / "audio.mp3"
    audio_path.write_bytes(b"fake audio")
    write_model_files(tmp_path / "models" / "small")
    monkeypatch.setenv("FASTER_WHISPER_MODEL_DIR", str(tmp_path / "models"))
    monkeypatch.setattr(transcription, "WhisperModel", None)
    monkeypatch.setattr(transcription, "FASTER_WHISPER_IMPORT_ERROR", "No module named 'numpy._core._exceptions'")
    monkeypatch.setattr(
        transcription,
        "transcribe_with_external_faster_whisper",
        lambda *args, **kwargs: (_ for _ in ()).throw(transcription.TranscriptionError("External Python was not found.")),
    )

    config = JobConfig(
        transcription_mode=TranscriptionMode.local_faster_whisper,
        transcription_api_key="",
        transcription_base_url="",
        transcription_model="small",
        note_api_key="note-key",
        note_base_url="https://api.openai.com/v1",
        note_model="gpt-5.5",
        note_language=NoteLanguage.zh,
        original_filename="input.mp4",
    )

    with pytest.raises(transcription.TranscriptionError) as exc_info:
        transcription.transcribe_audio(audio_path, config, tmp_path)

    message = str(exc_info.value)
    assert "Local Faster Whisper is not available" in message
    assert "numpy._core._exceptions" in message


def test_transcribe_audio_uses_external_worker_when_internal_faster_whisper_is_missing(tmp_path, monkeypatch) -> None:
    audio_path = tmp_path / "audio.mp3"
    audio_path.write_bytes(b"fake audio")
    write_model_files(tmp_path / "models" / "small")
    monkeypatch.setattr(transcription, "WhisperModel", None)
    monkeypatch.setattr(transcription, "FASTER_WHISPER_IMPORT_ERROR", "No module named 'faster_whisper'")
    monkeypatch.setenv("FASTER_WHISPER_MODEL_DIR", str(tmp_path / "models"))

    def fake_external_worker(audio_path_arg, config_arg, model_root_arg, *, work_dir=None, progress_callback=None):
        assert audio_path_arg == audio_path
        assert config_arg.transcription_model == "small"
        assert model_root_arg == tmp_path / "models"
        assert progress_callback is None
        return TranscriptPayload(text="external text", segments=[TranscriptSegment(start=0, end=1, text="external text")])

    monkeypatch.setattr(transcription, "transcribe_with_external_faster_whisper", fake_external_worker)

    config = JobConfig(
        transcription_mode=TranscriptionMode.local_faster_whisper,
        transcription_api_key="",
        transcription_base_url="",
        transcription_model="small",
        note_api_key="note-key",
        note_base_url="https://api.openai.com/v1",
        note_model="gpt-5.5",
        note_language=NoteLanguage.zh,
        original_filename="input.mp4",
    )

    parsed = transcription.transcribe_audio(audio_path, config, tmp_path)

    assert parsed["text"] == "external text"


def test_external_faster_whisper_worker_forces_utf8_stdout(tmp_path, monkeypatch) -> None:
    audio_path = tmp_path / "audio.mp3"
    audio_path.write_bytes(b"fake audio")
    model_root = tmp_path / "models"
    write_model_files(model_root / "small")
    monkeypatch.setattr(transcription, "find_external_python", lambda: "python")
    monkeypatch.setattr(transcription, "probe_duration", lambda _p: 60.0)
    monkeypatch.setattr(transcription, "get_local_whisper_worker_path", lambda: tmp_path / "worker.py")
    (tmp_path / "worker.py").write_text("print('worker')", encoding="utf-8")

    def fake_run(*args, **kwargs):
        env = kwargs.get("env") or {}
        assert env["PYTHONIOENCODING"].lower() == "utf-8"
        return subprocess.CompletedProcess(
            args=args[0],
            returncode=0,
            stdout='{"text": "中文正常", "segments": [{"start": 0, "end": 1, "text": "中文正常"}]}',
            stderr="",
        )

    monkeypatch.setattr(transcription.subprocess, "run", fake_run)

    config = JobConfig(
        transcription_mode=TranscriptionMode.local_faster_whisper,
        transcription_api_key="",
        transcription_base_url="",
        transcription_model="small",
        note_api_key="note-key",
        note_base_url="https://api.openai.com/v1",
        note_model="gpt-5.5",
        note_language=NoteLanguage.zh,
        original_filename="input.mp4",
    )

    parsed = transcription.transcribe_with_external_faster_whisper(audio_path, config, model_root, work_dir=tmp_path)

    assert parsed.text == "中文正常"


def test_external_faster_whisper_worker_reports_progress_before_blocking_run(tmp_path, monkeypatch) -> None:
    audio_path = tmp_path / "audio.mp3"
    audio_path.write_bytes(b"fake audio")
    model_root = tmp_path / "models"
    write_model_files(model_root / "small")
    monkeypatch.setattr(transcription, "find_external_python", lambda: "python")
    monkeypatch.setattr(transcription, "probe_duration", lambda _p: 60.0)
    monkeypatch.setattr(transcription, "get_local_whisper_worker_path", lambda: tmp_path / "worker.py")
    (tmp_path / "worker.py").write_text("print('worker')", encoding="utf-8")

    def fake_run(*args, **kwargs):
        return subprocess.CompletedProcess(
            args=args[0],
            returncode=0,
            stdout='{"text": "中文正常", "segments": [{"start": 0, "end": 1, "text": "中文正常"}]}',
            stderr="",
        )

    monkeypatch.setattr(transcription.subprocess, "run", fake_run)

    updates: list[tuple[str, int]] = []
    config = JobConfig(
        transcription_mode=TranscriptionMode.local_faster_whisper,
        transcription_api_key="",
        transcription_base_url="",
        transcription_model="small",
        local_whisper_device="cuda",
        local_whisper_compute_type="float16",
        note_api_key="note-key",
        note_base_url="https://api.openai.com/v1",
        note_model="gpt-5.5",
        note_language=NoteLanguage.zh,
        original_filename="input.mp4",
    )

    parsed = transcription.transcribe_with_external_faster_whisper(
        audio_path,
        config,
        model_root,
        work_dir=tmp_path,
        progress_callback=lambda step, progress: updates.append((step, progress)),
    )

    assert parsed.text == "中文正常"
    assert updates == [("字幕生成中：外部 Faster Whisper worker 转写中", 38)]


def test_audio_transcriptions_reports_chunk_progress(monkeypatch, tmp_path) -> None:
    audio_path = tmp_path / "audio.mp3"
    audio_path.write_bytes(b"x" * 30_000_000)

    chunk_dir = tmp_path / "chunks"
    chunk_dir.mkdir()
    chunk_a = chunk_dir / "chunk_000.mp3"
    chunk_b = chunk_dir / "chunk_001.mp3"
    chunk_a.write_bytes(b"a")
    chunk_b.write_bytes(b"b")

    monkeypatch.setattr(transcription, "split_audio", lambda *_args, **_kwargs: [chunk_a, chunk_b])
    monkeypatch.setattr(transcription, "probe_duration", lambda _path: 10.0)
    monkeypatch.setattr(
        transcription,
        "call_audio_endpoint",
        lambda *_args, **_kwargs: {"text": "hello", "segments": [{"start": 0, "end": 1, "text": "hello"}]},
    )

    updates: list[tuple[str, int]] = []
    config = JobConfig(
        transcription_mode=TranscriptionMode.audio_transcriptions,
        transcription_api_key="test-key",
        transcription_base_url="https://api.openai.com/v1",
        transcription_model="whisper-1",
        note_api_key="note-key",
        note_base_url="https://api.openai.com/v1",
        note_model="gpt-5.5",
        note_language=NoteLanguage.zh,
        original_filename="input.mp4",
    )

    result = transcription.transcribe_with_audio_endpoint(
        audio_path,
        config,
        tmp_path,
        progress_callback=lambda step, progress: updates.append((step, progress)),
    )

    assert result.text == "hello hello"
    assert updates == [
        ("字幕生成中：第 1/2 段转写中", 35),
        ("字幕生成中：第 2/2 段转写中", 47),
    ]


def test_external_worker_env_injects_configured_model_root(monkeypatch) -> None:
    monkeypatch.delenv("FASTER_WHISPER_MODEL_DIR", raising=False)
    monkeypatch.delenv("HUGGINGFACE_HUB_CACHE", raising=False)
    monkeypatch.setenv("VIDEO_NOTE_MARKER", "keep-me")

    env = transcription.external_worker_env(model_root=Path("D:/custom/models"))

    expected = str(Path("D:/custom/models"))
    assert env["FASTER_WHISPER_MODEL_DIR"] == expected
    assert env["VIDEO_NOTE_MARKER"] == "keep-me"
    assert env["PYTHONIOENCODING"].lower() == "utf-8"


def test_external_worker_env_preserves_existing_huggingface_cache(monkeypatch) -> None:
    monkeypatch.setenv("HUGGINGFACE_HUB_CACHE", "C:/already/here")

    env = transcription.external_worker_env(model_root=Path("D:/custom/models"))

    assert env["HUGGINGFACE_HUB_CACHE"] == "C:/already/here"
    expected = str(Path("D:/custom/models"))


def test_external_worker_env_without_model_root_is_backward_compatible(monkeypatch) -> None:
    monkeypatch.delenv("FASTER_WHISPER_MODEL_DIR", raising=False)
    monkeypatch.delenv("HUGGINGFACE_HUB_CACHE", raising=False)

    env = transcription.external_worker_env()

    assert env["PYTHONIOENCODING"].lower() == "utf-8"
    assert "FASTER_WHISPER_MODEL_DIR" not in env
    assert "HUGGINGFACE_HUB_CACHE" not in env


def test_external_faster_whisper_worker_passes_resolved_model_root_to_env(tmp_path, monkeypatch) -> None:
    audio_path = tmp_path / "audio.mp3"
    audio_path.write_bytes(b"fake audio")
    model_root = tmp_path / "settings-models"
    write_model_files(model_root / "small")
    monkeypatch.setattr(transcription, "find_external_python", lambda: "python")
    monkeypatch.setattr(transcription, "probe_duration", lambda _p: 60.0)
    monkeypatch.setattr(transcription, "get_local_whisper_worker_path", lambda: tmp_path / "worker.py")
    (tmp_path / "worker.py").write_text("print('worker')", encoding="utf-8")
    monkeypatch.delenv("FASTER_WHISPER_MODEL_DIR", raising=False)

    captured_env = {}

    def fake_run(*args, **kwargs):
        captured_env.update(kwargs.get("env") or {})
        return subprocess.CompletedProcess(
            args=args[0],
            returncode=0,
            stdout='{"text": "ok", "segments": [{"start": 0, "end": 1, "text": "ok"}]}',
            stderr="",
        )

    monkeypatch.setattr(transcription.subprocess, "run", fake_run)

    config = JobConfig(
        transcription_mode=TranscriptionMode.local_faster_whisper,
        transcription_api_key="",
        transcription_base_url="",
        transcription_model="small",
        note_api_key="note-key",
        note_base_url="https://api.openai.com/v1",
        note_model="gpt-5.5",
        note_language=NoteLanguage.zh,
        original_filename="input.mp4",
    )

    transcription.transcribe_with_external_faster_whisper(audio_path, config, model_root, work_dir=tmp_path)

    assert captured_env["FASTER_WHISPER_MODEL_DIR"] == str(model_root)
    assert captured_env["HUGGINGFACE_HUB_CACHE"] == str(model_root)



def test_transcribe_with_faster_whisper_passes_explicit_language(tmp_path, monkeypatch) -> None:
    from types import SimpleNamespace
    audio_path = tmp_path / "audio.mp3"
    audio_path.write_bytes(b"fake audio")
    write_model_files(tmp_path / "models" / "small")

    captured: dict[str, object] = {}

    class FakeWhisperModel:
        def __init__(self, *_args, **_kwargs):
            pass

        def transcribe(self, _file_path, language=None, **_kwargs):
            captured["language"] = language
            return [SimpleNamespace(start=0, end=1, text="zh text")], SimpleNamespace(language="zh")

    monkeypatch.setattr(transcription, "WhisperModel", FakeWhisperModel)
    monkeypatch.setenv("FASTER_WHISPER_MODEL_DIR", str(tmp_path / "models"))

    config = JobConfig(
        transcription_mode=TranscriptionMode.local_faster_whisper,
        transcription_api_key="",
        transcription_base_url="",
        transcription_model="small",
        transcription_language=TranscriptionLanguage.zh,
        note_api_key="note-key",
        note_base_url="https://api.openai.com/v1",
        note_model="gpt-5.5",
        note_language=NoteLanguage.zh,
        original_filename="input.mp4",
    )

    parsed = transcription.transcribe_with_faster_whisper(audio_path, config, tmp_path)

    assert parsed.text == "zh text"
    assert captured["language"] == "zh"


def test_transcribe_with_faster_whisper_omits_language_for_auto(tmp_path, monkeypatch) -> None:
    from types import SimpleNamespace
    audio_path = tmp_path / "audio.mp3"
    audio_path.write_bytes(b"fake audio")
    write_model_files(tmp_path / "models" / "small")

    captured: dict[str, object] = {}

    class FakeWhisperModel:
        def __init__(self, *_args, **_kwargs):
            pass

        def transcribe(self, _file_path, language=None, **_kwargs):
            captured["language"] = language
            return [SimpleNamespace(start=0, end=1, text="auto text")], SimpleNamespace(language="zh")

    monkeypatch.setattr(transcription, "WhisperModel", FakeWhisperModel)
    monkeypatch.setenv("FASTER_WHISPER_MODEL_DIR", str(tmp_path / "models"))

    config = JobConfig(
        transcription_mode=TranscriptionMode.local_faster_whisper,
        transcription_api_key="",
        transcription_base_url="",
        transcription_model="small",
        transcription_language=TranscriptionLanguage.auto,
        note_api_key="note-key",
        note_base_url="https://api.openai.com/v1",
        note_model="gpt-5.5",
        note_language=NoteLanguage.zh,
        original_filename="input.mp4",
    )

    transcription.transcribe_with_faster_whisper(audio_path, config, tmp_path)

    assert captured["language"] is None
