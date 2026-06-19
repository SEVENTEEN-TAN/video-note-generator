from __future__ import annotations

import importlib

from . import transcription
from .ffmpeg_tools import get_ffmpeg_path
from .runtime_paths import get_model_root
from .settings import get_settings_path


def get_cuda_device_count() -> int | None:
    try:
        ctranslate2 = importlib.import_module("ctranslate2")
        return int(ctranslate2.get_cuda_device_count())
    except Exception:
        return None


def get_runtime_status() -> dict:
    ffmpeg_path = get_ffmpeg_path()
    cuda_device_count = get_cuda_device_count()
    internal_faster_whisper_available = transcription.WhisperModel is not None
    external_python_path = transcription.find_external_python()
    external_worker_path = transcription.get_local_whisper_worker_path()
    external_worker_available = bool(external_python_path) and external_worker_path.exists()
    faster_whisper_available = internal_faster_whisper_available or external_worker_available
    model_root = get_model_root()
    local_models = transcription.discover_local_faster_whisper_models(model_root)

    return {
        "ok": bool(ffmpeg_path) and faster_whisper_available,
        "ffmpeg": {
            "available": bool(ffmpeg_path),
            "path": ffmpeg_path,
            "install_hint": "" if ffmpeg_path else "Install FFmpeg, then restart the app. Windows: winget install Gyan.FFmpeg, or install backend dependencies with python -m pip install -r backend/requirements.txt.",
        },
        "faster_whisper": {
            "available": faster_whisper_available,
            "internal_available": internal_faster_whisper_available,
            "internal_import_error": "" if internal_faster_whisper_available else transcription.FASTER_WHISPER_IMPORT_ERROR,
            "cuda_available": bool(cuda_device_count),
            "cuda_device_count": cuda_device_count,
            "external_python_path": external_python_path,
            "external_worker_path": str(external_worker_path),
            "external_worker_available": external_worker_available,
            "import_error": "" if faster_whisper_available else transcription.FASTER_WHISPER_IMPORT_ERROR,
            "install_hint": "" if faster_whisper_available else "Install Python 3.10+, then run python -m pip install -r backend/requirements.txt. Restart the app or set VIDEO_NOTE_PYTHON_PATH if Python is not on PATH.",
        },
        "local_models": {
            "root": str(model_root),
            "models": local_models,
            "hint": "Put Faster Whisper model folders here for local transcription. The app validates local files before starting a job and will not rely on a first-run network download.",
        },
        "settings": {
            "path": str(get_settings_path()),
            "warning": "API keys saved here are stored in local plaintext JSON.",
        },
    }
