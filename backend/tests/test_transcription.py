import subprocess
from types import SimpleNamespace
from pathlib import Path

import pytest
from pydantic import ValidationError

from backend.app import local_whisper_worker, transcription
from backend.app.models import JobConfig, NoteLanguage, TranscriptPayload, TranscriptSegment, TranscriptionLanguage, TranscriptionMode
from backend.app.transcription import (
    faster_whisper_segments_to_payload,
    parse_chat_audio_payload,
    resolve_local_faster_whisper_model,
)


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

    def fake_external_worker(audio_path_arg, config_arg, model_root_arg, progress_callback=None):
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

    parsed = transcription.transcribe_with_external_faster_whisper(audio_path, config, model_root)

    assert parsed.text == "中文正常"


def test_external_faster_whisper_worker_reports_progress_before_blocking_run(tmp_path, monkeypatch) -> None:
    audio_path = tmp_path / "audio.mp3"
    audio_path.write_bytes(b"fake audio")
    model_root = tmp_path / "models"
    write_model_files(model_root / "small")
    monkeypatch.setattr(transcription, "find_external_python", lambda: "python")
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

    transcription.transcribe_with_external_faster_whisper(audio_path, config, model_root)

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

    parsed = transcription.transcribe_with_faster_whisper(audio_path, config)

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

    transcription.transcribe_with_faster_whisper(audio_path, config)

    assert captured["language"] is None
