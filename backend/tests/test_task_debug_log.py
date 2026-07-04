from __future__ import annotations

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
