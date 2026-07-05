# Environment and Dependency Optimization Design

## Summary

The project already has useful runtime configuration helpers, but environment path resolution and dependency installation still have a few sharp edges: direct `pytest` invocation can miss the repository root, local dependency package versions are duplicated between code and requirements files, CUDA packages are not pinned, and some configured Python path failures are only discovered later by subprocess calls.

This design keeps the existing behavior and UI shape, then tightens the runtime layer so source mode, tests, dependency install endpoints, model discovery, and desktop packaging all read the same configuration and dependency sources.

## Goals

- Make `pytest backend/tests` and `python -m pytest backend/tests` both work from the repository root.
- Keep environment variable priority over saved settings and defaults.
- Make `runtime_paths.get_model_root()` use the same model directory resolution as the transcription, runtime status, and model download paths.
- Install local transcription dependencies from a shared requirements file instead of a duplicated tuple in Python code.
- Pin CUDA dependency versions in `backend/requirements-cuda.txt` and use that file for install endpoint behavior.
- Bundle the dependency requirements files into the desktop distribution so install endpoints keep working when frozen.
- Improve configured external Python validation for missing commands and directory paths.

## Non-Goals

- Do not upgrade application dependency major versions.
- Do not change the frontend layout or add new settings fields.
- Do not create or manage a virtual environment.
- Do not change the artifact layout under `outputs/`.

## Design

### Test Import Stability

Add a minimal pytest configuration at the repository root with `pythonpath = .` and `testpaths = backend/tests`. This fixes the direct `pytest` console-script case while keeping `python -m pytest` behavior unchanged.

### Dependency Source Files

Create `backend/requirements-local.txt` for runtime and local transcription packages:

- FastAPI / Uvicorn / multipart
- OpenAI SDK
- Pydantic
- imageio-ffmpeg
- faster-whisper

Keep `backend/requirements.txt` as the developer/backend install entrypoint by including `-r requirements-local.txt` plus `pytest`.

Use `backend/requirements-local.txt` for the local dependency install endpoint and `backend/requirements-cuda.txt` for the CUDA dependency install endpoint. The install controller will support either explicit package names or a requirements file, with a clear error when the file is missing.

### Runtime Path Consistency

Keep `runtime_config.get_configured_model_root()` as the settings-aware resolver. Change `runtime_paths.get_model_root()` to delegate to that resolver so old call sites cannot silently ignore saved settings.

For external Python, preserve the priority order:

1. `VIDEO_NOTE_PYTHON_PATH`
2. saved settings
3. PATH lookup for `python`, `python3`, `py`

Add validation so configured non-path executables not found on PATH and configured directory paths return explicit errors.

### Desktop Bundle

Add the local and CUDA requirements files to `desktop/VideoNoteGenerator.spec` datas. This keeps dependency install endpoints usable after PyInstaller freezes the app.

## Error Handling

- A missing requirements file fails before invoking pip with a message naming the missing file.
- A configured Python command that cannot be found on PATH reports that command name.
- A configured Python directory reports that the path is not a file.
- A missing model directory is still non-fatal, because the app can download models into that directory.

## Verification

- `pytest backend\tests -q`
- `python -m pytest backend\tests -q`
- `npm --prefix frontend run build`
- Focused tests for runtime config, runtime paths, install tasks, local dependencies, CUDA dependencies, and model downloads.
