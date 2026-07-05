from __future__ import annotations

from backend.app.runtime_config import (
    get_configured_external_python,
    get_configured_model_root,
    get_python_package_install_args,
    get_python_package_install_mode,
)
from backend.app.settings import save_user_settings


def test_configured_external_python_uses_saved_settings(tmp_path, monkeypatch) -> None:
    settings_path = tmp_path / "settings.json"
    python_path = tmp_path / "Python310" / "python.exe"
    python_path.parent.mkdir(parents=True)
    python_path.write_text("fake python", encoding="utf-8")
    monkeypatch.setenv("VIDEO_NOTE_SETTINGS_FILE", str(settings_path))
    monkeypatch.delenv("VIDEO_NOTE_PYTHON_PATH", raising=False)
    save_user_settings({"external_python_path": str(python_path)})

    configured = get_configured_external_python()

    assert configured.value == str(python_path)
    assert configured.source == "settings"
    assert configured.error == ""


def test_configured_external_python_prefers_environment(tmp_path, monkeypatch) -> None:
    settings_path = tmp_path / "settings.json"
    settings_python = tmp_path / "settings-python.exe"
    env_python = tmp_path / "env-python.exe"
    settings_python.write_text("settings", encoding="utf-8")
    env_python.write_text("env", encoding="utf-8")
    monkeypatch.setenv("VIDEO_NOTE_SETTINGS_FILE", str(settings_path))
    monkeypatch.setenv("VIDEO_NOTE_PYTHON_PATH", str(env_python))
    save_user_settings({"external_python_path": str(settings_python)})

    configured = get_configured_external_python()

    assert configured.value == str(env_python)
    assert configured.source == "environment"
    assert configured.error == ""


def test_configured_external_python_reports_missing_configured_path(tmp_path, monkeypatch) -> None:
    settings_path = tmp_path / "settings.json"
    missing_python = tmp_path / "missing" / "python.exe"
    monkeypatch.setenv("VIDEO_NOTE_SETTINGS_FILE", str(settings_path))
    monkeypatch.delenv("VIDEO_NOTE_PYTHON_PATH", raising=False)
    save_user_settings({"external_python_path": str(missing_python)})

    configured = get_configured_external_python()

    assert configured.value == str(missing_python)
    assert configured.source == "settings"
    assert "does not exist" in configured.error


def test_configured_external_python_reports_missing_configured_command(monkeypatch) -> None:
    monkeypatch.setenv("VIDEO_NOTE_PYTHON_PATH", "missing-python-for-video-note")
    monkeypatch.setattr("backend.app.runtime_config.shutil.which", lambda _value: None)

    configured = get_configured_external_python()

    assert configured.value == "missing-python-for-video-note"
    assert configured.source == "environment"
    assert "was not found on PATH" in configured.error


def test_configured_external_python_reports_directory_path(tmp_path, monkeypatch) -> None:
    settings_path = tmp_path / "settings.json"
    python_dir = tmp_path / "Python310"
    python_dir.mkdir()
    monkeypatch.setenv("VIDEO_NOTE_SETTINGS_FILE", str(settings_path))
    monkeypatch.delenv("VIDEO_NOTE_PYTHON_PATH", raising=False)
    save_user_settings({"external_python_path": str(python_dir)})

    configured = get_configured_external_python()

    assert configured.value == str(python_dir)
    assert configured.source == "settings"
    assert "is not a file" in configured.error


def test_configured_model_root_uses_saved_settings(tmp_path, monkeypatch) -> None:
    settings_path = tmp_path / "settings.json"
    model_root = tmp_path / "custom-models"
    monkeypatch.setenv("VIDEO_NOTE_SETTINGS_FILE", str(settings_path))
    monkeypatch.delenv("FASTER_WHISPER_MODEL_DIR", raising=False)
    save_user_settings({"faster_whisper_model_dir": str(model_root)})

    configured = get_configured_model_root()

    assert configured.as_path() == model_root
    assert configured.source == "settings"
    assert configured.error == ""


def test_configured_model_root_prefers_environment(tmp_path, monkeypatch) -> None:
    settings_path = tmp_path / "settings.json"
    settings_model_root = tmp_path / "settings-models"
    env_model_root = tmp_path / "env-models"
    monkeypatch.setenv("VIDEO_NOTE_SETTINGS_FILE", str(settings_path))
    monkeypatch.setenv("FASTER_WHISPER_MODEL_DIR", str(env_model_root))
    save_user_settings({"faster_whisper_model_dir": str(settings_model_root)})

    configured = get_configured_model_root()

    assert configured.as_path() == env_model_root
    assert configured.source == "environment"


def test_python_package_install_args_support_user_mode(tmp_path, monkeypatch) -> None:
    settings_path = tmp_path / "settings.json"
    monkeypatch.setenv("VIDEO_NOTE_SETTINGS_FILE", str(settings_path))
    save_user_settings({"python_package_install_mode": "user"})

    assert get_python_package_install_mode() == "user"
    assert get_python_package_install_args() == ["--user"]
