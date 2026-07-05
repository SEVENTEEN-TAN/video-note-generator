from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from .runtime_paths import get_app_data_root
from .settings import load_user_settings


RuntimeConfigSource = Literal["environment", "settings", "default", "missing"]
PythonPackageInstallMode = Literal["default", "user"]


@dataclass(frozen=True)
class RuntimePathResolution:
    value: str
    source: RuntimeConfigSource
    error: str = ""

    def as_path(self) -> Path:
        return Path(self.value).expanduser()


def get_configured_external_python() -> RuntimePathResolution:
    env_value = os.getenv("VIDEO_NOTE_PYTHON_PATH", "").strip()
    if env_value:
        return _resolve_python_candidate(env_value, "environment")

    settings_value = load_user_settings().external_python_path.strip()
    if settings_value:
        return _resolve_python_candidate(settings_value, "settings")

    for executable in ("python", "python3", "py"):
        path = shutil.which(executable)
        if path:
            return RuntimePathResolution(value=path, source="default")
    return RuntimePathResolution(
        value="",
        source="missing",
        error="External Python was not found on PATH. Install Python 3.10+ or set VIDEO_NOTE_PYTHON_PATH.",
    )


def get_configured_model_root() -> RuntimePathResolution:
    env_value = os.getenv("FASTER_WHISPER_MODEL_DIR", "").strip()
    if env_value:
        return RuntimePathResolution(value=str(Path(env_value).expanduser()), source="environment")

    settings_value = load_user_settings().faster_whisper_model_dir.strip()
    if settings_value:
        return RuntimePathResolution(value=str(Path(settings_value).expanduser()), source="settings")

    return RuntimePathResolution(
        value=str(get_app_data_root() / "backend" / "models" / "faster-whisper"),
        source="default",
    )


def get_python_package_install_mode() -> PythonPackageInstallMode:
    return load_user_settings().python_package_install_mode


def get_python_package_install_args() -> list[str]:
    if get_python_package_install_mode() == "user":
        return ["--user"]
    return []


def _resolve_python_candidate(value: str, source: RuntimeConfigSource) -> RuntimePathResolution:
    resolved = shutil.which(value)
    if resolved:
        return RuntimePathResolution(value=resolved, source=source)

    path = Path(value).expanduser()
    looks_like_path = path.is_absolute() or "\\" in value or "/" in value
    if looks_like_path:
        if not path.exists():
            return RuntimePathResolution(
                value=str(path),
                source=source,
                error=f"Configured external Python path does not exist: {path}",
            )
        if not path.is_file():
            return RuntimePathResolution(
                value=str(path),
                source=source,
                error=f"Configured external Python path is not a file: {path}",
            )
        return RuntimePathResolution(value=str(path), source=source)

    return RuntimePathResolution(
        value=value,
        source=source,
        error=f"Configured external Python executable was not found on PATH: {value}",
    )
