from __future__ import annotations

import base64
import json
import multiprocessing
import os
from concurrent.futures import ThreadPoolExecutor

import pytest

from backend.app import settings as settings_module
from backend.app.models import (
    NoteLanguage,
    NoteStyle,
    PerformanceMode,
    TranscriptionLanguage,
    TranscriptionMode,
)
from backend.app.secret_storage import SecretProtectionError, WindowsDpapiSecretProvider
from backend.app.settings import (
    CURRENT_SETTINGS_SCHEMA_VERSION,
    SettingsStorageError,
    clear_user_settings,
    get_settings_path,
    get_settings_storage_status,
    load_user_settings,
    save_user_settings,
)


class FakeSecretProvider:
    name = "test_secret_provider"
    available = True

    def protect(self, value: str) -> str:
        if not value:
            return ""
        return base64.b64encode(f"protected:{value}".encode()).decode()

    def unprotect(self, value: str) -> str:
        if not value:
            return ""
        try:
            decoded = base64.b64decode(value, validate=True).decode()
        except (ValueError, UnicodeDecodeError) as exc:
            raise SecretProtectionError("invalid test ciphertext") from exc
        if not decoded.startswith("protected:"):
            raise SecretProtectionError("invalid test ciphertext")
        return decoded.removeprefix("protected:")


def _save_settings_in_process(settings_path: str, update: dict, ready, start, result) -> None:
    os.environ["VIDEO_NOTE_SETTINGS_FILE"] = settings_path
    ready.put(True)
    if not start.wait(timeout=5):
        result.put("start timeout")
        return
    try:
        save_user_settings(update)
    except Exception as exc:
        result.put(f"{type(exc).__name__}: {exc}")
    else:
        result.put("")


@pytest.fixture(autouse=True)
def use_portable_secret_provider(monkeypatch):
    monkeypatch.setattr(settings_module, "get_secret_provider", lambda: FakeSecretProvider())


def test_user_settings_roundtrip_persists_keys_and_models(tmp_path, monkeypatch) -> None:
    settings_path = tmp_path / "settings.json"
    monkeypatch.setenv("VIDEO_NOTE_SETTINGS_FILE", str(settings_path))

    saved = save_user_settings(
        {
            "transcription_mode": "audio_transcriptions",
            "transcription_language": "zh",
            "transcription_api_key": "transcription-secret",
            "transcription_base_url": "https://api.example.com/v1",
            "transcription_model": "whisper-1",
            "local_whisper_device": "cuda",
            "local_whisper_compute_type": "float16",
            "performance_mode": "accurate",
            "note_api_key": "note-secret",
            "note_base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
            "note_model": "qwen-plus",
            "note_thinking_enabled": True,
            "note_context_window_tokens": 256000,
            "note_max_output_tokens": 32768,
            "note_language": "follow",
            "note_style": "tutorial",
            "extras": "Keep formulas intact.",
            "frame_limit": 8,
        }
    )

    loaded = load_user_settings()

    assert get_settings_path() == settings_path
    assert saved == loaded
    assert loaded.transcription_mode == TranscriptionMode.audio_transcriptions
    assert loaded.transcription_language == TranscriptionLanguage.zh
    assert loaded.transcription_api_key == "transcription-secret"
    assert loaded.local_whisper_device == "cuda"
    assert loaded.local_whisper_compute_type == "float16"
    assert loaded.performance_mode == PerformanceMode.accurate
    assert loaded.note_api_key == "note-secret"
    assert loaded.note_model == "qwen-plus"
    assert loaded.note_thinking_enabled is True
    assert loaded.note_context_window_tokens == 256000
    assert loaded.note_max_output_tokens == 32768
    assert loaded.note_language == NoteLanguage.follow
    assert loaded.note_style == NoteStyle.tutorial
    assert loaded.frame_limit == 8
    payload = json.loads(settings_path.read_text(encoding="utf-8"))
    serialized = settings_path.read_text(encoding="utf-8")
    assert payload["schema_version"] == CURRENT_SETTINGS_SCHEMA_VERSION
    assert payload["settings"]["transcription_language"] == "zh"
    assert payload["settings"]["note_thinking_enabled"] is True
    assert payload["settings"]["note_context_window_tokens"] == 256000
    assert payload["settings"]["note_max_output_tokens"] == 32768
    assert payload["secrets"]["provider"] == "test_secret_provider"
    assert payload["secrets"]["note_api_key"]
    assert "note-secret" not in serialized
    assert "transcription-secret" not in serialized


def test_clear_user_settings_removes_file_and_returns_defaults(tmp_path, monkeypatch) -> None:
    settings_path = tmp_path / "settings.json"
    monkeypatch.setenv("VIDEO_NOTE_SETTINGS_FILE", str(settings_path))
    save_user_settings({"note_api_key": "note-secret", "note_model": "qwen-plus"})

    cleared = clear_user_settings()

    assert not settings_path.exists()
    assert cleared.note_api_key == ""
    assert cleared.note_model == "gpt-5.5"
    assert cleared.transcription_mode == TranscriptionMode.local_faster_whisper
    assert cleared.transcription_language == TranscriptionLanguage.auto
    assert cleared.transcription_model == "small"
    assert cleared.local_whisper_device == "auto"
    assert cleared.local_whisper_compute_type == "default"
    assert cleared.performance_mode == PerformanceMode.balanced


def test_user_settings_reject_output_budget_that_consumes_context() -> None:
    with pytest.raises(ValueError, match="leave at least 2048 tokens"):
        settings_module.UserSettings(
            note_context_window_tokens=8192,
            note_max_output_tokens=7000,
        )


def test_old_settings_without_performance_mode_default_to_balanced(tmp_path, monkeypatch) -> None:
    settings_path = tmp_path / "settings.json"
    monkeypatch.setenv("VIDEO_NOTE_SETTINGS_FILE", str(settings_path))
    settings_path.write_text('{"transcription_model": "small"}', encoding="utf-8")

    loaded = load_user_settings()

    assert loaded.performance_mode == PerformanceMode.balanced


def test_user_settings_roundtrip_persists_runtime_path_overrides(tmp_path, monkeypatch) -> None:
    settings_path = tmp_path / "settings.json"
    python_path = tmp_path / "Python310" / "python.exe"
    model_dir = tmp_path / "custom-models"
    python_path.parent.mkdir(parents=True)
    python_path.write_text("fake python", encoding="utf-8")
    monkeypatch.setenv("VIDEO_NOTE_SETTINGS_FILE", str(settings_path))

    saved = save_user_settings(
        {
            "external_python_path": str(python_path),
            "faster_whisper_model_dir": str(model_dir),
            "python_package_install_mode": "user",
        }
    )

    loaded = load_user_settings()
    payload = json.loads(settings_path.read_text(encoding="utf-8"))

    assert saved.external_python_path == str(python_path)
    assert saved.faster_whisper_model_dir == str(model_dir)
    assert saved.python_package_install_mode == "user"
    assert loaded == saved
    assert payload["settings"]["external_python_path"] == str(python_path)
    assert payload["settings"]["faster_whisper_model_dir"] == str(model_dir)
    assert payload["settings"]["python_package_install_mode"] == "user"


def test_legacy_plaintext_settings_migrate_on_next_save(tmp_path, monkeypatch) -> None:
    settings_path = tmp_path / "settings.json"
    monkeypatch.setenv("VIDEO_NOTE_SETTINGS_FILE", str(settings_path))
    settings_path.write_text(
        json.dumps(
            {
                "transcription_mode": "audio_transcriptions",
                "transcription_language": "en",
                "transcription_api_key": "legacy-transcription-secret",
                "note_api_key": "legacy-note-secret",
                "note_model": "legacy-model",
            }
        ),
        encoding="utf-8",
    )

    legacy = load_user_settings(strict=True)
    status_before = get_settings_storage_status()
    migrated = save_user_settings({"note_model": "new-model"})
    payload = json.loads(settings_path.read_text(encoding="utf-8"))
    serialized = settings_path.read_text(encoding="utf-8")

    assert legacy.transcription_language == TranscriptionLanguage.en
    assert legacy.note_api_key == "legacy-note-secret"
    assert status_before["schema_version"] == 1
    assert status_before["secret_provider"] == "plaintext_legacy"
    assert migrated.note_model == "new-model"
    assert migrated.note_api_key == "legacy-note-secret"
    assert payload["schema_version"] == CURRENT_SETTINGS_SCHEMA_VERSION
    assert payload["settings"]["transcription_language"] == "en"
    assert payload["secrets"]["provider"] == "test_secret_provider"
    assert "legacy-note-secret" not in serialized
    assert "legacy-transcription-secret" not in serialized


def test_concurrent_partial_updates_preserve_both_changes(tmp_path, monkeypatch) -> None:
    settings_path = tmp_path / "settings.json"
    monkeypatch.setenv("VIDEO_NOTE_SETTINGS_FILE", str(settings_path))
    save_user_settings({"note_api_key": "secret"})

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(save_user_settings, {"note_model": "parallel-model"}),
            executor.submit(save_user_settings, {"extras": "parallel extras"}),
        ]
        for future in futures:
            future.result(timeout=5)

    loaded = load_user_settings(strict=True)
    payload = json.loads(settings_path.read_text(encoding="utf-8"))

    assert loaded.note_model == "parallel-model"
    assert loaded.extras == "parallel extras"
    assert loaded.note_api_key == "secret"
    assert payload["schema_version"] == CURRENT_SETTINGS_SCHEMA_VERSION


def test_cross_process_partial_updates_use_one_settings_lock(tmp_path, monkeypatch) -> None:
    settings_path = tmp_path / "settings.json"
    monkeypatch.setenv("VIDEO_NOTE_SETTINGS_FILE", str(settings_path))
    save_user_settings({"note_model": "initial"})
    context = multiprocessing.get_context("spawn")
    ready = context.Queue()
    start = context.Event()
    result = context.Queue()
    processes = [
        context.Process(
            target=_save_settings_in_process,
            args=(str(settings_path), {"note_model": "process-model"}, ready, start, result),
        ),
        context.Process(
            target=_save_settings_in_process,
            args=(str(settings_path), {"extras": "process extras"}, ready, start, result),
        ),
    ]
    for process in processes:
        process.start()
    assert ready.get(timeout=5) is True
    assert ready.get(timeout=5) is True
    start.set()
    errors = [result.get(timeout=10), result.get(timeout=10)]
    for process in processes:
        process.join(timeout=10)

    assert errors == ["", ""]
    assert all(process.exitcode == 0 for process in processes)
    loaded = load_user_settings(strict=True)
    assert loaded.note_model == "process-model"
    assert loaded.extras == "process extras"


def test_corrupt_ciphertext_is_not_replaced_by_partial_save(tmp_path, monkeypatch) -> None:
    settings_path = tmp_path / "settings.json"
    monkeypatch.setenv("VIDEO_NOTE_SETTINGS_FILE", str(settings_path))
    save_user_settings({"note_api_key": "secret", "note_model": "model-before"})
    payload = json.loads(settings_path.read_text(encoding="utf-8"))
    payload["secrets"]["note_api_key"] = "not-valid-ciphertext"
    settings_path.write_text(json.dumps(payload), encoding="utf-8")
    before = settings_path.read_bytes()

    with pytest.raises(SettingsStorageError, match="could not be decrypted"):
        load_user_settings(strict=True)
    with pytest.raises(SettingsStorageError, match="could not be decrypted"):
        save_user_settings({"note_model": "model-after"})

    assert settings_path.read_bytes() == before
    assert "secret" not in str(get_settings_storage_status()["error"]).lower()


def test_invalid_settings_return_defaults_non_strict_and_raise_strict(tmp_path, monkeypatch) -> None:
    settings_path = tmp_path / "settings.json"
    monkeypatch.setenv("VIDEO_NOTE_SETTINGS_FILE", str(settings_path))
    settings_path.write_text("{invalid", encoding="utf-8")

    assert load_user_settings().note_model == "gpt-5.5"
    with pytest.raises(SettingsStorageError, match="invalid JSON"):
        load_user_settings(strict=True)
    with pytest.raises(SettingsStorageError, match="invalid JSON"):
        save_user_settings({"note_model": "must-not-overwrite"})
    assert settings_path.read_text(encoding="utf-8") == "{invalid"


def test_malformed_schema_v2_is_not_treated_as_legacy_settings(tmp_path, monkeypatch) -> None:
    settings_path = tmp_path / "settings.json"
    monkeypatch.setenv("VIDEO_NOTE_SETTINGS_FILE", str(settings_path))
    settings_path.write_text(
        json.dumps({"schema_version": CURRENT_SETTINGS_SCHEMA_VERSION, "settings": {}}),
        encoding="utf-8",
    )

    with pytest.raises(SettingsStorageError, match="Invalid encrypted settings document"):
        load_user_settings(strict=True)
    with pytest.raises(SettingsStorageError, match="Invalid encrypted settings document"):
        save_user_settings({"note_model": "must-not-overwrite"})
    status = get_settings_storage_status()
    assert status["schema_version"] == CURRENT_SETTINGS_SCHEMA_VERSION
    assert status["error"] == "Invalid encrypted settings document."


@pytest.mark.skipif(os.name != "nt", reason="Windows DPAPI integration")
def test_windows_dpapi_roundtrip_uses_current_user_scope() -> None:
    provider = WindowsDpapiSecretProvider()

    ciphertext = provider.protect("dpapi-secret")

    assert ciphertext
    assert "dpapi-secret" not in ciphertext
    assert provider.unprotect(ciphertext) == "dpapi-secret"
