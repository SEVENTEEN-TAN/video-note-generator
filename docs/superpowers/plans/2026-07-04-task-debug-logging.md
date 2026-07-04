# Task Debug Logging Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add per-job debug logs that record the full processing pipeline from task creation through final output or failure.

**Architecture:** Add a small backend task logger that writes `debug.log` and optional raw debug files under each job directory. Wire it through the processor and note-generation LLM calls so every major stage logs start/success/failure details without persisting API keys. Expose logs as normal artifacts and include them in the ZIP.

**Tech Stack:** Python 3.13, FastAPI backend, Pydantic models, pytest, React TypeScript artifact type mirror.

---

### Task 1: Task Debug Logger

**Files:**
- Create: `backend/app/task_debug_log.py`
- Test: `backend/tests/test_task_debug_log.py`

- [ ] **Step 1: Write failing tests**

```python
from backend.app.task_debug_log import TaskDebugLog

def test_task_debug_log_writes_events_and_redacts_sensitive_values(tmp_path):
    log = TaskDebugLog(tmp_path)
    log.event("job", "created", note_api_key="secret", note_model="qwen-plus")
    text = (tmp_path / "debug.log").read_text(encoding="utf-8")
    assert "created" in text
    assert "qwen-plus" in text
    assert "secret" not in text

def test_task_debug_log_writes_debug_artifacts_under_debug_dir(tmp_path):
    log = TaskDebugLog(tmp_path)
    artifact = log.write_debug_text("note-model-response-attempt-1.txt", "bad json")
    assert artifact == tmp_path / "debug" / "note-model-response-attempt-1.txt"
    assert artifact.read_text(encoding="utf-8") == "bad json"
```

- [ ] **Step 2: Run red test**

Run: `python -m pytest backend/tests/test_task_debug_log.py -q`
Expected: FAIL because `backend.app.task_debug_log` does not exist.

- [ ] **Step 3: Implement minimal logger**

Create `TaskDebugLog` with `event`, `exception`, and `write_debug_text`. Log lines are timestamped JSONL-like text. Redact keys containing `api_key`, `token`, `secret`, `password`, or `authorization`.

- [ ] **Step 4: Run green test**

Run: `python -m pytest backend/tests/test_task_debug_log.py -q`
Expected: PASS.

### Task 2: Processor Pipeline Logging

**Files:**
- Modify: `backend/app/processor.py`
- Modify: `backend/app/main.py`
- Modify: `backend/app/job_store.py`
- Modify: `backend/app/models.py`
- Modify: `frontend/src/App.tsx`
- Test: `backend/tests/test_processor.py`
- Test: `backend/tests/test_job_store.py`

- [ ] **Step 1: Write failing tests**

Add processor tests that run a successful job and a failing job, then assert `debug.log` exists and contains stage names such as `probe_duration`, `transcribe_audio`, `generate_note_draft`, `create_zip`, and failure traceback text. Add a job store test that `debug.log` appears as an artifact.

- [ ] **Step 2: Run red tests**

Run: `python -m pytest backend/tests/test_processor.py backend/tests/test_job_store.py -q`
Expected: FAIL because no debug log artifact or processor logging exists.

- [ ] **Step 3: Add pipeline logging**

Instantiate `TaskDebugLog(job_dir)` in `create_job`, `process_job`, and `regenerate_note_job`. Log stage start/success details before and after each external or file-producing operation. Refresh artifacts after writing debug logs. Extend artifact kind to include `log`, and include `debug.log` plus `debug/*.txt` in artifacts.

- [ ] **Step 4: Run green tests**

Run: `python -m pytest backend/tests/test_processor.py backend/tests/test_job_store.py -q`
Expected: PASS.

### Task 3: LLM Response Debug Files

**Files:**
- Modify: `backend/app/llm.py`
- Modify: `backend/app/processor.py`
- Modify: `backend/app/note_versions.py`
- Test: `backend/tests/test_llm_debug_logging.py`

- [ ] **Step 1: Write failing tests**

Add tests that monkeypatch the note model to return invalid JSON and assert the logger writes `debug/note-model-response-attempt-1.txt`, records response length, error location context, and retry attempts.

- [ ] **Step 2: Run red test**

Run: `python -m pytest backend/tests/test_llm_debug_logging.py -q`
Expected: FAIL because LLM calls do not accept a debug logger.

- [ ] **Step 3: Wire debug logger through LLM calls**

Add optional `debug_log` and `debug_context` parameters to `generate_note_draft`, `generate_chunked_note_draft`, `reduce_note_drafts`, and `call_note_model`. Save raw model responses under `debug/`, log prompt and response sizes, and log parse-error context around JSON decode positions.

- [ ] **Step 4: Run green test**

Run: `python -m pytest backend/tests/test_llm_debug_logging.py -q`
Expected: PASS.

### Task 4: ZIP Inclusion And Full Verification

**Files:**
- Modify: `backend/app/processor.py`
- Test: `backend/tests/test_processor.py`

- [ ] **Step 1: Write failing assertion**

Assert `debug.log` and `debug/note-model-response-attempt-1.txt` are included in `download.zip` when present.

- [ ] **Step 2: Implement ZIP inclusion**

Extend `create_zip` to add `debug.log` and all files under `debug/`.

- [ ] **Step 3: Verify full suite**

Run: `python -m pytest backend/tests`
Expected: PASS.

Run: `npm --prefix frontend run build`
Expected: PASS.
