# Job Request Validation Cleanup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Centralize repeated job request validation in `backend/app/main.py` and make frame suggestion use the same local readiness preflight as full job creation.

**Architecture:** Keep route signatures unchanged. Add focused internal helpers in `main.py` for video suffix validation, `JobConfig` construction, and local transcription readiness, then call them from both endpoints before filesystem writes.

**Tech Stack:** Python, FastAPI, Pydantic, pytest, Vite frontend build for regression verification.

---

### Task 1: Add Regression Tests

**Files:**
- Modify: `backend/tests/test_job_validation.py`

- [ ] **Step 1: Add invalid local runtime config test for frame suggestion**

Add a test that posts to `/api/jobs/frame-suggestion` with `transcription_mode=local_faster_whisper`, `local_whisper_device=gpu`, and a mocked local model resolver. Assert status `400` and no temporary directory remains under the patched `OUTPUTS_ROOT`.

- [ ] **Step 2: Add CUDA readiness test for frame suggestion**

Add a test that posts to `/api/jobs/frame-suggestion` with local CUDA, a mocked successful model resolver, and mocked runtime status where `ready_for_cuda` is false. Assert status `400`, error detail contains `CUDA`, and no temporary directory remains under the patched `OUTPUTS_ROOT`.

- [ ] **Step 3: Verify RED**

Run:

```powershell
python -m pytest backend\tests\test_job_validation.py -q
```

Expected: new tests fail because frame suggestion still validates after temp directory creation and does not preflight CUDA readiness.

### Task 2: Refactor Main Validation Helpers

**Files:**
- Modify: `backend/app/main.py`

- [ ] **Step 1: Add `validate_video_extension`**

Create helper:

```python
def validate_video_extension(filename: str | None) -> str:
    suffix = Path(filename or "").suffix.lower()
    if suffix not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported video format. Use one of: {', '.join(sorted(ALLOWED_EXTENSIONS))}.",
        )
    return suffix
```

- [ ] **Step 2: Add `build_job_config_or_400`**

Create an explicit helper that accepts the shared form fields plus `frame_limit` and `original_filename`, constructs `JobConfig`, and converts `ValidationError` into `HTTPException(status_code=400, detail=str(exc))`.

- [ ] **Step 3: Add `ensure_local_transcription_ready`**

Create helper:

```python
def ensure_local_transcription_ready(config: JobConfig) -> None:
    if config.transcription_mode != TranscriptionMode.local_faster_whisper:
        return
    try:
        resolve_local_faster_whisper_model(config.transcription_model, get_faster_whisper_model_root())
    except TranscriptionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    ensure_local_cuda_ready(config)
```

- [ ] **Step 4: Use helpers in both endpoints**

Replace duplicated suffix checks, manual required-field checks, direct `JobConfig` construction, and local model checks in `/api/jobs` and `/api/jobs/frame-suggestion` with the helpers. Keep filesystem writes after all validation/preflight calls.

- [ ] **Step 5: Verify GREEN**

Run:

```powershell
python -m pytest backend\tests\test_job_validation.py -q
```

Expected: all tests in that file pass.

### Task 3: Full Verification

**Files:**
- Verify only; no expected source edits.

- [ ] **Step 1: Run backend tests through Python module invocation**

```powershell
python -m pytest backend\tests -q
```

Expected: all backend tests pass.

- [ ] **Step 2: Run backend tests through direct pytest console script**

```powershell
pytest backend\tests -q
```

Expected: all backend tests pass.

- [ ] **Step 3: Run frontend build**

```powershell
npm --prefix frontend run build
```

Expected: TypeScript and Vite build succeed.
