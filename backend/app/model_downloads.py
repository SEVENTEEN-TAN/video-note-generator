from __future__ import annotations

import re
import subprocess
import threading
from pathlib import Path

from pydantic import BaseModel, Field, field_validator

from .transcription import (
    TranscriptionError,
    external_worker_env,
    find_external_python,
    get_faster_whisper_model_root,
    get_local_whisper_worker_path,
    resolve_local_faster_whisper_model,
)

MODEL_NAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


class ModelDownloadRequest(BaseModel):
    model_name: str = Field(default="small")

    @field_validator("model_name")
    @classmethod
    def validate_model_name(cls, value: str) -> str:
        value = value.strip()
        if not MODEL_NAME_PATTERN.fullmatch(value):
            raise ValueError("model_name may only contain letters, numbers, dots, underscores, and hyphens.")
        return value


class ModelDownloadState(BaseModel):
    model_name: str
    status: str = "pending"
    progress: int = 0
    error: str = ""
    model_root: str


_states: dict[str, ModelDownloadState] = {}
_lock = threading.Lock()


def clear_model_download_states() -> None:
    with _lock:
        _states.clear()


def get_model_download_state(model_name: str) -> ModelDownloadState:
    model_name = ModelDownloadRequest(model_name=model_name).model_name
    with _lock:
        state = _states.get(model_name)
        if state:
            return state
    model_root = get_faster_whisper_model_root()
    try:
        resolve_local_faster_whisper_model(model_name, model_root)
        return ModelDownloadState(model_name=model_name, status="succeeded", progress=100, model_root=str(model_root))
    except TranscriptionError:
        return ModelDownloadState(model_name=model_name, status="idle", progress=0, model_root=str(model_root))


def start_model_download(model_name: str) -> ModelDownloadState:
    model_name = ModelDownloadRequest(model_name=model_name).model_name
    model_root = get_faster_whisper_model_root()
    try:
        resolve_local_faster_whisper_model(model_name, model_root)
        state = ModelDownloadState(model_name=model_name, status="succeeded", progress=100, model_root=str(model_root))
    except TranscriptionError:
        state = ModelDownloadState(model_name=model_name, status="pending", progress=0, model_root=str(model_root))

    with _lock:
        current = _states.get(model_name)
        if current and current.status in {"pending", "running"}:
            return current
        _states[model_name] = state
        return state


def run_model_download(model_name: str) -> None:
    model_name = ModelDownloadRequest(model_name=model_name).model_name
    model_root = get_faster_whisper_model_root()
    set_model_download_state(model_name, status="running", progress=5, error="", model_root=model_root)
    try:
        download_faster_whisper_model(model_name, model_root)
        resolve_local_faster_whisper_model(model_name, model_root)
        set_model_download_state(model_name, status="succeeded", progress=100, error="", model_root=model_root)
    except Exception as exc:
        set_model_download_state(model_name, status="failed", progress=0, error=str(exc), model_root=model_root)


def set_model_download_state(model_name: str, status: str, progress: int, error: str, model_root: Path) -> None:
    with _lock:
        _states[model_name] = ModelDownloadState(
            model_name=model_name,
            status=status,
            progress=progress,
            error=error,
            model_root=str(model_root),
        )


def download_faster_whisper_model(model_name: str, model_root: Path) -> None:
    python_path = find_external_python()
    if not python_path:
        raise TranscriptionError("External Python was not found on PATH. Install Python 3.10+ or set VIDEO_NOTE_PYTHON_PATH.")

    worker_path = get_local_whisper_worker_path()
    if not worker_path.exists():
        raise TranscriptionError(f"External Faster Whisper worker script was not found: {worker_path}")

    completed = subprocess.run(
        [
            python_path,
            str(worker_path),
            "--download-only",
            "--model",
            model_name,
            "--model-root",
            str(model_root),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=external_worker_env(model_root=model_root),
    )
    if completed.returncode != 0:
        message = completed.stderr.strip() or completed.stdout.strip() or "Model download failed."
        raise TranscriptionError(message[-2000:])
