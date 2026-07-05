from __future__ import annotations

import json

from backend.app.task_debug_log import TaskDebugLog


def test_task_debug_log_writes_events_and_redacts_sensitive_values(tmp_path) -> None:
    log = TaskDebugLog(tmp_path)

    log.event("job", "created", note_api_key="secret-key", note_model="qwen-plus")

    text = (tmp_path / "debug.log").read_text(encoding="utf-8")
    assert "created" in text
    assert "qwen-plus" in text
    assert "secret-key" not in text
    assert "[REDACTED]" in text


def test_task_debug_log_keeps_non_secret_token_count_fields(tmp_path) -> None:
    log = TaskDebugLog(tmp_path)

    log.event("llm", "requesting", max_tokens=3600, note_api_key="secret-key")

    text = (tmp_path / "debug.log").read_text(encoding="utf-8")
    assert "3600" in text
    assert "secret-key" not in text


def test_task_debug_log_writes_debug_artifacts_under_debug_dir(tmp_path) -> None:
    log = TaskDebugLog(tmp_path)

    artifact = log.write_debug_text("note-model-response-attempt-1.txt", "bad json")

    assert artifact == tmp_path / "debug" / "note-model-response-attempt-1.txt"
    assert artifact.read_text(encoding="utf-8") == "bad json"


def test_task_debug_log_truncates_very_long_string_fields(tmp_path) -> None:
    log = TaskDebugLog(tmp_path)
    long_error = "start-" + ("x" * 5000) + "-end"

    log.event("llm", "invalid_json", error_context=long_error)

    record = json.loads((tmp_path / "debug.log").read_text(encoding="utf-8"))
    error_context = record["details"]["error_context"]
    assert len(error_context) < 1200
    assert "start-" in error_context
    assert "-end" in error_context
    assert "truncated" in error_context


def test_task_debug_log_redacts_credentials_embedded_in_strings(tmp_path) -> None:
    log = TaskDebugLog(tmp_path)

    log.event(
        "llm",
        "api_error",
        error="Authorization: Bearer sk-secret-token; retry with api_key=another-secret",
    )

    text = (tmp_path / "debug.log").read_text(encoding="utf-8")
    assert "sk-secret-token" not in text
    assert "another-secret" not in text
    assert "Bearer [REDACTED]" in text
    assert "api_key=[REDACTED]" in text
