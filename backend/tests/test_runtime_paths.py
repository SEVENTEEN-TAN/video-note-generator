from __future__ import annotations

from pathlib import Path

from backend.app.runtime_paths import get_model_root, get_outputs_root
from backend.app.settings import save_user_settings


def test_runtime_paths_allow_output_and_model_overrides(tmp_path, monkeypatch) -> None:
    outputs_dir = tmp_path / "custom-outputs"
    model_dir = tmp_path / "custom-models"
    monkeypatch.setenv("VIDEO_NOTE_OUTPUTS_DIR", str(outputs_dir))
    monkeypatch.setenv("FASTER_WHISPER_MODEL_DIR", str(model_dir))

    assert get_outputs_root() == outputs_dir
    assert get_model_root() == model_dir
    assert isinstance(get_outputs_root(), Path)


def test_runtime_model_root_uses_saved_settings(tmp_path, monkeypatch) -> None:
    settings_path = tmp_path / "settings.json"
    model_dir = tmp_path / "settings-models"
    monkeypatch.setenv("VIDEO_NOTE_SETTINGS_FILE", str(settings_path))
    monkeypatch.delenv("FASTER_WHISPER_MODEL_DIR", raising=False)
    save_user_settings({"faster_whisper_model_dir": str(model_dir)})

    assert get_model_root() == model_dir
