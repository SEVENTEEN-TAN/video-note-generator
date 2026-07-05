from __future__ import annotations

import os
import sys
from pathlib import Path


def get_workspace_root() -> Path:
    return Path(__file__).resolve().parents[2]


def get_bundle_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).resolve().parent))
    return get_workspace_root()


def get_app_data_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return get_workspace_root()


def get_outputs_root() -> Path:
    override = os.getenv("VIDEO_NOTE_OUTPUTS_DIR", "").strip()
    if override:
        return Path(override).expanduser()
    return get_app_data_root() / "outputs"


def get_frontend_dist_dir() -> Path:
    override = os.getenv("VIDEO_NOTE_FRONTEND_DIST", "").strip()
    if override:
        return Path(override).expanduser()
    return get_bundle_root() / "frontend" / "dist"


def get_model_root() -> Path:
    from .runtime_config import get_configured_model_root

    return get_configured_model_root().as_path()


def get_backend_requirements_file(filename: str) -> Path:
    return get_bundle_root() / "backend" / filename
