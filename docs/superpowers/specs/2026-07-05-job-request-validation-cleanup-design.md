# Job Request Validation Cleanup Design

## Summary

`backend/app/main.py` currently repeats request validation and `JobConfig` construction across `/api/jobs` and `/api/jobs/frame-suggestion`. The repeated checks make future form changes easy to apply to one endpoint but miss in the other. One concrete behavior gap exists today: frame suggestion can run a local CUDA transcription path without using the same CUDA readiness preflight as full job creation.

This cleanup keeps the public API and form fields unchanged while centralizing the small pieces of validation that both endpoints already need.

## Goals

- Keep `/api/jobs` and `/api/jobs/frame-suggestion` request behavior stable for existing valid calls.
- Validate video extensions through one helper.
- Build `JobConfig` through one helper that converts Pydantic validation errors into `400` responses before creating output directories.
- Reuse one local transcription readiness helper for local model availability and CUDA readiness.
- Make frame suggestion reject local CUDA requests before writing temporary files when CUDA runtime is not ready.

## Non-Goals

- Do not redesign the FastAPI route signatures.
- Do not change frontend form fields or request payload shape.
- Do not change processing artifacts, ZIP contents, or job history behavior.
- Do not split `main.py` into new modules in this pass.

## Design

Add small internal helpers in `backend/app/main.py`:

- `validate_video_extension(filename: str | None) -> str`
- `build_job_config_or_400(...) -> JobConfig`
- `ensure_local_transcription_ready(config: JobConfig) -> None`

`validate_video_extension` returns the lowercase suffix or raises the same unsupported-format `400` response.

`build_job_config_or_400` constructs `JobConfig` and converts `pydantic.ValidationError` into `HTTPException(status_code=400, detail=str(exc))`. Both endpoints call this helper before writing files.

`ensure_local_transcription_ready` checks local Faster Whisper model availability, then delegates CUDA checks to existing `ensure_local_cuda_ready`. Both endpoints call it for local transcription mode. For non-local transcription it returns immediately.

## Error Handling

- Invalid form/config input is rejected before output or temporary directories are created.
- Local model errors remain `400` with the current model-resolution detail.
- Local CUDA readiness errors remain `400` and include `CUDA`.

## Tests

- Add a frame-suggestion regression test proving invalid local runtime config is rejected before temporary files are created.
- Add a frame-suggestion regression test proving local CUDA not ready is rejected before temporary files are created.
- Keep existing `/api/jobs` validation tests green.

## Verification

- `python -m pytest backend\tests\test_job_validation.py -q`
- `python -m pytest backend\tests -q`
- `pytest backend\tests -q`
- `npm --prefix frontend run build`
