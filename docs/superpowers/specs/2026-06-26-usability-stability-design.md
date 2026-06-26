# Usability And Stability Improvement Design

## Summary

Improve the current local-first video note generator without changing its product identity or visual system. The approved first phase combines stability fixes with existing-feature usability improvements. It addresses real backend safety and recovery risks, makes the main workflow clearer before and during long jobs, and exposes artifacts and version metadata that already exist but are underused in the UI.

The product remains a single-user local workbench: upload a video, transcribe audio, generate structured notes, extract frames, manage history and note versions, and download local artifacts. This phase does not add login, cloud sync, collaboration, multi-user queueing, or a new visual direction.

## Current Evidence

- Backend is FastAPI with disk-based job artifacts under `outputs/{job_id}`.
- Frontend is a Vite React app, mostly in `frontend/src/App.tsx`, using existing `styles.css` workbench styling.
- Backend tests currently pass with `python -m pytest backend/tests`.
- Frontend production build currently passes with `npm --prefix frontend run build`.
- Exploratory testing reproduced a real path safety bug: encoded `.` as a job id can resolve to the entire outputs root and allow deletion of that root through the delete endpoint.
- Three sub-agent reviews found overlapping priorities: backend path and version-index hardening, long-task progress clarity, first-run readiness checks, failed-job recovery, artifact discoverability, and version-management visibility.

## Approved Scope

### 1. Code Bug Optimization

#### Job Id Path Safety

`safe_job_dir()` must reject job ids that resolve to the outputs root, parent directories, path separators, empty segments, or dot segments. A job id must resolve to a single direct child of `OUTPUTS_ROOT`.

Affected surface:

- `backend/app/main.py`
- `backend/tests/test_job_validation.py` or a focused new backend test file

Required behavior:

- `GET /api/jobs/%2E` returns a client error instead of loading the outputs root as a job.
- `DELETE /api/jobs/%2E` cannot delete `OUTPUTS_ROOT`.
- Normal generated job ids and existing single-directory history jobs continue to work.

#### Note Version Path Safety And Corrupt Index Recovery

Version metadata from `note_versions/versions.json` must not be trusted as raw filesystem paths. Loading or using a note version must reject or ignore paths that escape the job directory. Corrupt or invalid `versions.json` must not make the entire history endpoint fail.

Affected surface:

- `backend/app/note_versions.py`
- `backend/app/processor.py`
- `backend/app/job_store.py`
- `backend/tests/test_note_versions.py`
- `backend/tests/test_job_history.py`

Required behavior:

- Version ids used for ZIP archive names are safe path segments.
- `note_path` and `frame_dir` are resolved as job-relative paths and cannot point outside the job directory.
- A corrupt `versions.json` degrades to an empty version index for history/listing behavior.
- Activating or zipping a malicious version index cannot copy external files or add external files to the ZIP.
- Normal version creation, activation, selection, and ZIP generation remain compatible.

#### Atomic Version Index And ZIP Writes

Version index and ZIP writes should avoid leaving half-written files when interrupted. Existing metadata writes already use straightforward local JSON writes; this phase focuses on the version index and `download.zip`, which are most directly touched by version selection/regeneration.

Affected surface:

- `backend/app/note_versions.py`
- `backend/app/processor.py`
- Tests around ZIP creation and version index behavior

Required behavior:

- `versions.json` is written through a temporary file and replaced atomically.
- `download.zip` is written through a temporary file and replaced atomically.
- Failed ZIP rebuilds do not leave a misleading new `download.zip` path.

#### CUDA Readiness Guard

When local transcription is selected with CUDA, the app must not proceed as if CPU readiness is sufficient. The frontend should block or guide the user to CPU when CUDA is not ready, and the backend should reject a CUDA local transcription job if runtime diagnostics say CUDA dependencies are unavailable.

Affected surface:

- `frontend/src/App.tsx`
- `backend/app/main.py`
- `backend/app/runtime_status.py` only if a helper is needed
- Backend validation tests

Required behavior:

- If `local_whisper_device === "cuda"` and runtime status says CUDA is not ready, the main submit path shows a clear message before creating a job.
- The message offers the existing recovery options: install CUDA dependencies from settings or switch to CPU.
- Backend validation rejects CUDA jobs when runtime diagnostics indicate CUDA runtime is missing, so API-only use gets the same protection.
- CPU local transcription behavior is unchanged.

#### Create Job Validation Before Side Effects

`create_job()` should validate `JobConfig` inputs before creating the job directory and copying the uploaded file. If late file-copy or metadata failures happen, the newly created job directory should be cleaned up when safe.

Affected surface:

- `backend/app/main.py`
- Backend validation tests

Required behavior:

- Invalid `extras`, local Whisper runtime values, or other `JobConfig` validation failures do not leave orphan job directories.
- Upload copy failures return a clear HTTP error and clean up the new job directory.
- Existing successful job creation and metadata seeding continue to work.

### 2. Existing Functionality Supplement

#### Start Readiness Summary

The main configuration panel should show a compact preflight summary near the submit button. It should use existing state, not add new heavyweight polling.

Signals:

- Backend connected or not.
- FFmpeg available or missing.
- For local Faster Whisper: CPU readiness, selected model availability, and CUDA readiness when CUDA is selected.
- Note API key present or missing.
- Remote transcription API key present when remote transcription is selected.

Behavior:

- The summary is visible before submission.
- Items use existing button/link actions where available: open settings, start model download, install local/CUDA dependencies, or switch the user to CPU where appropriate.
- It does not expose API key values.

#### Long-Task Progress Clarity

The progress area should show the current backend step text, percentage, and current-stage elapsed time. Step activation must not rely only on exact Chinese string equality.

Affected surface:

- `frontend/src/App.tsx`
- `frontend/src/styles.css`
- Optionally backend model only if a stable `stage` field is introduced; otherwise keep this frontend-only by deriving stage from progress and step prefixes.

Behavior:

- During chunked transcription, the UI keeps "字幕生成" visually active while showing detailed text such as `字幕生成中：第 2/8 段转写中`.
- The user sees `progress` and `stage_elapsed_seconds` in the active job summary.
- Failed jobs show the failed step and elapsed time.

#### Failed-Job Recovery Panel

When a job fails, the UI should explain what can still be used and what the next action is. This is derived from existing artifacts.

Behavior:

- If subtitles or transcript artifacts exist, show download actions and allow "重新生成笔记" if `transcript.json` exists.
- If only audio exists, show audio download and indicate that transcription must be retried.
- If no reusable artifacts exist, show a concise "fix settings/dependencies and retry" path.
- The existing error text remains visible.

#### Complete Artifact Downloads

The UI should expose all generated artifacts, while keeping common downloads easy.

Behavior:

- Keep top-level buttons for Markdown, SRT, MP3, and ZIP.
- Add an "全部产物" area that lists `job.artifacts`, including VTT, transcript JSON, metadata JSON, and frames.
- Downloads reuse the existing browser/desktop download path.
- Desktop save success should show the returned path when the desktop bridge supplies one. Browser downloads should show that the download was triggered.

#### Version Metadata Visibility And ZIP Selection

The note version UI should make current backend version metadata useful without introducing a full diff tool.

Behavior:

- Version options show id, style, created time, model, and active status.
- The user can see which versions are selected for ZIP inclusion.
- The user can toggle selected versions for ZIP inclusion without changing the active preview version.
- Active version remains the version shown as `note.md` and copied frames.
- ZIP rebuild happens after selection changes, matching current backend behavior.

### 3. Practical New Function Candidates

The approved first phase does not implement a large new workflow. It records the next high-value practical features for separate design and planning.

#### Subtitle Correction Then Regenerate Note

User value: local Whisper can misrecognize terms. Letting users correct subtitles before regenerating a note can materially improve final notes without retranscribing the video.

Expected future shape:

- Preserve original transcript and subtitles.
- Add an editable subtitle/transcript view with timestamp validation.
- Save a corrected transcript variant.
- Regenerate a new note version from the corrected transcript.

Main dependencies:

- `backend/app/subtitles.py`
- `backend/app/note_versions.py`
- `backend/app/main.py`
- `frontend/src/App.tsx`

#### Timestamp-Linked Local Video Preview

User value: clicking timestamps in the note or subtitle preview should jump to the source video, making review and study faster.

Expected future shape:

- Expose the original source video as a safe asset for the owning job.
- Parse note/subtitle timestamps into clickable controls.
- Seek a local video preview to the selected timestamp.

Main dependencies:

- `backend/app/main.py`
- `backend/app/processor.py`
- `frontend/src/App.tsx`

## Architecture Approach

Keep backend safety changes close to the existing path and version modules rather than introducing broad abstractions. Add small helper functions where they remove duplicated path checks:

- A job-directory validator in `main.py` or a small shared helper if tests show reuse pressure.
- A note-version path resolver in `note_versions.py`.
- Atomic write helpers local to the modules that need them.

Keep frontend changes inside the current `App.tsx` and `styles.css` pattern. The file is large, but this phase should not split components unless necessary for readability of the new panels. Any extraction should be limited to small pure rendering helpers inside the same file.

## Data Flow

### Job Creation

1. Frontend preflight reads existing `health`, local model status, selected transcription mode, selected device, and API key presence.
2. Frontend blocks obviously invalid local CUDA submissions before posting.
3. Backend validates form fields into `JobConfig`.
4. Backend checks local model and CUDA runtime where applicable.
5. Backend creates the job directory and copies the upload only after validation succeeds.
6. Backend writes initial metadata, creates store state, and queues `process_job`.

### Job Progress

1. Backend continues to update `status`, `step`, `progress`, `step_started_at`, `updated_at`, and `stage_elapsed_seconds`.
2. Frontend polls job state as today.
3. Frontend derives the visual active stage from progress thresholds and step prefixes.
4. Frontend displays detailed `job.step` separately from the coarse step list.

### Note Versions And ZIP

1. Backend loads version indexes defensively.
2. Backend resolves version note/frame paths through job-relative safety checks.
3. Frontend fetches versions as today.
4. Active version changes call the existing PATCH endpoint with `active_version_id`.
5. ZIP inclusion toggles call the same PATCH endpoint with updated `selected_version_ids` and the current active version.
6. Backend rebuilds ZIP atomically.

## Error Handling

- Invalid job ids return client errors and never resolve to `OUTPUTS_ROOT`.
- Invalid version metadata is ignored or rejected at use time, not trusted.
- Corrupt version indexes do not break `/api/jobs`.
- CUDA readiness failures produce actionable messages and do not start doomed transcription jobs.
- Failed job creation cleans up newly created partial directories.
- Failed jobs continue to expose completed artifacts through the existing artifact system.

## Testing Plan

### Backend

Run targeted tests while implementing, then full suite:

- `python -m pytest backend/tests/test_job_validation.py`
- `python -m pytest backend/tests/test_job_history.py`
- `python -m pytest backend/tests/test_note_versions.py`
- `python -m pytest backend/tests`

New or updated tests should cover:

- Encoded dot job id cannot load or delete outputs root.
- Malicious version paths cannot escape job dir.
- Corrupt `versions.json` does not break history listing.
- Atomic ZIP/index behavior still creates valid outputs.
- CUDA local transcription job is rejected when runtime is not ready.
- Invalid `JobConfig` input does not leave an orphan job directory.

### Frontend

Run:

- `npm --prefix frontend run build`

Manual browser/desktop verification after implementation should cover:

- Main preflight summary states for missing key, missing model, CPU ready, CUDA not ready, and backend disconnected.
- Long-running step display using mocked or real progress state.
- Failed job recovery panel for jobs with partial artifacts.
- Full artifact list and download status messaging.
- Version ZIP inclusion toggles and active preview switching.

## Non-Goals

- No cloud sync, login, accounts, or multi-user queue.
- No new design system or landing page.
- No source-video playback in this phase.
- No subtitle editing in this phase.
- No full component refactor of `frontend/src/App.tsx`.
- No secret-storage redesign; the existing plaintext local settings behavior remains, with existing warnings.

## Acceptance Criteria

- The outputs root cannot be loaded, downloaded through, or deleted by using `.` or encoded dot as a job id.
- Malicious or corrupt note-version metadata cannot escape a job directory or break history listing.
- Version index and ZIP writes are atomic enough that normal interrupted writes do not leave a newly advertised half-written file.
- CUDA jobs do not start unless CUDA readiness checks pass, while CPU local transcription still works as before.
- Invalid job config validation happens before job-directory side effects.
- Main UI clearly shows readiness, active long-task progress, failed-job recovery options, all artifacts, and useful version metadata.
- Existing backend tests pass.
- Frontend production build passes.
