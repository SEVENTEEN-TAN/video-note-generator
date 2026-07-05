from __future__ import annotations

import json
from types import SimpleNamespace

import httpx
import pytest
from openai import AuthenticationError, BadRequestError

from backend.app import llm
from backend.app.llm import LLMError
from backend.app.models import JobConfig, NoteLanguage, TranscriptionMode
from backend.app.task_debug_log import TaskDebugLog


def test_note_model_client_uses_timeout_and_no_sdk_retries(monkeypatch) -> None:
    calls: list[dict] = []

    class FakeOpenAI:
        def __init__(self, **kwargs):
            calls.append(kwargs)

    monkeypatch.setattr(llm, "OpenAI", FakeOpenAI)

    llm.make_client("note-key", "https://example.test/v1")
    llm.make_client("note-key", "")

    assert calls == [
        {
            "api_key": "note-key",
            "base_url": "https://example.test/v1",
            "timeout": 60.0,
            "max_retries": 0,
        },
        {
            "api_key": "note-key",
            "timeout": 60.0,
            "max_retries": 0,
        },
    ]


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


def test_call_note_model_retry_prompt_includes_json_error_details(monkeypatch) -> None:
    responses = [
        '{\n  "title": "Demo"\n  "summary": "missing comma"\n}',
        '{"title":"Demo","summary":"fixed","chapters":[],"key_moments":[]}',
    ]
    calls: list[dict] = []

    class FakeCompletions:
        def create(self, **kwargs):
            calls.append(kwargs)
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

    draft = llm.call_note_model(config, [{"role": "user", "content": "make JSON"}])

    retry_prompt = calls[1]["messages"][-1]["content"]
    assert draft.summary == "fixed"
    assert "JSON parse error" in retry_prompt
    assert "Expecting ',' delimiter" in retry_prompt
    assert "line 3" in retry_prompt
    assert "missing comma" in retry_prompt


def test_call_note_model_logs_response_finish_reason(tmp_path, monkeypatch) -> None:
    text = '{"title":"Demo","summary":"ok","chapters":[],"key_moments":[]}'

    class FakeCompletions:
        def create(self, **_kwargs):
            return SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        finish_reason="length",
                        message=SimpleNamespace(content=text),
                    )
                ]
            )

    fake_client = SimpleNamespace(chat=SimpleNamespace(completions=FakeCompletions()))
    monkeypatch.setattr(llm, "make_client", lambda *_args, **_kwargs: fake_client)

    config = JobConfig(
        transcription_mode=TranscriptionMode.local_faster_whisper,
        note_api_key="note-key",
        note_language=NoteLanguage.en,
        original_filename="demo.mp4",
    )
    debug_log = TaskDebugLog(tmp_path)

    draft = llm.call_note_model(
        config,
        [{"role": "user", "content": "make JSON"}],
        debug_log=debug_log,
        debug_context="note",
    )

    records = [
        json.loads(line)
        for line in (tmp_path / "debug.log").read_text(encoding="utf-8").splitlines()
    ]
    response_event = next(record for record in records if record["message"] == "response_received")
    assert draft.title == "Demo"
    assert response_event["details"]["finish_reason"] == "length"


def test_call_note_model_converts_content_filter_finish_reason_to_llm_error(tmp_path, monkeypatch) -> None:
    call_count = 0

    class FakeCompletions:
        def create(self, **_kwargs):
            nonlocal call_count
            call_count += 1
            return SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        finish_reason="content_filter",
                        message=SimpleNamespace(content=""),
                    )
                ]
            )

    fake_client = SimpleNamespace(chat=SimpleNamespace(completions=FakeCompletions()))
    monkeypatch.setattr(llm, "make_client", lambda *_args, **_kwargs: fake_client)

    config = JobConfig(
        transcription_mode=TranscriptionMode.local_faster_whisper,
        note_api_key="note-key",
        note_language=NoteLanguage.en,
        original_filename="demo.mp4",
    )
    debug_log = TaskDebugLog(tmp_path)

    with pytest.raises(LLMError, match="finish_reason=content_filter"):
        llm.call_note_model(
            config,
            [{"role": "user", "content": "make JSON"}],
            debug_log=debug_log,
            debug_context="note-chunk-1-of-2",
        )

    records = [
        json.loads(line)
        for line in (tmp_path / "debug.log").read_text(encoding="utf-8").splitlines()
    ]
    response_event = next(record for record in records if record["message"] == "response_received")
    assert call_count == 1
    assert response_event["details"]["finish_reason"] == "content_filter"
    assert not any(record["message"] == "invalid_json" for record in records)


def test_call_note_model_converts_content_policy_bad_request_to_llm_error(monkeypatch) -> None:
    body = {
        "error": {
            "code": "content_policy_violation",
            "message": "This request has been flagged by moderation.",
            "type": "invalid_request_error",
        }
    }
    response = httpx.Response(
        400,
        request=httpx.Request("POST", "https://example.test/chat/completions"),
        json=body,
    )
    error = BadRequestError("Error code: 400 - content_policy_violation", response=response, body=body)

    class FakeCompletions:
        def create(self, **_kwargs):
            raise error

    fake_client = SimpleNamespace(chat=SimpleNamespace(completions=FakeCompletions()))
    monkeypatch.setattr(llm, "make_client", lambda *_args, **_kwargs: fake_client)

    config = JobConfig(
        transcription_mode=TranscriptionMode.local_faster_whisper,
        note_api_key="note-key",
        note_language=NoteLanguage.en,
        original_filename="demo.mp4",
    )

    with pytest.raises(LLMError, match="content_policy_violation"):
        llm.call_note_model(config, [{"role": "user", "content": "make JSON"}])


def test_call_note_model_logs_api_error_details_for_bad_request(tmp_path, monkeypatch) -> None:
    body = {
        "error": {
            "code": "content_policy_violation",
            "message": "This request has been flagged by moderation.",
            "type": "invalid_request_error",
        },
        "api_key": "secret-note-key",
    }
    response = httpx.Response(
        400,
        request=httpx.Request("POST", "https://example.test/chat/completions"),
        json=body,
    )
    error = BadRequestError("Error code: 400 - content_policy_violation", response=response, body=body)

    class FakeCompletions:
        def create(self, **_kwargs):
            raise error

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
            debug_context="note-chunk-1-of-2",
        )

    records = [
        json.loads(line)
        for line in (tmp_path / "debug.log").read_text(encoding="utf-8").splitlines()
    ]
    api_error = next(record for record in records if record["message"] == "api_error")
    assert api_error["stage"] == "note_model_call"
    assert api_error["details"]["context"] == "note-chunk-1-of-2"
    assert api_error["details"]["attempt"] == 1
    assert api_error["details"]["exception_type"] == "BadRequestError"
    assert api_error["details"]["status_code"] == 400
    assert api_error["details"]["body"]["error"]["code"] == "content_policy_violation"
    assert api_error["details"]["body"]["api_key"] == "[REDACTED]"


def test_call_note_model_logs_api_error_details_for_authentication_error(tmp_path, monkeypatch) -> None:
    body = {
        "error": {
            "message": "invalid token",
            "type": "unauthorized_error",
        },
        "api_key": "secret-note-key",
    }
    response = httpx.Response(
        401,
        request=httpx.Request("POST", "https://example.test/chat/completions"),
        json=body,
    )
    error = AuthenticationError("Error code: 401 - invalid token", response=response, body=body)

    class FakeCompletions:
        def create(self, **_kwargs):
            raise error

    fake_client = SimpleNamespace(chat=SimpleNamespace(completions=FakeCompletions()))
    monkeypatch.setattr(llm, "make_client", lambda *_args, **_kwargs: fake_client)

    config = JobConfig(
        transcription_mode=TranscriptionMode.local_faster_whisper,
        note_api_key="note-key",
        note_language=NoteLanguage.en,
        original_filename="demo.mp4",
    )
    debug_log = TaskDebugLog(tmp_path)

    with pytest.raises(AuthenticationError):
        llm.call_note_model(
            config,
            [{"role": "user", "content": "make JSON"}],
            debug_log=debug_log,
            debug_context="note-chunk-1-of-16",
        )

    records = [
        json.loads(line)
        for line in (tmp_path / "debug.log").read_text(encoding="utf-8").splitlines()
    ]
    api_error = next(record for record in records if record["message"] == "api_error")
    assert api_error["stage"] == "note_model_call"
    assert api_error["details"]["context"] == "note-chunk-1-of-16"
    assert api_error["details"]["attempt"] == 1
    assert api_error["details"]["exception_type"] == "AuthenticationError"
    assert api_error["details"]["status_code"] == 401
    assert api_error["details"]["body"]["error"]["message"] == "invalid token"
    assert api_error["details"]["body"]["api_key"] == "[REDACTED]"


def test_call_note_model_retries_without_response_format_when_provider_rejects_it(tmp_path, monkeypatch) -> None:
    body = {
        "error": {
            "message": "response_format is not supported by this model",
            "type": "invalid_request_error",
        }
    }
    response = httpx.Response(
        400,
        request=httpx.Request("POST", "https://example.test/chat/completions"),
        json=body,
    )
    error = BadRequestError("Error code: 400 - response_format is not supported", response=response, body=body)
    calls: list[dict] = []

    class FakeCompletions:
        def create(self, **kwargs):
            calls.append(kwargs)
            if "response_format" in kwargs:
                raise error
            text = '{"title":"Demo","summary":"Fallback worked","chapters":[],"key_moments":[]}'
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

    draft = llm.call_note_model(
        config,
        [{"role": "user", "content": "make JSON"}],
        debug_log=debug_log,
        debug_context="note",
    )

    assert draft.summary == "Fallback worked"
    assert "response_format" in calls[0]
    assert "response_format" not in calls[1]
    records = [
        json.loads(line)
        for line in (tmp_path / "debug.log").read_text(encoding="utf-8").splitlines()
    ]
    assert any(record["message"] == "response_format_fallback" for record in records)


def test_call_note_model_keeps_response_format_disabled_after_parse_retry(tmp_path, monkeypatch) -> None:
    body = {
        "error": {
            "message": "response_format is not supported by this model",
            "type": "invalid_request_error",
        }
    }
    response = httpx.Response(
        400,
        request=httpx.Request("POST", "https://example.test/chat/completions"),
        json=body,
    )
    error = BadRequestError("Error code: 400 - response_format is not supported", response=response, body=body)
    calls: list[dict] = []
    fallback_responses = [
        '{"title":"Demo","summary":"missing required comma"',
        '{"title":"Demo","summary":"Second attempt worked","chapters":[],"key_moments":[]}',
    ]

    class FakeCompletions:
        def create(self, **kwargs):
            calls.append(kwargs)
            if "response_format" in kwargs:
                raise error
            text = fallback_responses.pop(0)
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=text))])

    fake_client = SimpleNamespace(chat=SimpleNamespace(completions=FakeCompletions()))
    monkeypatch.setattr(llm, "make_client", lambda *_args, **_kwargs: fake_client)

    config = JobConfig(
        transcription_mode=TranscriptionMode.local_faster_whisper,
        note_api_key="note-key",
        note_language=NoteLanguage.en,
        original_filename="demo.mp4",
    )

    draft = llm.call_note_model(
        config,
        [{"role": "user", "content": "make JSON"}],
        debug_log=TaskDebugLog(tmp_path),
        debug_context="note",
    )

    assert draft.summary == "Second attempt worked"
    assert ["response_format" in call for call in calls] == [True, False, False]


def test_call_json_model_retries_without_response_format_when_provider_rejects_it(monkeypatch) -> None:
    body = {
        "error": {
            "message": "response_format is not supported by this model",
            "type": "invalid_request_error",
        }
    }
    response = httpx.Response(
        400,
        request=httpx.Request("POST", "https://example.test/chat/completions"),
        json=body,
    )
    error = BadRequestError("Error code: 400 - response_format is not supported", response=response, body=body)
    calls: list[dict] = []

    class FakeCompletions:
        def create(self, **kwargs):
            calls.append(kwargs)
            if "response_format" in kwargs:
                raise error
            text = '{"segments":[{"index":0,"corrected_text":"hello"}]}'
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=text))])

    fake_client = SimpleNamespace(chat=SimpleNamespace(completions=FakeCompletions()))
    monkeypatch.setattr(llm, "make_client", lambda *_args, **_kwargs: fake_client)

    config = JobConfig(
        transcription_mode=TranscriptionMode.local_faster_whisper,
        note_api_key="note-key",
        note_language=NoteLanguage.en,
        original_filename="demo.mp4",
    )

    payload = llm.call_json_model(config, [{"role": "user", "content": "fix transcript"}])

    assert payload["segments"][0]["corrected_text"] == "hello"
    assert "response_format" in calls[0]
    assert "response_format" not in calls[1]
