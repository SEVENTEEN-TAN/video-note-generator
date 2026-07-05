# Worker Runtime Environment Propagation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the configured model directory flow into the external Faster Whisper worker subprocess environment so custom (non-C-drive) paths configured through settings are respected by the worker and its cache fallbacks.

**Architecture:** Generalize `transcription.external_worker_env` to accept the resolved model root and inject `FASTER_WHISPER_MODEL_DIR` and `HUGGINGFACE_HUB_CACHE`. Update transcription, model download, and dependency install subprocess launches to pass the resolved model root through this single helper.

**Tech Stack:** Python, FastAPI, pytest, PyInstaller desktop build.

---

### Task 1: Add Regression Tests

**Files:**
- Modify: `backend/tests/test_transcription.py`

- [ ] **Step 1: Test env injection injects model cache variables**

Add a test that calls `external_worker_env(model_root=Path("D:/custom/models"))` and asserts the returned env sets `FASTER_WHISPER_MODEL_DIR` and `HUGGINGFACE_HUB_CACHE` to that path while preserving existing os.environ entries.

- [ ] **Step 2: Test env helper preserves explicit HUGGINGFACE_HUB_CACHE**

Add a test that sets `HUGGINGFACE_HUB_CACHE` in the monkeypatched environment and asserts the helper does not override it when a model root is provided.

- [ ] **Step 3: Test env helper without model root is backward compatible**

Add a test that `external_worker_env()` returns an env containing the UTF-8 overrides and does not set model cache variables.

- [ ] **Step 4: Verify RED**

Run:

```powershell
python -m pytest backend\tests\test_transcription.py -q -k external_worker_env
```

Expected: FAIL because the helper does not yet accept a model root argument.

### Task 2: Implement Worker Env Propagation

**Files:**
- Modify: `backend/app/transcription.py`
- Modify: `backend/app/model_downloads.py`

- [ ] **Step 1: Generalize `external_worker_env`**

Update the helper to accept an optional `model_root: Path | None` and inject `FASTER_WHISPER_MODEL_DIR` and `HUGGINGFACE_HUB_CACHE` when provided, without overriding existing values.

- [ ] **Step 2: Pass model root from transcription**

In `transcribe_with_external_faster_whisper`, call `external_worker_env(model_root=model_root)`.

- [ ] **Step 3: Pass model root from model download**

In `model_downloads.download_faster_whisper_model`, call `external_worker_env(model_root=model_root)`.

- [ ] **Step 4: Verify GREEN**

Run:

```powershell
python -m pytest backend\tests\test_transcription.py -q
```

Expected: PASS.

### Task 3: Full Verification and Desktop Build

**Files:**
- Verify and build only; no expected source edits.

- [ ] **Step 1: Run backend tests through module invocation**

```powershell
python -m pytest backend\tests -q
```

Expected: all tests pass.

- [ ] **Step 2: Run backend tests through direct pytest console script**

```powershell
pytest backend\tests -q
```

Expected: all tests pass.

- [ ] **Step 3: Run frontend build**

```powershell
npm --prefix frontend run build
```

Expected: TypeScript and Vite build succeed.

- [ ] **Step 4: Build the Windows desktop app**

```powershell
./scripts/build-desktop.ps1
```

Expected: `dist/VideoNoteGenerator/VideoNoteGenerator.exe` exists and the build produced a bundled Python DLL and `_internal` directory.
