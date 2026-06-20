from __future__ import annotations

from backend.app.models import JobConfig, NoteLanguage, TranscriptionMode
from backend.app.settings import UserSettings, UserSettingsUpdate


def test_frame_limit_allows_twenty_four() -> None:
    config = JobConfig(
        transcription_mode=TranscriptionMode.local_faster_whisper,
        transcription_api_key="",
        transcription_base_url="",
        transcription_model="small",
        note_api_key="note-key",
        note_base_url="https://api.openai.com/v1",
        note_model="gpt-5.5",
        note_language=NoteLanguage.zh,
        original_filename="input.mp4",
        frame_limit=24,
    )

    assert config.frame_limit == 24
    assert UserSettings(frame_limit=24).frame_limit == 24
    assert UserSettingsUpdate(frame_limit=24).frame_limit == 24
