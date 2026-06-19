from __future__ import annotations

from pathlib import Path

from backend.app.runtime_paths import get_model_root, get_outputs_root


def test_runtime_paths_allow_output_and_model_overrides(tmp_path, monkeypatch) -> None:
    outputs_dir = tmp_path / "custom-outputs"
    model_dir = tmp_path / "custom-models"
    monkeypatch.setenv("VIDEO_NOTE_OUTPUTS_DIR", str(outputs_dir))
    monkeypatch.setenv("FASTER_WHISPER_MODEL_DIR", str(model_dir))

    assert get_outputs_root() == outputs_dir
    assert get_model_root() == model_dir
    assert isinstance(get_outputs_root(), Path)
