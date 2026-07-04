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
    assert status["faster_whisper"]["internal_available"] is True
    assert status["faster_whisper"]["internal_import_error"] == ""
    assert status["faster_whisper"]["python_available"] is False
    assert status["faster_whisper"]["worker_ready"] is False
    assert status["faster_whisper"]["ready_for_cpu"] is True
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
    assert status["faster_whisper"]["python_available"] is False
    assert status["faster_whisper"]["worker_ready"] is False
    assert status["faster_whisper"]["ready_for_cpu"] is False
    assert "Install Python 3.10+" in status["faster_whisper"]["install_hint"]
    assert status["local_models"]["models"] == []


def test_runtime_status_marks_external_worker_unavailable_without_required_packages(tmp_path, monkeypatch) -> None:
    worker_path = tmp_path / "worker.py"
    worker_path.write_text("print('worker')", encoding="utf-8")
    model_root = tmp_path / "models"
    write_model_files(model_root / "small")
    monkeypatch.setenv("FASTER_WHISPER_MODEL_DIR", str(model_root))
    monkeypatch.setattr(runtime_status, "get_ffmpeg_path", lambda: "C:/ffmpeg/bin/ffmpeg.exe")
    monkeypatch.setattr(transcription, "WhisperModel", None)
    monkeypatch.setattr(transcription, "FASTER_WHISPER_IMPORT_ERROR", "No module named 'faster_whisper'")
    monkeypatch.setattr(transcription, "find_external_python", lambda: "python")
    monkeypatch.setattr(transcription, "get_local_whisper_worker_path", lambda: worker_path)
    monkeypatch.setattr(
        runtime_status,
        "get_external_runtime_status",
        lambda *_args: {
            "python_path": "python",
            "faster_whisper_available": False,
            "faster_whisper_error": "No module named 'faster_whisper'",
            "ctranslate2_available": False,
            "ctranslate2_version": "",
            "cuda_device_count": None,
            "cuda_runtime_available": False,
            "cuda_error": "",
            "cuda_dll_dirs": [],
            "source": "external",
        },
    )

    status = runtime_status.get_runtime_status()

    assert status["ok"] is False
    assert status["faster_whisper"]["external_worker_available"] is True
    assert status["faster_whisper"]["python_available"] is True
    assert status["faster_whisper"]["worker_ready"] is False
    assert status["faster_whisper"]["available"] is False
    assert status["faster_whisper"]["ready_for_cpu"] is False
    assert status["faster_whisper"]["worker_error"] == "No module named 'faster_whisper'"
    assert "backend/requirements.txt" in status["faster_whisper"]["install_hint"]


def test_runtime_status_reports_external_cuda_runtime_error(tmp_path, monkeypatch) -> None:
    worker_path = tmp_path / "worker.py"
    worker_path.write_text("print('worker')", encoding="utf-8")
    model_root = tmp_path / "models"
    write_model_files(model_root / "small")
    monkeypatch.setenv("FASTER_WHISPER_MODEL_DIR", str(model_root))
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
        "get_external_runtime_status",
        lambda *_args: {
            "python_path": "python",
            "faster_whisper_available": True,
            "faster_whisper_error": "",
            "ctranslate2_available": True,
            "ctranslate2_version": "4.5.0",
            "cuda_device_count": 1,
            "cuda_runtime_available": False,
            "cuda_error": "cublas64_12.dll is not found or cannot be loaded",
            "cuda_dll_dirs": ["C:/Python/Lib/site-packages/nvidia/cublas/bin"],
            "source": "external",
        },
    )

    status = runtime_status.get_runtime_status()

    assert status["faster_whisper"]["available"] is True
    assert status["faster_whisper"]["worker_ready"] is True
    assert status["faster_whisper"]["ready_for_cpu"] is True
    assert status["faster_whisper"]["ready_for_cuda"] is False
    assert status["faster_whisper"]["cuda_available"] is False
    assert status["faster_whisper"]["cuda_device_count"] == 1
    assert status["faster_whisper"]["cuda_source"] == "external"
    assert "cublas64_12.dll" in status["faster_whisper"]["cuda_error"]


def test_runtime_status_reports_configured_path_sources(tmp_path, monkeypatch) -> None:
    from backend.app.settings import save_user_settings

    settings_path = tmp_path / "settings.json"
    python_path = tmp_path / "Python310" / "python.exe"
    worker_path = tmp_path / "worker.py"
    model_root = tmp_path / "custom-models"
    python_path.parent.mkdir(parents=True)
    python_path.write_text("fake python", encoding="utf-8")
    worker_path.write_text("print('worker')", encoding="utf-8")
    write_model_files(model_root / "small")

    monkeypatch.setenv("VIDEO_NOTE_SETTINGS_FILE", str(settings_path))
    monkeypatch.delenv("VIDEO_NOTE_PYTHON_PATH", raising=False)
    monkeypatch.delenv("FASTER_WHISPER_MODEL_DIR", raising=False)
    save_user_settings(
        {
            "external_python_path": str(python_path),
            "faster_whisper_model_dir": str(model_root),
            "python_package_install_mode": "user",
        }
    )
    monkeypatch.setattr(runtime_status, "get_ffmpeg_path", lambda: "C:/ffmpeg/bin/ffmpeg.exe")
    monkeypatch.setattr(transcription, "WhisperModel", None)
    monkeypatch.setattr(transcription, "FASTER_WHISPER_IMPORT_ERROR", "No module named 'faster_whisper'")
    monkeypatch.setattr(transcription, "get_local_whisper_worker_path", lambda: worker_path)
    monkeypatch.setattr(
        runtime_status,
        "get_external_runtime_status",
        lambda *_args: {
            "python_path": str(python_path),
            "faster_whisper_available": True,
            "faster_whisper_error": "",
            "ctranslate2_available": True,
            "ctranslate2_version": "4.5.0",
            "cuda_device_count": None,
            "cuda_runtime_available": False,
            "cuda_error": "",
            "cuda_dll_dirs": [],
            "source": "external",
        },
    )

    status = runtime_status.get_runtime_status()

    assert status["faster_whisper"]["external_python_path"] == str(python_path)
    assert status["faster_whisper"]["external_python_source"] == "settings"
    assert status["faster_whisper"]["external_python_error"] == ""
    assert status["faster_whisper"]["python_package_install_mode"] == "user"
    assert status["local_models"]["root"] == str(model_root)
    assert status["local_models"]["root_source"] == "settings"
    assert status["local_models"]["models"] == ["small"]
