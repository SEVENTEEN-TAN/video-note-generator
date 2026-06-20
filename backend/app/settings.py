from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .models import NoteLanguage, NoteStyle, TranscriptionMode
from .runtime_paths import get_app_data_root

OPENAI_BASE_URL = "https://api.openai.com/v1"


class UserSettings(BaseModel):
    model_config = ConfigDict(extra="ignore")

    transcription_mode: TranscriptionMode = TranscriptionMode.local_faster_whisper
    transcription_api_key: str = ""
    transcription_base_url: str = OPENAI_BASE_URL
    transcription_model: str = "small"
    local_whisper_device: str = "cpu"
    local_whisper_compute_type: str = "int8"
    note_api_key: str = ""
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
        "local_whisper_device",
        "local_whisper_compute_type",
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

    @field_validator("local_whisper_device")
    @classmethod
    def validate_local_whisper_device(cls, value: str) -> str:
        if value not in {"auto", "cpu", "cuda"}:
            raise ValueError("local_whisper_device must be auto, cpu, or cuda.")
        return value

    @field_validator("local_whisper_compute_type")
    @classmethod
    def validate_local_whisper_compute_type(cls, value: str) -> str:
        if value not in {"default", "int8", "int8_float16", "float16", "float32"}:
            raise ValueError("local_whisper_compute_type is not supported.")
        return value


class UserSettingsUpdate(BaseModel):
    model_config = ConfigDict(extra="ignore")

    transcription_mode: TranscriptionMode | None = None
    transcription_api_key: str | None = None
    transcription_base_url: str | None = None
    transcription_model: str | None = None
    local_whisper_device: str | None = None
    local_whisper_compute_type: str | None = None
    note_api_key: str | None = None
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
        "local_whisper_device",
        "local_whisper_compute_type",
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

    @field_validator("local_whisper_device")
    @classmethod
    def validate_optional_local_whisper_device(cls, value: str | None) -> str | None:
        if value is not None and value not in {"auto", "cpu", "cuda"}:
            raise ValueError("local_whisper_device must be auto, cpu, or cuda.")
        return value

    @field_validator("local_whisper_compute_type")
    @classmethod
    def validate_optional_local_whisper_compute_type(cls, value: str | None) -> str | None:
        if value is not None and value not in {"default", "int8", "int8_float16", "float16", "float32"}:
            raise ValueError("local_whisper_compute_type is not supported.")
        return value


def get_settings_path() -> Path:
    override = os.getenv("VIDEO_NOTE_SETTINGS_FILE", "").strip()
    if override:
        return Path(override).expanduser()
    return get_app_data_root() / "config" / "settings.json"


def load_user_settings() -> UserSettings:
    settings_path = get_settings_path()
    if not settings_path.exists():
        return UserSettings()
    try:
        return UserSettings.model_validate(json.loads(settings_path.read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError, ValueError):
        return UserSettings()


def save_user_settings(update: UserSettings | dict[str, Any]) -> UserSettings:
    current = load_user_settings().model_dump(mode="json")
    if isinstance(update, UserSettings):
        incoming = update.model_dump(mode="json")
    else:
        incoming = UserSettingsUpdate.model_validate(update).model_dump(mode="json", exclude_none=True)
    next_settings = UserSettings.model_validate({**current, **incoming})

    settings_path = get_settings_path()
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = settings_path.with_suffix(f"{settings_path.suffix}.tmp")
    temp_path.write_text(
        json.dumps(next_settings.model_dump(mode="json"), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    temp_path.replace(settings_path)
    return next_settings


def clear_user_settings() -> UserSettings:
    settings_path = get_settings_path()
    if settings_path.exists():
        settings_path.unlink()
    return UserSettings()
