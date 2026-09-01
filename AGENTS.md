# AGENTS.md

This file provides guidance to Codex (Codex.ai/code) when working with code in this repository.

## Overview

This repository is a local-first video note generator with two main entry modes:

- `frontend/`: Vite + React single-page UI for configuring jobs, monitoring progress, previewing notes/subtitles, managing note versions, and downloading artifacts.
- `backend/`: FastAPI service that accepts uploaded videos, runs the processing pipeline, stores per-job artifacts on disk, and serves both API endpoints and the built frontend bundle when `frontend/dist` exists.
- `desktop/`: Windows desktop wrapper that starts the FastAPI app in-process with Uvicorn and opens it in `pywebview` (fallback: system browser).

The product flow is: upload video → extract MP3 with FFmpeg → transcribe audio (local Faster Whisper or remote OpenAI-compatible endpoint) → generate structured note JSON via chat completions → extract key frames → write markdown/subtitle artifacts → build ZIP.

## Common commands

### Backend setup and run

```bash
python -m pip install -r "backend/requirements.txt"
python -m uvicorn backend.app.main:app --reload --host 127.0.0.1 --port 8000
```

### Frontend setup and run

```bash
npm --prefix "frontend" install
npm --prefix "frontend" run dev
```

Vite dev server runs on `http://127.0.0.1:5173` and proxies `/api` to `http://127.0.0.1:8000` via `frontend/vite.config.ts`.

### Frontend production build

```bash
npm --prefix "frontend" run build
npm --prefix "frontend" run preview
```

### Backend tests

Run all backend tests:

```bash
pytest "backend/tests"
```

Run a single test file:

```bash
pytest "backend/tests/test_processor.py"
```

Run a single test by name:

```bash
pytest "backend/tests/test_processor.py" -k "generates_artifacts"
```

### Windows desktop build

```bash
./scripts/build-desktop.ps1
```

Bundle the cached Faster Whisper `small` model into the desktop distribution:

```bash
./scripts/build-desktop.ps1 -BundleSmallModel
```

Desktop build script performs, in order:

1. `npm --prefix frontend install`
2. `npm --prefix frontend run build`
3. `python -m pip install -r backend/requirements.txt`
4. `python -m pip install -r desktop/requirements.txt`
5. `python -m PyInstaller --clean --noconfirm desktop/VideoNoteGenerator.spec`

### Run built desktop app

```bash
./dist/VideoNoteGenerator/VideoNoteGenerator.exe
```

## Architecture

### Backend request surface

`backend/app/main.py` is the API composition root. It owns:

- FastAPI lifespan, CORS, router registration, shared job dependencies, and static frontend mounting
- job lifecycle endpoints: create job, poll job state, preview note/subtitles, download assets/ZIP
- note version management and note regeneration endpoints

Extracted domain routers currently own:

- `backend/app/api/runtime.py`: `/api/ready`, `/api/health`, `/api/runtime`, local dependency installation, model download, and Faster Whisper cache release
- `backend/app/api/settings.py`: local settings read/update/delete
- `backend/app/api/downloads.py`: note/subtitle previews, version previews, artifact serving, final ZIP, and diagnostics ZIP
- `backend/app/api/review.py`: quality reports, frame candidate reads and decisions, review drafts/assets, and finalization
- `backend/app/api/subtitles.py`: subtitle confirmation/regeneration and transcript-correction preview/application
- `backend/app/api/notes.py`: note chunk reads/regeneration and note version reads/selection/regeneration
- `backend/app/api/jobs.py`: frame suggestions, job creation/history/state, cancellation, transcription resume, storage/cache management, and deletion

`backend/app/note_regeneration.py` owns the recoverable single-chunk regeneration operation and keeps the `_regenerate_chunk_job` operation type stable. `backend/app/job_paths.py` owns validated job directory and artifact path resolution. Domain routers must not import `backend.app.main`; use injected dependencies or move shared behavior into application/service modules instead. `main.py` should remain the composition root and must not regain domain route handlers.

`/api/ready` is intentionally cheap and should stay independent from expensive runtime detection; there is a regression test for that in `backend/tests/test_runtime_api.py`.

### Processing pipeline

The main orchestration is in `backend/app/processor.py`:

1. probe video duration and extract MP3 with `ffmpeg_tools`
2. transcribe audio with `transcription.transcribe_audio`
3. normalize subtitle segments and write `srt` / `vtt` / markdown subtitles
4. generate a structured `NoteDraft` with `llm.generate_note_draft`
5. create a note version plus frames via `note_versions.create_note_version_from_draft`
6. write `metadata.json`, rebuild `download.zip`, and update in-memory job state

Any change to artifact names or layout must be checked against ZIP creation and frontend download/preview code, because both assume stable filenames like `note.md`, `subtitles.md`, `download.zip`, and `frames/*.jpg`.

Upload handling is centralized in `backend/app/upload_limits.py`. Both `/api/jobs` and `/api/jobs/frame-suggestion` must keep the pre-parse `Content-Length` limit, declared-size/disk-space preflight, streaming byte-count enforcement, and cleanup of unregistered job or temporary directories. Limits are overrideable with `VIDEO_NOTE_MAX_VIDEO_UPLOAD_BYTES`, `VIDEO_NOTE_MAX_SUBTITLE_UPLOAD_BYTES`, and `VIDEO_NOTE_UPLOAD_MIN_FREE_BYTES`.

### Data and validation models

`backend/app/models.py` is the shared schema layer for:

- stage-specific job configuration: `JobInputConfig`, `TranscriptionConfig`, `NotePreferences`, and `NoteGenerationConfig`
- transcription modes and local Whisper runtime options
- transcript payloads and note draft structure
- note version metadata
- public job state returned to the frontend

Job creation must not require or persist a note API key. It stores `NotePreferences`; note credentials are validated only at subtitle confirmation or another note-generation entry point. `JobConfig` remains only as a compatibility adapter for older callers and test fixtures; new production code must consume the narrow stage config it needs.

If you change enums or validation rules here, trace the impact through both FastAPI form handling in `backend/app/main.py` and mirrored TypeScript unions/types in `frontend/src/App.tsx`.

### Transcription subsystem

`backend/app/transcription.py` supports three transcription modes:

- `local_faster_whisper`: prefer in-process `faster_whisper`, fallback to external Python worker if bundled dependencies are missing
- `audio_transcriptions`: OpenAI-compatible `/audio/transcriptions` endpoint with segment timestamps
- `chat_audio`: chunked audio sent through chat completions multimodal audio fallback

Important implementation details:

- local model discovery/validation is file-based and happens before job start; the app does not silently download on first use
- large audio files are chunked before remote transcription
- local runtime selection also reads `FASTER_WHISPER_DEVICE`, `FASTER_WHISPER_COMPUTE_TYPE`, and `FASTER_WHISPER_MODEL_DIR`
- desktop/lightweight packaging relies on the external worker path when bundled Python dependencies are incomplete

### Runtime- and desktop-specific path handling

`backend/app/runtime_paths.py` centralizes path decisions for source mode vs frozen desktop mode.

Pay attention to the distinction between:

- `get_bundle_root()`: where bundled code/assets are read from
- `get_app_data_root()`: where runtime-writable files live in frozen mode
- `get_outputs_root()`: job artifacts root, overrideable by `VIDEO_NOTE_OUTPUTS_DIR`
- `get_frontend_dist_dir()`: built frontend path, overrideable by `VIDEO_NOTE_FRONTEND_DIST`
- `get_model_root()`: local Faster Whisper model root

This separation is important when changing filesystem behavior because the desktop build writes outputs, config, and model caches next to the executable rather than back into the repository.

### Runtime diagnostics and install flows

`backend/app/runtime_status.py` aggregates FFmpeg availability, Faster Whisper availability, CUDA visibility, external worker availability, local model presence, and settings file location into the payload consumed by the UI.

The frontend uses this runtime payload to decide whether to:

- allow local Faster Whisper usage
- offer model download
- offer CUDA dependency installation
- show path/hint diagnostics

If you change runtime payload shape, update the `RuntimeState` type and related UI logic in `frontend/src/App.tsx`.

### Note generation and versioning

`backend/app/llm.py` generates structured note JSON, not freeform markdown first. It:

- builds transcript prompts from timestamped segments
- applies note style instructions and optional user extras
- uses direct JSON response parsing with retry-on-invalid-JSON
- falls back to chunked map/reduce note generation for long transcripts

`backend/app/note_versions.py` owns versioned note regeneration and selection state. The frontend treats regenerated notes as version history rather than overwriting the original note in place.

When changing note draft schema or markdown rendering, inspect the whole chain:

- `llm.py` output schema
- `markdown.py` rendering
- `note_versions.py` persisted version metadata
- frontend preview/version selection logic in `frontend/src/useNoteWorkflow.ts` and `frontend/src/ResultWorkbench.tsx`

### Frontend structure

`frontend/src/App.tsx` remains the page-level composition component. It owns workbench selection, keyboard shortcuts, and feature-hook composition.

Extracted feature views currently include:

- `TaskConfigPanel.tsx`: controlled video/SRT selection, note preferences, create/cancel/resume controls
- `SettingsModal.tsx`: settings shell, persistence controls, runtime summary, and grouped modal/note/transcription inputs
- `SettingsTranscriptionSection.tsx`: transcription mode/language selection and local-vs-remote section composition
- `SettingsLocalTranscriptionSection.tsx`: Faster Whisper model/runtime, device/compute, Python/CUDA dependency, and model-download controls
- `SettingsRemoteTranscriptionSection.tsx`: remote transcription endpoint, model, and API key fields
- `SettingsNoteApiSection.tsx`: note endpoint presets, model, and API key fields
- `ResultWorkbench.tsx`: controlled downloads, workbench navigation, note/subtitle/frame previews, chunk management, and manual-review entry points; its inputs are grouped by context, downloads, frames, note, and subtitle, and it does not own job polling or current-job identity
- `FrameReviewModal.tsx`: review-draft editing and frame selection
- `RuntimeStatus.tsx`, `QualityStatusControl.tsx`, `TranscriptCorrectionModal.tsx`, `JobHistoryPanel.tsx`, and `WorkbenchNavigation.tsx`: focused presentation components
- `useJobResources.ts`: artifact-revision-aware loading and cancellation of job-derived resources
- `useSubtitleWorkflow.ts`: subtitle confirmation, regeneration, AI correction, correction application, and stale-response isolation across job switches
- `useNoteWorkflow.ts`: note-version switching, full/chunk regeneration, finalization, revision-conflict handling, and stale-response isolation
- `useReviewWorkflow.ts`: manual-review preparation, paragraph saving, quality refresh, modal state, revision-conflict handling, and stale-response isolation
- `useRuntimeTasks.ts`: model download, local/CUDA dependency installation, non-overlapping polling, launch-failure mapping, and runtime refresh on completion
- `useSettings.ts`: typed settings state, defaults, initial loading, field updates, persistence, clearing, unmount protection, and runtime refresh
- `useJobLifecycle.ts`: current-job state, primary polling, history loading, job switching, cancellation, transcription resume, deletion, and stale-response isolation
- `useJobCreation.ts`: video/SRT selection, pre-submit runtime validation, form-data construction, local-model download entry, job creation, input cleanup coordination, and stale-response isolation
- `useHealthState.ts`: runtime health state, non-overlapping startup retries, explicit refresh, request cancellation, unmount protection, and stale-response isolation

Feature views must not own global job polling or current-job switching. Keep network mutations and cross-feature state in `App.tsx` or focused hooks, and pass typed values/callbacks into presentation components.

## Files and directories with special roles

- `outputs/`: per-job runtime artifacts; not source-of-truth code
- `backend/tests/`: pytest suite covering processing, settings, runtime, transcription, note versioning, and desktop launcher behavior
- `outputs/moodboards/video-note-generator-ui/`: UI exploration/reference assets, not the active Vite app
- `scripts/build-desktop.ps1`: canonical desktop packaging entrypoint

## External and optional dependencies

The app depends on several tools/services that are not fully mocked by the runtime architecture:

- FFmpeg must be available for audio extraction and frame capture
- local transcription depends on Faster Whisper model files and optionally CUDA runtime libraries
- remote transcription and note generation expect OpenAI-compatible APIs

There is also a separate CUDA helper requirements file:

```bash
python -m pip install -r "backend/requirements-cuda.txt"
```

Use it when working on or validating the CUDA install flow.
