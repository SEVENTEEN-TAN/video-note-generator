from __future__ import annotations

from backend.app import runtime_status, transcription


def write_model_files(model_dir) -> None:
    model_dir.mkdir(parents=True)
    for name in ("config.json", "model.bin", "tokenizer.json", "vocabulary.txt"):
        (model_dir / name).write_text("x", encoding="utf-8")


def test_runtime_status_reports_dependencies_and_local_models(tmp_path, monkeypatch) -> None:
    model_root = tmp_path / "models"
    write_model_files(model_root / "small")
    write_model_files(model_root / "large-v3")
    (model_root / "readme.txt").write_text("ignore", encoding="utf-8")
    monkeypatch.setenv("FASTER_WHISPER_MODEL_DIR", str(model_root))
    monkeypatch.setattr(runtime_status, "get_ffmpeg_path", lambda: "C:/ffmpeg/bin/ffmpeg.exe")
    monkeypatch.setattr(transcription, "WhisperModel", object())
    monkeypatch.setattr(transcription, "FASTER_WHISPER_IMPORT_ERROR", "")
    monkeypatch.setattr(transcription, "find_external_python", lambda: None)

    status = runtime_status.get_runtime_status()

    assert status["ok"] is True
    assert status["ffmpeg"]["available"] is True
    assert status["ffmpeg"]["path"] == "C:/ffmpeg/bin/ffmpeg.exe"
    assert status["faster_whisper"]["available"] is True
    assert status["faster_whisper"]["import_error"] == ""
    assert status["local_models"]["root"] == str(model_root)
    assert status["local_models"]["models"] == ["large-v3", "small"]


def test_runtime_status_reports_install_hints_when_dependencies_missing(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("FASTER_WHISPER_MODEL_DIR", str(tmp_path / "missing-models"))
    monkeypatch.setattr(runtime_status, "get_ffmpeg_path", lambda: None)
    monkeypatch.setattr(transcription, "WhisperModel", None)
    monkeypatch.setattr(transcription, "FASTER_WHISPER_IMPORT_ERROR", "No module named 'faster_whisper'")
    monkeypatch.setattr(transcription, "find_external_python", lambda: None)

    status = runtime_status.get_runtime_status()

    assert status["ok"] is False
    assert status["ffmpeg"]["available"] is False
    assert "FFmpeg" in status["ffmpeg"]["install_hint"]
    assert status["faster_whisper"]["available"] is False
    assert "python -m pip install -r backend/requirements.txt" in status["faster_whisper"]["install_hint"]
    assert status["local_models"]["models"] == []


def test_runtime_status_reports_external_cuda_runtime_error(tmp_path, monkeypatch) -> None:
    worker_path = tmp_path / "worker.py"
    worker_path.write_text("print('worker')", encoding="utf-8")
    monkeypatch.setenv("FASTER_WHISPER_MODEL_DIR", str(tmp_path / "models"))
    monkeypatch.setattr(runtime_status, "get_ffmpeg_path", lambda: "C:/ffmpeg/bin/ffmpeg.exe")
    monkeypatch.setattr(transcription, "WhisperModel", None)
    monkeypatch.setattr(transcription, "FASTER_WHISPER_IMPORT_ERROR", "No module named 'faster_whisper'")
    monkeypatch.setattr(transcription, "find_external_python", lambda: "python")
    monkeypatch.setattr(transcription, "get_local_whisper_worker_path", lambda: worker_path)
    monkeypatch.setattr(
        runtime_status,
        "get_internal_cuda_status",
        lambda: {"source": "internal", "cuda_device_count": None, "cuda_runtime_available": False, "cuda_error": ""},
    )
    monkeypatch.setattr(
        runtime_status,
        "get_external_cuda_status",
        lambda *_args: {
            "source": "external",
            "cuda_device_count": 1,
            "cuda_runtime_available": False,
            "cuda_error": "cublas64_12.dll is not found or cannot be loaded",
        },
    )

    status = runtime_status.get_runtime_status()

    assert status["faster_whisper"]["cuda_available"] is False
    assert status["faster_whisper"]["cuda_device_count"] == 1
    assert status["faster_whisper"]["cuda_source"] == "external"
    assert "cublas64_12.dll" in status["faster_whisper"]["cuda_error"]
