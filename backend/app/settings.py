from __future__ import annotations

import json
import os
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from threading import Lock, RLock
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .atomic_io import atomic_write_json
from .models import (
    AIProtocol,
    LocalWhisperComputeType,
    LocalWhisperDevice,
    NoteLanguage,
    NoteStyle,
    PerformanceMode,
    TranscriptionLanguage,
    TranscriptionMode,
)
from .runtime_paths import get_app_data_root
from .secret_storage import (
    SecretProtectionError,
    SecretProvider,
    get_default_secret_provider,
)

OPENAI_BASE_URL = "https://api.openai.com/v1"
PythonPackageInstallMode = Literal["default", "user"]
CURRENT_SETTINGS_SCHEMA_VERSION = 2
SETTINGS_SECRET_FIELDS = ("transcription_api_key", "note_api_key")
SETTINGS_LOCK_TIMEOUT_SECONDS = 10.0
_SETTINGS_LOCKS_GUARD = Lock()
_SETTINGS_LOCKS: dict[str, RLock] = {}


class SettingsStorageError(RuntimeError):
    """Raised when the settings file cannot be read or safely updated."""


@dataclass(frozen=True)
class _LoadedSettings:
    settings: "UserSettings"
    schema_version: int
    secret_provider: str
    encrypted_secrets: dict[str, str]
    legacy_plaintext: bool = False


class UserSettings(BaseModel):
    model_config = ConfigDict(extra="ignore")

    transcription_mode: TranscriptionMode = TranscriptionMode.local_faster_whisper
    transcription_language: TranscriptionLanguage = TranscriptionLanguage.auto
    transcription_api_key: str = ""
    transcription_base_url: str = OPENAI_BASE_URL
    transcription_model: str = "small"
    local_whisper_device: LocalWhisperDevice = LocalWhisperDevice.auto
    local_whisper_compute_type: LocalWhisperComputeType = LocalWhisperComputeType.default
    performance_mode: PerformanceMode = PerformanceMode.balanced
    external_python_path: str = ""
    faster_whisper_model_dir: str = ""
    python_package_install_mode: PythonPackageInstallMode = "default"
    note_api_key: str = ""
    note_api_protocol: AIProtocol = AIProtocol.openai_chat_completions
    note_base_url: str = OPENAI_BASE_URL
    note_model: str = "gpt-5.5"
    note_language: NoteLanguage = NoteLanguage.zh
    note_style: NoteStyle = NoteStyle.detailed
    extras: str = ""
    frame_limit: int = Field(default=6, ge=1, le=24)

    @field_validator(
        "transcription_api_key",
        "transcription_base_url",
        "transcription_model",
        "external_python_path",
        "faster_whisper_model_dir",
        "note_api_key",
        "note_base_url",
        "note_model",
        "extras",
    )
    @classmethod
    def normalize_text(cls, value: str) -> str:
        return value.strip()

    @field_validator("extras")
    @classmethod
    def limit_extras(cls, value: str) -> str:
        if len(value) > 2000:
            raise ValueError("extras must be 2000 characters or fewer.")
        return value

class UserSettingsUpdate(BaseModel):
    model_config = ConfigDict(extra="ignore")

    transcription_mode: TranscriptionMode | None = None
    transcription_language: TranscriptionLanguage | None = None
    transcription_api_key: str | None = None
    transcription_base_url: str | None = None
    transcription_model: str | None = None
    local_whisper_device: LocalWhisperDevice | None = None
    local_whisper_compute_type: LocalWhisperComputeType | None = None
    performance_mode: PerformanceMode | None = None
    external_python_path: str | None = None
    faster_whisper_model_dir: str | None = None
    python_package_install_mode: PythonPackageInstallMode | None = None
    note_api_key: str | None = None
    note_api_protocol: AIProtocol | None = None
    note_base_url: str | None = None
    note_model: str | None = None
    note_language: NoteLanguage | None = None
    note_style: NoteStyle | None = None
    extras: str | None = None
    frame_limit: int | None = Field(default=None, ge=1, le=24)

    @field_validator(
        "transcription_api_key",
        "transcription_base_url",
        "transcription_model",
        "external_python_path",
        "faster_whisper_model_dir",
        "note_api_key",
        "note_base_url",
        "note_model",
        "extras",
    )
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip()

    @field_validator("extras")
    @classmethod
    def limit_optional_extras(cls, value: str | None) -> str | None:
        if value is not None and len(value) > 2000:
            raise ValueError("extras must be 2000 characters or fewer.")
        return value

def get_settings_path() -> Path:
    override = os.getenv("VIDEO_NOTE_SETTINGS_FILE", "").strip()
    if override:
        return Path(override).expanduser()
    return get_app_data_root() / "config" / "settings.json"


def get_secret_provider() -> SecretProvider:
    return get_default_secret_provider()


def load_user_settings(*, strict: bool = False) -> UserSettings:
    settings_path = get_settings_path()
    if not settings_path.exists():
        return UserSettings()
    try:
        return _load_settings_document(settings_path).settings
    except SettingsStorageError:
        if strict:
            raise
        return UserSettings()


def save_user_settings(update: UserSettings | dict[str, Any]) -> UserSettings:
    if isinstance(update, UserSettings):
        incoming = update.model_dump(mode="json")
    else:
        incoming = UserSettingsUpdate.model_validate(update).model_dump(mode="json", exclude_none=True)

    settings_path = get_settings_path()
    with _settings_write_lock(settings_path):
        loaded = (
            _load_settings_document(settings_path)
            if settings_path.exists()
            else _LoadedSettings(
                settings=UserSettings(),
                schema_version=CURRENT_SETTINGS_SCHEMA_VERSION,
                secret_provider="",
                encrypted_secrets={},
            )
        )
        current = loaded.settings.model_dump(mode="json")
        next_settings = UserSettings.model_validate({**current, **incoming})
        payload = _settings_envelope(next_settings)
        atomic_write_json(settings_path, payload)
        return next_settings


def clear_user_settings() -> UserSettings:
    settings_path = get_settings_path()
    with _settings_write_lock(settings_path):
        settings_path.unlink(missing_ok=True)
    return UserSettings()


def get_settings_storage_status() -> dict[str, Any]:
    settings_path = get_settings_path()
    provider = get_secret_provider()
    base = {
        "path": str(settings_path),
        "schema_version": CURRENT_SETTINGS_SCHEMA_VERSION,
        "secret_provider": provider.name,
        "secrets_encrypted": False,
        "error": "",
    }
    if not settings_path.exists():
        base["warning"] = _provider_storage_message(provider)
        return base
    try:
        payload = json.loads(settings_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        base["warning"] = "The local settings file is unreadable. Clear it or restore a valid copy before saving."
        base["error"] = _generic_settings_error(exc)
        return base
    if not isinstance(payload, dict):
        base["warning"] = "The local settings file has an invalid format."
        base["error"] = "Invalid settings document."
        return base
    if payload.get("schema_version") == CURRENT_SETTINGS_SCHEMA_VERSION and not _is_v2_envelope(payload):
        base["warning"] = "The encrypted local settings file has an invalid format."
        base["error"] = "Invalid encrypted settings document."
        return base
    if _is_v2_envelope(payload):
        secrets = payload.get("secrets")
        secrets = secrets if isinstance(secrets, dict) else {}
        saved_provider = str(secrets.get("provider") or "")
        encrypted = any(bool(secrets.get(field)) for field in SETTINGS_SECRET_FIELDS)
        base["secret_provider"] = saved_provider or provider.name
        base["secrets_encrypted"] = encrypted
        if encrypted and saved_provider != provider.name:
            base["warning"] = "Saved API keys use a secret provider that is unavailable in this runtime."
            base["error"] = "Saved secret provider is unavailable."
        elif encrypted:
            base["warning"] = _encrypted_storage_message(saved_provider)
        else:
            base["warning"] = _provider_storage_message(provider)
        return base

    contains_plaintext_secrets = any(bool(payload.get(field)) for field in SETTINGS_SECRET_FIELDS)
    base["schema_version"] = 1
    if contains_plaintext_secrets:
        base["secret_provider"] = "plaintext_legacy"
        base["warning"] = "Legacy plaintext API keys were detected and will be encrypted on the next save."
    else:
        base["warning"] = "Legacy settings will be upgraded to the encrypted schema on the next save."
    return base


def _load_settings_document(settings_path: Path) -> _LoadedSettings:
    try:
        payload = json.loads(settings_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SettingsStorageError(_generic_settings_error(exc)) from exc
    if not isinstance(payload, dict):
        raise SettingsStorageError("Invalid settings document.")
    if payload.get("schema_version") == CURRENT_SETTINGS_SCHEMA_VERSION and not _is_v2_envelope(payload):
        raise SettingsStorageError("Invalid encrypted settings document.")
    if not _is_v2_envelope(payload):
        if "schema_version" in payload:
            try:
                schema_version = int(payload["schema_version"])
            except (TypeError, ValueError) as exc:
                raise SettingsStorageError("Invalid settings schema version.") from exc
            if schema_version > CURRENT_SETTINGS_SCHEMA_VERSION:
                raise SettingsStorageError(
                    f"Settings schema version {schema_version} is newer than this application supports."
                )
        try:
            settings = UserSettings.model_validate(payload)
        except ValueError as exc:
            raise SettingsStorageError("The legacy settings document is invalid.") from exc
        return _LoadedSettings(
            settings=settings,
            schema_version=1,
            secret_provider="plaintext_legacy",
            encrypted_secrets={},
            legacy_plaintext=True,
        )

    raw_settings = payload.get("settings")
    raw_secrets = payload.get("secrets")
    if not isinstance(raw_settings, dict) or not isinstance(raw_secrets, dict):
        raise SettingsStorageError("Invalid encrypted settings document.")
    provider = get_secret_provider()
    saved_provider = str(raw_secrets.get("provider") or "")
    encrypted_secrets = {
        field: str(raw_secrets.get(field) or "")
        for field in SETTINGS_SECRET_FIELDS
    }
    if any(encrypted_secrets.values()) and saved_provider != provider.name:
        raise SettingsStorageError("The saved API keys use an unavailable secret provider.")
    decrypted: dict[str, str] = {}
    try:
        for field, value in encrypted_secrets.items():
            decrypted[field] = provider.unprotect(value)
    except SecretProtectionError as exc:
        raise SettingsStorageError("The saved API keys could not be decrypted for the current user.") from exc
    try:
        settings = UserSettings.model_validate({**raw_settings, **decrypted})
    except ValueError as exc:
        raise SettingsStorageError("The encrypted settings document is invalid.") from exc
    return _LoadedSettings(
        settings=settings,
        schema_version=CURRENT_SETTINGS_SCHEMA_VERSION,
        secret_provider=saved_provider,
        encrypted_secrets=encrypted_secrets,
    )


def _settings_envelope(settings: UserSettings) -> dict[str, Any]:
    provider = get_secret_provider()
    raw_settings = settings.model_dump(mode="json")
    raw_secrets = {
        field: str(raw_settings.pop(field, "") or "")
        for field in SETTINGS_SECRET_FIELDS
    }
    if any(raw_secrets.values()) and not provider.available:
        raise SettingsStorageError(
            "Secure local API key storage is unavailable. API keys were not written to disk."
        )
    try:
        encrypted = {
            field: provider.protect(value)
            for field, value in raw_secrets.items()
        }
    except SecretProtectionError as exc:
        raise SettingsStorageError("API keys could not be encrypted for local storage.") from exc
    return {
        "schema_version": CURRENT_SETTINGS_SCHEMA_VERSION,
        "settings": raw_settings,
        "secrets": {
            "provider": provider.name,
            **encrypted,
        },
    }


def _is_v2_envelope(payload: dict[str, Any]) -> bool:
    return (
        payload.get("schema_version") == CURRENT_SETTINGS_SCHEMA_VERSION
        and "settings" in payload
        and "secrets" in payload
    )


def _provider_storage_message(provider: SecretProvider) -> str:
    if provider.available and provider.name == "windows_dpapi":
        return "API keys are encrypted for the current Windows user with DPAPI when settings are saved."
    return "Secure API key persistence is unavailable in this runtime; non-secret settings can still be saved."


def _encrypted_storage_message(provider_name: str) -> str:
    if provider_name == "windows_dpapi":
        return "Saved API keys are encrypted for the current Windows user with DPAPI."
    return f"Saved API keys are encrypted with the configured {provider_name or 'local'} secret provider."


def _generic_settings_error(exc: Exception) -> str:
    if isinstance(exc, json.JSONDecodeError):
        return "The local settings file contains invalid JSON."
    return "The local settings file could not be read."


def _thread_lock_for(settings_path: Path) -> RLock:
    key = str(settings_path.resolve()).casefold()
    with _SETTINGS_LOCKS_GUARD:
        return _SETTINGS_LOCKS.setdefault(key, RLock())


@contextmanager
def _settings_write_lock(settings_path: Path):
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    thread_lock = _thread_lock_for(settings_path)
    with thread_lock:
        lock_path = settings_path.with_name(f".{settings_path.name}.lock")
        with lock_path.open("a+b") as stream:
            stream.seek(0, os.SEEK_END)
            if stream.tell() == 0:
                stream.write(b"\0")
                stream.flush()
            stream.seek(0)
            _lock_file(stream)
            try:
                yield
            finally:
                _unlock_file(stream)


def _lock_file(stream) -> None:
    if os.name == "nt":
        import msvcrt

        deadline = time.monotonic() + SETTINGS_LOCK_TIMEOUT_SECONDS
        while True:
            try:
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                return
            except OSError as exc:
                if time.monotonic() >= deadline:
                    raise SettingsStorageError("Timed out waiting for the local settings lock.") from exc
                time.sleep(0.05)
    else:
        import fcntl

        fcntl.flock(stream.fileno(), fcntl.LOCK_EX)


def _unlock_file(stream) -> None:
    if os.name == "nt":
        import msvcrt

        stream.seek(0)
        msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
    else:
        import fcntl

        fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
