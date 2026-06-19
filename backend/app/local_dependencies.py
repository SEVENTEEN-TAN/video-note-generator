from __future__ import annotations

import subprocess
import threading

from pydantic import BaseModel

from .transcription import TranscriptionError, external_worker_env, find_external_python

LOCAL_TRANSCRIPTION_DEPENDENCY_PACKAGES = (
    "fastapi==0.115.6",
    "uvicorn[standard]==0.34.0",
    "python-multipart==0.0.20",
    "openai==1.59.7",
    "pydantic==2.12.5",
    "imageio-ffmpeg==0.5.1",
    "faster-whisper==1.1.1",
)


class LocalTranscriptionDependencyInstallState(BaseModel):
    status: str = "idle"
    progress: int = 0
    error: str = ""
    python_path: str = ""


_state = LocalTranscriptionDependencyInstallState()
_lock = threading.Lock()


def clear_local_dependency_install_state() -> None:
    global _state
    with _lock:
        _state = LocalTranscriptionDependencyInstallState()



def get_local_dependency_install_state() -> LocalTranscriptionDependencyInstallState:
    with _lock:
        return _state



def start_local_dependency_install() -> LocalTranscriptionDependencyInstallState:
    global _state
    python_path = find_external_python() or ""
    with _lock:
        if _state.status in {"pending", "running"}:
            return _state
        _state = LocalTranscriptionDependencyInstallState(status="pending", progress=0, error="", python_path=python_path)
        return _state



def run_local_dependency_install() -> None:
    python_path = find_external_python()
    if not python_path:
        set_local_dependency_install_state(
            status="failed",
            progress=0,
            error="External Python was not found on PATH. Install Python 3.10+ or set VIDEO_NOTE_PYTHON_PATH.",
            python_path="",
        )
        return

    set_local_dependency_install_state(status="running", progress=10, error="", python_path=python_path)
    try:
        install_local_transcription_dependencies(python_path)
        set_local_dependency_install_state(status="succeeded", progress=100, error="", python_path=python_path)
    except Exception as exc:
        set_local_dependency_install_state(status="failed", progress=0, error=str(exc), python_path=python_path)



def set_local_dependency_install_state(status: str, progress: int, error: str, python_path: str) -> None:
    global _state
    with _lock:
        _state = LocalTranscriptionDependencyInstallState(
            status=status,
            progress=progress,
            error=error,
            python_path=python_path,
        )



def install_local_transcription_dependencies(python_path: str) -> None:
    completed = subprocess.run(
        [
            python_path,
            "-m",
            "pip",
            "install",
            *LOCAL_TRANSCRIPTION_DEPENDENCY_PACKAGES,
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=external_worker_env(),
    )
    if completed.returncode != 0:
        message = completed.stderr.strip() or completed.stdout.strip() or "Local transcription dependency installation failed."
        raise TranscriptionError(message[-2000:])
