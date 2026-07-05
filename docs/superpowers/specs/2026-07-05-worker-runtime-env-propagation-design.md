# Worker Runtime Environment Propagation Design

## Summary

The local Faster Whisper worker runs as a subprocess of an external Python interpreter. Today the worker only receives the configured model directory as a CLI argument, while the subprocess environment is built from the parent's raw `os.environ` plus UTF-8 settings. This works for the current code paths, but it is fragile when the user customizes the default dependency and model locations (for example storing models on a non-C drive configured through settings rather than an environment variable).

The architectural smell: resolution of the model root lives in two priority sources (environment variable, then settings, then default), but the subprocess only inherits the environment-variable layer. Any code path inside the worker that falls back to environment-based cache resolution (huggingface_hub defaults, future ctranslate2/faster_whisper reads, or a subprocess spawned by the worker) would land in the C-drive default location instead of the user's configured directory.

This change makes the resolved runtime context flow consistently into the worker subprocess without changing any public API or filesystem layout.

## Goals

- Keep all public endpoints, request payloads, artifact names, and path resolution priority unchanged.
- Propagate the resolved model directory (from environment, settings, or default) into the worker subprocess environment so that environment-based reads and huggingface cache fallbacks honor the user's configured location, including non-C-drive paths configured only through settings.
- Reuse the same worker environment for transcription, model download, and dependency install subprocesses.
- Keep explicit `--model-root` CLI arguments (they remain authoritative for the worker's own argument parsing).

## Non-Goals

- Do not change how the worker resolves models internally.
- Do not install the backend package into the external Python or deduplicate the worker's model resolution code.
- Do not change CUDA DLL discovery logic.
- Do not change the desktop build pipeline or PyInstaller spec beyond what already landed.

## Design

Generalize `transcription.external_worker_env` to accept the resolved model root and inject the canonical cache environment variables:

- `FASTER_WHISPER_MODEL_DIR` set to the resolved model root, so the project's own priority chain and any env-based read inside the worker agree.
- `HUGGINGFACE_HUB_CACHE` set to the resolved model root, so huggingface_hub's implicit cache location matches the explicit `cache_dir` already passed by the download path.

Existing environment values are preserved. When the parent resolved the model root from an environment variable, the injection is idempotent. When the parent resolved it from settings or defaults, the worker now sees the same path.

Callers updated:

- `transcribe_with_external_faster_whisper` passes the model root it already computed.
- `model_downloads.download_faster_whisper_model` passes the model root it already passes as `--model-root`.
- `install_tasks.PackageInstallController.install_packages` continues to use the same env helper; pip does not consume the model cache variables, but keeping one env builder avoids drift.

## Error Handling

- If the resolved model root cannot be created, transcription already fails with the existing `TranscriptionError`. No new failure modes.
- Environment injection never overrides an explicit parent environment value, so power users setting `HF_HOME` directly are not overridden.

## Tests

- `external_worker_env()` with a configured model root injects `FASTER_WHISPER_MODEL_DIR` and `HUGGINGFACE_HUB_CACHE`.
- `external_worker_env()` without a model root keeps the previous behavior.
- When a parent environment already sets `HUGGINGFACE_HUB_CACHE`, the helper preserves it instead of overriding.
- The external transcription path launches the worker with the resolved model root injected into its environment, even when that root came from settings.

## Verification

- `python -m pytest backend\tests -q`
- `pytest backend\tests -q`
- `npm --prefix frontend run build`
- Desktop build: `./scripts/build-desktop.ps1` produces `dist/VideoNoteGenerator/VideoNoteGenerator.exe`.
