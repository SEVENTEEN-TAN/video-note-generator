# Environment Dependency Optimization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make environment path resolution and dependency installation consistent across source, tests, runtime diagnostics, and desktop builds.

**Architecture:** Keep runtime configuration centralized in `backend/app/runtime_config.py`; let legacy path helpers delegate to it where needed. Move dependency install endpoints from hard-coded package tuples to bundled requirements files while preserving existing pip install modes.

**Tech Stack:** Python 3, FastAPI backend, pytest, pip requirements files, PyInstaller desktop spec, Vite/React frontend verification.

---

### Task 1: Add Regression Tests

**Files:**
- Modify: `backend/tests/test_runtime_config.py`
- Modify: `backend/tests/test_runtime_paths.py`
- Modify: `backend/tests/test_install_tasks.py`

- [ ] **Step 1: Test missing configured Python command**

Add a test that sets `VIDEO_NOTE_PYTHON_PATH` to a command that cannot exist and asserts `get_configured_external_python()` reports an environment-source error instead of returning the raw command.

- [ ] **Step 2: Test directory configured as Python**

Add a test that saves a directory in settings as `external_python_path` and asserts the resolver reports that it is not a file.

- [ ] **Step 3: Test settings-aware model root through runtime paths**

Add a test that saves `faster_whisper_model_dir` and asserts `runtime_paths.get_model_root()` returns that saved directory.

- [ ] **Step 4: Test requirements-file pip installation**

Add install-controller tests that verify `pip install -r <requirements-file>` and clear failure output when the requirements file is missing.

- [ ] **Step 5: Verify RED**

Run:

```powershell
python -m pytest backend\tests\test_runtime_config.py backend\tests\test_runtime_paths.py backend\tests\test_install_tasks.py -q
```

Expected: FAIL because the new behavior is not implemented yet.

### Task 2: Implement Runtime and Install Changes

**Files:**
- Modify: `backend/app/runtime_config.py`
- Modify: `backend/app/runtime_paths.py`
- Modify: `backend/app/install_tasks.py`
- Modify: `backend/app/local_dependencies.py`
- Modify: `backend/app/cuda_dependencies.py`
- Create: `backend/requirements-local.txt`
- Modify: `backend/requirements.txt`
- Modify: `backend/requirements-cuda.txt`
- Modify: `desktop/VideoNoteGenerator.spec`

- [ ] **Step 1: Add requirements-file support to install controller**

Extend `PackageInstallController` with an optional `requirements_file_provider`. When present, it validates the file exists and runs `python -m pip install <install args> -r <path>`.

- [ ] **Step 2: Use bundled requirements files**

Make local dependency installation use `backend/requirements-local.txt` and CUDA dependency installation use `backend/requirements-cuda.txt`.

- [ ] **Step 3: Split and pin requirements**

Move runtime/local packages into `backend/requirements-local.txt`, include it from `backend/requirements.txt`, and pin CUDA packages in `backend/requirements-cuda.txt`.

- [ ] **Step 4: Fix path consistency**

Make `runtime_paths.get_model_root()` delegate to `runtime_config.get_configured_model_root()` and tighten configured Python validation.

- [ ] **Step 5: Bundle requirements in desktop spec**

Add the local and CUDA requirements files to PyInstaller datas.

- [ ] **Step 6: Verify GREEN**

Run:

```powershell
python -m pytest backend\tests\test_runtime_config.py backend\tests\test_runtime_paths.py backend\tests\test_install_tasks.py -q
```

Expected: PASS.

### Task 3: Full Verification

**Files:**
- Verify only; no expected source edits.

- [ ] **Step 1: Run backend tests through Python module invocation**

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

- [ ] **Step 4: Review diff**

```powershell
git diff -- backend desktop docs pytest.ini
```

Expected: only environment/dependency optimization changes are present.
