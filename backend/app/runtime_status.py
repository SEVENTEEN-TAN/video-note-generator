from __future__ import annotations

import importlib
import json
import subprocess

from . import transcription
from .ffmpeg_tools import get_ffmpeg_path
from .runtime_config import get_configured_external_python, get_configured_model_root, get_python_package_install_mode
from .runtime_models import RuntimeState
from .settings import get_settings_storage_status


def get_internal_cuda_status() -> dict:
    status = {
        "source": "internal",
        "cuda_device_count": None,
        "cuda_runtime_available": False,
        "cuda_error": "",
    }
    try:
        ctranslate2 = importlib.import_module("ctranslate2")
        count = int(ctranslate2.get_cuda_device_count())
        status["cuda_device_count"] = count
        status["cuda_runtime_available"] = count > 0
    except Exception as exc:
        status["cuda_error"] = str(exc)
    return status


def get_external_runtime_status(python_path: str | None, worker_path: str) -> dict:
    status = {
        "python_path": python_path or "",
        "faster_whisper_available": False,
        "faster_whisper_error": "",
        "worker_error_code": "",
        "worker_error": "",
        "ctranslate2_available": False,
        "ctranslate2_version": "",
        "cuda_device_count": None,
        "cuda_runtime_available": False,
        "cuda_error": "",
        "cuda_dll_dirs": [],
        "source": "external",
    }
    if not python_path:
        status["worker_error_code"] = "python_not_found"
        status["worker_error"] = "External Python was not found."
        return status
    try:
        completed = subprocess.run(
            [python_path, worker_path, "--runtime-status"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=20,
            env=transcription.external_worker_env(),
        )
        if completed.returncode != 0:
            status["worker_error_code"] = "worker_process_failed"
            status["worker_error"] = completed.stderr.strip() or completed.stdout.strip() or "External worker status check failed."
            return status
        try:
            payload = json.loads(completed.stdout)
        except json.JSONDecodeError as exc:
            status["worker_error_code"] = "worker_invalid_response"
            status["worker_error"] = str(exc)
            return status
        status.update(
            {
                "python_path": str(payload.get("python_path") or python_path),
                "faster_whisper_available": bool(payload.get("faster_whisper_available")),
                "faster_whisper_error": str(payload.get("faster_whisper_error") or ""),
                "ctranslate2_available": bool(payload.get("ctranslate2_available")),
                "ctranslate2_version": str(payload.get("ctranslate2_version") or ""),
                "cuda_device_count": payload.get("cuda_device_count"),
                "cuda_runtime_available": bool(payload.get("cuda_runtime_available")),
                "cuda_error": str(payload.get("cuda_error") or ""),
                "cuda_dll_dirs": payload.get("cuda_dll_dirs") or [],
            }
        )
    except subprocess.TimeoutExpired as exc:
        status["worker_error_code"] = "worker_timeout"
        status["worker_error"] = str(exc)
    except OSError as exc:
        status["worker_error_code"] = "worker_launch_failed"
        status["worker_error"] = str(exc)
    except Exception as exc:
        status["worker_error_code"] = "worker_probe_failed"
        status["worker_error"] = str(exc)
    return status


def choose_cuda_status(internal_status: dict, external_status: dict | None) -> dict:
    if external_status and (external_status.get("cuda_runtime_available") or external_status.get("cuda_device_count")):
        return external_status
    if internal_status.get("cuda_runtime_available") or not external_status:
        return internal_status
    return external_status


def build_faster_whisper_install_hint(
    *,
    internal_available: bool,
    python_available: bool,
    worker_ready: bool,
    worker_error: str,
    worker_error_code: str = "",
) -> str:
    if internal_available or worker_ready:
        return ""
    if not python_available:
        return "Install Python 3.10+, then run python -m pip install -r backend/requirements.txt. Restart the app or set VIDEO_NOTE_PYTHON_PATH if Python is not on PATH."
    if worker_error_code:
        return worker_error or "The external transcription worker could not be verified."
    if worker_error:
        return (
            "Install the local transcription packages into the external Python environment with "
            "python -m pip install -r backend/requirements.txt. "
            f"Current worker error: {worker_error}"
        )
    return "Install the local transcription packages into the external Python environment with python -m pip install -r backend/requirements.txt."


def get_runtime_status() -> dict:
    ffmpeg_path = get_ffmpeg_path()
    internal_faster_whisper_available = transcription.WhisperModel is not None
    external_python = get_configured_external_python()
    external_python_path = transcription.find_external_python()
    external_worker_path = transcription.get_local_whisper_worker_path()
    external_worker_available = bool(external_python_path) and external_worker_path.exists()
    external_runtime = (
        get_external_runtime_status(external_python_path, str(external_worker_path)) if external_worker_available else None
    )
    python_available = bool(external_python_path)
    worker_ready = bool(external_runtime and external_runtime.get("faster_whisper_available"))
    worker_error = str(external_runtime.get("faster_whisper_error") or "") if external_runtime else ""
    worker_error_code = str(external_runtime.get("worker_error_code") or "") if external_runtime else ""
    worker_probe_error = str(external_runtime.get("worker_error") or "") if external_runtime else ""
    faster_whisper_available = internal_faster_whisper_available or worker_ready
    internal_cuda_status = get_internal_cuda_status()
    cuda_status = choose_cuda_status(internal_cuda_status, external_runtime)
    model_root_config = get_configured_model_root()
    model_root = model_root_config.as_path()
    local_models = transcription.discover_local_faster_whisper_models(model_root)
    model_available = len(local_models) > 0
    ready_for_cpu = faster_whisper_available and model_available
    ready_for_cuda = ready_for_cpu and bool(cuda_status["cuda_runtime_available"])
    install_hint = build_faster_whisper_install_hint(
        internal_available=internal_faster_whisper_available,
        python_available=python_available,
        worker_ready=worker_ready,
        worker_error=worker_probe_error or worker_error,
        worker_error_code=worker_error_code,
    )
    ffmpeg_available = bool(ffmpeg_path)
    capabilities = {
        "video_processing": _capability(
            ffmpeg_available,
            available_reason="FFmpeg is available for video probing, audio extraction, and frame capture.",
            unavailable_reason="FFmpeg is required for video processing.",
        ),
        "uploaded_subtitle": _capability(
            ffmpeg_available,
            available_reason="Uploaded subtitles can be parsed and paired with the video.",
            unavailable_reason="FFmpeg is required to probe the video and extract note frames.",
        ),
        "local_transcription_cpu": _capability(
            ffmpeg_available and ready_for_cpu,
            available_reason="FFmpeg, Faster Whisper, and a local model are ready for CPU transcription.",
            unavailable_reason=_local_transcription_unavailable_reason(
                ffmpeg_available=ffmpeg_available,
                engine_available=faster_whisper_available,
                model_available=model_available,
                install_hint=install_hint,
            ),
        ),
        "local_transcription_cuda": _capability(
            ffmpeg_available and ready_for_cuda,
            available_reason="Local Faster Whisper is ready for CUDA transcription.",
            unavailable_reason=(
                _local_transcription_unavailable_reason(
                    ffmpeg_available=ffmpeg_available,
                    engine_available=faster_whisper_available,
                    model_available=model_available,
                    install_hint=install_hint,
                )
                if not ready_for_cpu
                else str(cuda_status.get("cuda_error") or "CUDA runtime libraries are not ready.")
            ),
        ),
        "audio_transcriptions": _capability(
            ffmpeg_available,
            available_reason="The local video preparation path is ready; endpoint credentials are checked when a job starts.",
            unavailable_reason="FFmpeg is required before audio can be sent to a transcription endpoint.",
            requires_credentials=True,
        ),
        "chat_audio": _capability(
            ffmpeg_available,
            available_reason="The local audio chunking path is ready; endpoint credentials are checked when a job starts.",
            unavailable_reason="FFmpeg is required before audio chunks can be sent to a chat endpoint.",
            requires_credentials=True,
        ),
        "note_generation": _capability(
            True,
            available_reason="The note client is installed; endpoint credentials are checked when notes are generated.",
            unavailable_reason="The note client is unavailable.",
            requires_credentials=True,
        ),
    }

    payload = {
        # Backward-compatible core readiness. Optional local transcription is
        # represented separately in the capability matrix.
        "ok": capabilities["video_processing"]["available"],
        "capabilities": capabilities,
        "ffmpeg": {
            "available": ffmpeg_available,
            "path": ffmpeg_path,
            "install_hint": "" if ffmpeg_path else "Install FFmpeg, then restart the app. Windows: winget install Gyan.FFmpeg, or install backend dependencies with python -m pip install -r backend/requirements.txt.",
        },
        "faster_whisper": {
            "available": faster_whisper_available,
            "internal_available": internal_faster_whisper_available,
            "internal_import_error": "" if internal_faster_whisper_available else transcription.FASTER_WHISPER_IMPORT_ERROR,
            "python_available": python_available,
            "external_python_path": external_python_path,
            "external_python_source": external_python.source,
            "external_python_error": external_python.error,
            "python_package_install_mode": get_python_package_install_mode(),
            "external_worker_path": str(external_worker_path),
            "external_worker_available": external_worker_available,
            "worker_ready": worker_ready,
            "worker_error": worker_error,
            "worker_error_code": worker_error_code,
            "worker_probe_error": worker_probe_error,
            "ctranslate2_available": bool(external_runtime and external_runtime.get("ctranslate2_available")),
            "ctranslate2_version": str(external_runtime.get("ctranslate2_version") or "") if external_runtime else "",
            "cuda_available": bool(cuda_status["cuda_runtime_available"]),
            "cuda_device_count": cuda_status["cuda_device_count"],
            "cuda_runtime_available": bool(cuda_status["cuda_runtime_available"]),
            "cuda_error": cuda_status["cuda_error"],
            "cuda_source": cuda_status["source"],
            "cuda_runtime_hint": "" if cuda_status["cuda_runtime_available"] else "For CUDA Faster Whisper, install CUDA 12 cuBLAS/cuDNN runtime libraries, for example: python -m pip install nvidia-cublas-cu12 nvidia-cudnn-cu12.",
            "cuda_dll_dirs": external_runtime.get("cuda_dll_dirs") if external_runtime else [],
            "import_error": "" if faster_whisper_available else transcription.FASTER_WHISPER_IMPORT_ERROR,
            "install_hint": install_hint,
            "model_available": model_available,
            "ready_for_cpu": ready_for_cpu,
            "ready_for_cuda": ready_for_cuda,
        },
        "local_models": {
            "root": str(model_root),
            "root_source": model_root_config.source,
            "models": local_models,
            "hint": "Put Faster Whisper model folders here for local transcription. The app validates local files before starting a job and will not rely on a first-run network download.",
        },
        "settings": get_settings_storage_status(),
    }
    return RuntimeState.model_validate(payload).model_dump(mode="json")


def _capability(
    available: bool,
    *,
    available_reason: str,
    unavailable_reason: str,
    requires_credentials: bool = False,
) -> dict:
    return {
        "available": bool(available),
        "reason": available_reason if available else unavailable_reason,
        "requires_credentials": requires_credentials,
    }


def _local_transcription_unavailable_reason(
    *,
    ffmpeg_available: bool,
    engine_available: bool,
    model_available: bool,
    install_hint: str,
) -> str:
    if not ffmpeg_available:
        return "FFmpeg is required for local transcription."
    if not engine_available:
        return install_hint or "Faster Whisper is not available."
    if not model_available:
        return "No validated local Faster Whisper model is available."
    return "Local transcription is not ready."
