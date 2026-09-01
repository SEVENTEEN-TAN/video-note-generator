from __future__ import annotations

import pytest
from pydantic import ValidationError

from backend.app.models import (
    JobConfig,
    NoteGenerationConfig,
    NoteLanguage,
    NotePreferences,
    NoteStyle,
    TranscriptionConfig,
    TranscriptionMode,
)


def test_local_transcription_config_does_not_require_api_key() -> None:
    config = TranscriptionConfig(
        transcription_mode=TranscriptionMode.local_faster_whisper,
        transcription_model="small",
        original_filename="input.mp4",
    )

    assert config.transcription_api_key == ""
    assert not hasattr(config, "note_api_key")


def test_remote_transcription_config_requires_api_key() -> None:
    with pytest.raises(ValidationError, match="Transcription API Key"):
        TranscriptionConfig(
            transcription_mode=TranscriptionMode.audio_transcriptions,
            transcription_model="whisper-1",
            original_filename="input.mp4",
        )


def test_note_preferences_do_not_require_credentials() -> None:
    preferences = NotePreferences(
        note_base_url="",
        note_model="",
        note_language=NoteLanguage.zh,
        original_filename="input.mp4",
    )

    assert preferences.note_base_url == ""
    assert preferences.note_model == ""
    assert not hasattr(preferences, "note_api_key")


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("note_api_key", ""),
        ("note_base_url", ""),
        ("note_model", ""),
    ],
)
def test_note_generation_config_requires_service_fields(field: str, value: str) -> None:
    payload = {
        "note_api_key": "note-key",
        "note_base_url": "https://api.example.test/v1",
        "note_model": "note-model",
        "note_language": NoteLanguage.zh,
        "original_filename": "input.mp4",
    }
    payload[field] = value

    with pytest.raises(ValidationError):
        NoteGenerationConfig(**payload)


def test_legacy_job_config_adapters_expose_only_stage_fields() -> None:
    legacy = JobConfig(
        transcription_mode=TranscriptionMode.local_faster_whisper,
        transcription_model="small",
        note_api_key="note-key",
        note_base_url="https://api.example.test/v1",
        note_model="note-model",
        note_language=NoteLanguage.zh,
        note_style=NoteStyle.detailed,
        original_filename="input.mp4",
    )

    transcription = legacy.for_transcription()
    note_generation = legacy.for_note_generation()

    assert isinstance(transcription, TranscriptionConfig)
    assert not hasattr(transcription, "note_api_key")
    assert isinstance(note_generation, NoteGenerationConfig)
    assert not hasattr(note_generation, "transcription_model")
