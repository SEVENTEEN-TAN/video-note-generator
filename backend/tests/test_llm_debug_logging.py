from __future__ import annotations

from types import SimpleNamespace

import pytest

from backend.app import llm
from backend.app.llm import LLMError
from backend.app.models import JobConfig, NoteLanguage, TranscriptionMode
from backend.app.task_debug_log import TaskDebugLog


def test_call_note_model_writes_raw_responses_and_json_error_context(tmp_path, monkeypatch) -> None:
    responses = [
        '{\n  "title": "Demo"\n  "summary": "missing comma"\n}',
        '{\n  "title": "Demo"\n  "summary": "still missing comma"\n}',
    ]

    class FakeCompletions:
        def create(self, **_kwargs):
            text = responses.pop(0)
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=text))])

    fake_client = SimpleNamespace(chat=SimpleNamespace(completions=FakeCompletions()))
    monkeypatch.setattr(llm, "make_client", lambda *_args, **_kwargs: fake_client)

    config = JobConfig(
        transcription_mode=TranscriptionMode.local_faster_whisper,
        note_api_key="note-key",
        note_language=NoteLanguage.en,
        original_filename="demo.mp4",
    )
    debug_log = TaskDebugLog(tmp_path)

    with pytest.raises(LLMError):
        llm.call_note_model(
            config,
            [{"role": "user", "content": "make JSON"}],
            debug_log=debug_log,
            debug_context="note",
        )

    assert (tmp_path / "debug" / "note-model-response-attempt-1.txt").read_text(encoding="utf-8").startswith("{")
    assert (tmp_path / "debug" / "note-model-response-attempt-2.txt").read_text(encoding="utf-8").startswith("{")
    log_text = (tmp_path / "debug.log").read_text(encoding="utf-8")
    assert "note_model_call" in log_text
    assert "note-model-response-attempt-1.txt" in log_text
    assert "error_context" in log_text
    assert "missing comma" in log_text
