# Subtitle Confirmation Gate Design

## Summary

Today the job pipeline runs end to end in one background task: probe, extract audio, transcribe, write subtitles, generate notes, extract frames, write ZIP. The user wants a confirmation step after subtitles are generated. If quality is not acceptable, the user can regenerate subtitles; only after confirming do notes get generated.

## Goals

- After subtitles are written, the job pauses in a new state `awaiting_subtitle_confirmation` instead of continuing to notes.
- The user can confirm subtitles to continue into note generation.
- The user can regenerate subtitles (re-run transcription), which pauses again for confirmation.
- Resume after app restart must restore the awaiting state from disk.
- Keep existing endpoints, artifact layout, and the existing transcript-correction flow unchanged.
- Frontend shows a confirmation banner with "confirm and continue" and "regenerate subtitles" actions when the job is awaiting confirmation; subtitle preview is reused.

## Non-Goals

- No new transcription modes or note features.
- No change to the existing post-completion transcript correction modal.
- No change to ZIP contents or job history sorting.
- No A/B quality scoring; the decision is fully user-driven.

## Design

### Job Status

Add `JobStatus.awaiting_subtitle_confirmation`. The pipeline splits into two phases:

- Phase 1 `process_transcription_job`: probe duration, extract MP3, transcribe, write transcript + subtitles, write a marker file `subtitles.pending`, set status to `awaiting_subtitle_confirmation` with step `等待确认字幕`.
- Phase 2 `continue_job_to_notes`: remove `subtitles.pending`, generate note draft, create note version + frames, write metadata + ZIP, set status to `succeeded`.
- Regenerate `regenerate_subtitles_job`: remove prior notes/versions if any, re-run phase 1 transcription (re-extract audio from source video), pause again.

### Disk Inference

`JobStore.load_from_disk` / `_infer_disk_job_status`:
- note.md or any note version exists → `succeeded`
- subtitles exist and `subtitles.pending` marker exists → `awaiting_subtitle_confirmation`
- otherwise → `failed`

`load_from_disk` step text for the awaiting state is `等待确认字幕`.

### Endpoints

- `POST /api/jobs/{job_id}/subtitles/confirm` — only valid when status is `awaiting_subtitle_confirmation`. Enqueues phase 2, sets status to `running` (step `笔记生成`).
- `POST /api/jobs/{job_id}/subtitles/regenerate` — accepts transcription form fields (mode, api key, base url, model, local whisper device/compute type). Only valid when status is `awaiting_subtitle_confirmation`. Enqueues `regenerate_subtitles_job`, sets status to `running` (step `字幕生成`).

Both endpoints validate the current status and the presence of `source_video` and `transcript.json`/`subtitles` before enqueuing.

### Delete Guard

`delete_job` continues to block only `pending`/`running`. An awaiting job is paused and may be deleted.

### Frontend

- Add `awaiting_subtitle_confirmation` to the `JobStatus` union. Job polling already stops because it is neither `pending` nor `running`.
- Add a confirmation banner shown when `job.status === "awaiting_subtitle_confirmation"`. The subtitle preview effect already fetches subtitles when `subtitles.md` exists, so it is visible.
- Confirm button calls `/api/jobs/{job_id}/subtitles/confirm`, optimistically sets job to `running`.
- Regenerate button opens no new modal; it posts transcription params and optimistically sets job to `running` with step `字幕生成`. For local transcription the API key is not required.

## Error Handling

- Confirming/regenerating a job not in the awaiting state returns `409`.
- Missing source video or transcript returns `400`.
- Phase 2 failure sets status to `failed` exactly as today.
- Regenerate failure sets status back to `failed`.

## Tests

- Phase 1 job ends in `awaiting_subtitle_confirmation` with the marker file and subtitles, no note.md.
- Confirm transitions to running then succeeded; marker removed.
- Confirm on a non-awaiting job returns `409`.
- Regenerate re-runs transcription and pauses again; old notes removed.
- Disk inference marks a paused job as `awaiting_subtitle_confirmation` after reload.

## Verification

- `python -m pytest backend\tests -q`
- `pytest backend\tests -q`
- `npm --prefix frontend run build`
- `./scripts/build-desktop.ps1`
