from __future__ import annotations

import json

from backend.app.models import NoteLanguage, NoteStyle, TranscriptionMode
from backend.app.settings import clear_user_settings, get_settings_path, load_user_settings, save_user_settings


def test_user_settings_roundtrip_persists_keys_and_models(tmp_path, monkeypatch) -> None:
    settings_path = tmp_path / "settings.json"
    monkeypatch.setenv("VIDEO_NOTE_SETTINGS_FILE", str(settings_path))

    saved = save_user_settings(
        {
            "transcription_mode": "audio_transcriptions",
            "transcription_api_key": "transcription-secret",
            "transcription_base_url": "https://api.example.com/v1",
            "transcription_model": "whisper-1",
            "local_whisper_device": "cuda",
            "local_whisper_compute_type": "float16",
            "note_api_key": "note-secret",
            "note_base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
            "note_model": "qwen-plus",
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
    assert loaded.transcription_api_key == "transcription-secret"
    assert loaded.local_whisper_device == "cuda"
    assert loaded.local_whisper_compute_type == "float16"
    assert loaded.note_api_key == "note-secret"
    assert loaded.note_model == "qwen-plus"
    assert loaded.note_language == NoteLanguage.follow
    assert loaded.note_style == NoteStyle.tutorial
    assert loaded.frame_limit == 8
    assert json.loads(settings_path.read_text(encoding="utf-8"))["note_api_key"] == "note-secret"


def test_clear_user_settings_removes_file_and_returns_defaults(tmp_path, monkeypatch) -> None:
    settings_path = tmp_path / "settings.json"
    monkeypatch.setenv("VIDEO_NOTE_SETTINGS_FILE", str(settings_path))
    save_user_settings({"note_api_key": "note-secret", "note_model": "qwen-plus"})

    cleared = clear_user_settings()

    assert not settings_path.exists()
    assert cleared.note_api_key == ""
    assert cleared.note_model == "gpt-5.5"
    assert cleared.transcription_mode == TranscriptionMode.local_faster_whisper
    assert cleared.transcription_model == "small"
    assert cleared.local_whisper_device == "cpu"
    assert cleared.local_whisper_compute_type == "int8"
