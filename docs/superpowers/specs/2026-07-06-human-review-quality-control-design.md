# Human Review Quality Control Design

## Summary

The current pipeline can produce a complete video note package, but the user still has limited control over whether the note covers the right ideas and whether the extracted frames are useful, unique, and aligned with the text. The next product step is a human-in-the-loop quality layer: the system should generate drafts, surface quality risks, offer frame choices, and let the user approve or adjust the final package before the ZIP is finalized.

## Goals

- Give users explicit control over content quality without making them edit every line.
- Add a review stage between draft generation and final ZIP creation.
- Show coverage signals per chapter: transcript span, note density, frame count, and detected risks.
- Prevent repeated or near-duplicate frames from being selected by default.
- Let users select, reject, or replace frames before finalization.
- Let users mark chapter priorities before or during note generation.
- Keep existing artifacts such as `note.md`, `subtitles.md`, `transcript.json`, `frames/*.jpg`, and `download.zip` stable after final approval.
- Preserve the existing subtitle confirmation and transcript correction flows.

## Non-Goals

- No full video editor or frame-by-frame timeline editor.
- No multi-user review workflow.
- No mandatory external OCR or vision model dependency in the first implementation.
- No promise that the system can prove factual correctness without user review.
- No large redesign of the upload form or settings model.

## Product Flow

### 1. Subtitle Review

This keeps the existing `awaiting_subtitle_confirmation` gate. The user reviews the transcript/subtitles first because all downstream quality depends on this source material.

Enhancements:

- Surface subtitle risks: very long segments, empty spans, repeated filler text, and likely terminology issues.
- Keep the existing transcript correction path as the repair action.
- Continue to note planning only after the user confirms subtitles.

### 2. Outline Review

After subtitles are confirmed, the system generates an outline draft and pauses before writing the full note.

The outline review shows:

- Chapter title.
- Time range.
- Transcript character count.
- Key terms detected in that range.
- Suggested priority: normal, focus, or brief.
- User instruction field per chapter.

User actions:

- Confirm the outline as-is.
- Mark a chapter as focus or brief.
- Add chapter-specific instructions.
- Request outline regeneration.

The MVP does not need draggable timeline editing. Splitting and merging chapters can be deferred unless the generated outline is unusable.

### 3. Draft Note And Frame Review

After outline approval, the system generates a draft note version and a frame candidate set. The job enters a new review state instead of immediately producing the final ZIP.

The review workbench shows:

- Overall quality status: ready, review recommended, or needs attention.
- Chapter coverage cards.
- Draft note preview.
- Frame candidates per chapter.
- Issues such as duplicate frames, missing frames, low coverage, and model fallback events.

User actions:

- Approve the final version.
- Regenerate one chapter.
- Add a short instruction to one chapter and regenerate only that chapter.
- Select a different frame candidate.
- Reject a frame.
- Ask the system to find another frame for that chapter.

### 4. Finalization

Only after the user approves the review state does the app:

- Copy selected frames into `frames/`.
- Render the final `note.md` with those selected frame paths.
- Write `quality_report.json` and `quality_report.md`.
- Rebuild `download.zip`.
- Set the job to `succeeded`.

## Job States

Add two states:

- `awaiting_outline_review`: subtitles are confirmed and an outline draft exists.
- `awaiting_note_review`: a note draft, quality report, and frame candidates exist, but final artifacts are not approved.

The existing `succeeded` state means the user-approved ZIP exists.

Disk inference should treat these states as resumable paused states, like the subtitle confirmation gate. Marker files keep inference simple:

- `.outline-review.pending`
- `.note-review.pending`

## Artifact Layout

Draft and review artifacts live under a review directory so final artifacts stay stable:

```text
review/
  outline.json
  review_state.json
  quality_report.json
  quality_report.md
  frame_candidates/
    chapter_001/
      candidate_001.jpg
      candidate_002.jpg
  frame_candidates.json
```

Final approved artifacts remain:

```text
note.md
frames/*.jpg
download.zip
```

## Data Model

### Review State

```json
{
  "outline_confirmed": true,
  "note_confirmed": false,
  "chapter_priorities": [
    {"chapter_index": 0, "priority": "focus", "instruction": "Emphasize VGG vs ResNet."}
  ],
  "selected_frame_ids": ["chapter_001_candidate_002"],
  "rejected_frame_ids": ["chapter_001_candidate_001"]
}
```

### Quality Report

```json
{
  "status": "review_recommended",
  "scores": {
    "coverage": 0.82,
    "structure": 0.78,
    "frames": 0.64,
    "stability": 0.72
  },
  "chapter_reports": [
    {
      "chapter_index": 0,
      "title": "Deep learning basics",
      "start_time": 38.0,
      "end_time": 874.0,
      "transcript_chars": 4200,
      "note_chars": 900,
      "selected_frame_count": 2,
      "issues": []
    }
  ],
  "issues": [
    {
      "severity": "warning",
      "type": "duplicate_frame",
      "message": "Two selected frames appear visually similar.",
      "chapter_index": 5,
      "frame_ids": ["chapter_006_candidate_001", "chapter_006_candidate_003"]
    }
  ]
}
```

### Frame Candidate

```json
{
  "id": "chapter_006_candidate_002",
  "chapter_index": 5,
  "time": 8792.0,
  "path": "review/frame_candidates/chapter_006/candidate_002.jpg",
  "reason": "Batch Normalization formula and learned gamma/beta parameters",
  "source": "near_model_moment",
  "hash": "ff80c1...",
  "duplicate_of": null,
  "similarity": 0.18,
  "risk_flags": [],
  "selected": true
}
```

## Frame Candidate And De-Duplication Strategy

The frame system should stop treating one model timestamp as one final image. It should generate candidates, score them, and select non-repeating frames.

For each chapter:

1. Start with model-proposed key moments.
2. Add fallback chapter positions: early, middle, late.
3. Around each moment, extract nearby candidates, for example `t - 20s`, `t - 10s`, `t`, `t + 10s`, `t + 20s`, clamped to chapter bounds.
4. Compute a lightweight visual hash for each candidate.
5. Reject exact or near-duplicate candidates before default selection.
6. Prefer candidates that are not too close to chapter boundaries.
7. Prefer candidates whose surrounding transcript lines contain terms related to the chapter reason.
8. If all candidates are duplicate or weak, leave the chapter under-framed and flag it instead of forcing a poor frame.

The first implementation can compute visual hashes without adding a heavy dependency:

- Use FFmpeg to downsample each image to a tiny grayscale raw frame.
- Compute an average hash or difference hash in Python.
- Compare Hamming distance to detect near-duplicates.

Future optional improvement:

- Use OCR or a multimodal model to compare visible slide text against the frame reason. This should be optional because it adds dependency and provider complexity.

## Content Quality Controls

The quality layer should focus on signals that can be measured locally and explained to the user:

- Coverage balance: long transcript chapters should not produce tiny note sections.
- Missing coverage: every chapter should have at least one paragraph or meaningful bullets.
- Over-condensation: a long chapter with very few note characters is flagged.
- Repetition: repeated chapter titles, repeated frames, and repeated generated paragraphs are flagged.
- Generation stability: model retries, fallback merges, invalid JSON, and content policy failures lower the stability score.
- Source evidence: every chapter should keep timestamp references.

The report should not claim the note is factually perfect. It should say what the system checked and what still needs human judgment.

## Backend Changes

- Add review state models to `backend/app/models.py`.
- Add a review module, for example `backend/app/review_quality.py`, to build coverage and stability reports.
- Add a frame candidate module, for example `backend/app/frame_candidates.py`, to extract candidate frames, hash them, score them, and persist candidate metadata.
- Adjust `processor.py` so subtitle confirmation leads to outline generation and `awaiting_outline_review`.
- Add note review generation after outline approval, ending in `awaiting_note_review`.
- Add finalization logic that writes final artifacts and creates the ZIP only after approval.
- Keep existing note versioning. A reviewed draft can still be stored as a note version, but final `note.md` should reflect the approved frame selections.

## API Changes

- `GET /api/jobs/{job_id}/outline-review`
- `POST /api/jobs/{job_id}/outline-review/confirm`
- `POST /api/jobs/{job_id}/outline-review/regenerate`
- `GET /api/jobs/{job_id}/quality-report`
- `GET /api/jobs/{job_id}/frame-candidates`
- `POST /api/jobs/{job_id}/frame-candidates/{candidate_id}/select`
- `POST /api/jobs/{job_id}/frame-candidates/{candidate_id}/reject`
- `POST /api/jobs/{job_id}/chapters/{chapter_index}/regenerate`
- `POST /api/jobs/{job_id}/finalize`

Endpoints that mutate review state should return the updated job state plus the relevant review payload so the frontend can refresh without waiting for another poll.

## Frontend Changes

Add a review workbench to the existing single-page app rather than creating a separate route.

When `job.status === "awaiting_outline_review"`:

- Show outline cards.
- Allow priority selection: normal, focus, brief.
- Allow chapter instruction text.
- Confirm or regenerate outline.

When `job.status === "awaiting_note_review"`:

- Show overall quality status and scores.
- Show chapter cards with issues.
- Show note preview.
- Show candidate frame strips per chapter.
- Allow select, reject, replace, and finalize actions.

The UI should keep the current product tone: dense, operational, and review-oriented. Avoid marketing-style empty states.

## Error Handling

- Finalize without a confirmed note review returns `409`.
- Selecting a duplicate-risk frame is allowed, but the UI keeps the warning visible.
- If frame candidate extraction fails for a chapter, the chapter remains reviewable with a missing-frame warning.
- If chapter regeneration fails, keep the previous draft and show the error in the review state.
- If review files are partially missing on reload, infer the closest safe paused state and ask the user to regenerate the missing review artifacts.

## Testing

Backend:

- Quality report flags low note coverage for a long chapter.
- Quality report records model fallback events from `debug.log`.
- Frame hashing detects identical and near-identical frames.
- Frame candidate selection avoids duplicates by default.
- Job pauses at `awaiting_outline_review` and resumes from disk.
- Job pauses at `awaiting_note_review` and resumes from disk.
- Finalize writes `note.md`, selected frames, `quality_report.*`, and `download.zip`.
- Finalize on an unapproved job returns `409`.

Frontend:

- Outline review renders chapter cards and posts confirmation.
- Note review renders quality issues and frame candidates.
- Selecting/rejecting frame candidates updates the preview state.
- Finalize action transitions the job to running and then succeeded.

## Rollout Plan

1. Implement backend-only quality report for completed jobs, with no pipeline state changes.
2. Add frame candidate extraction and duplicate detection.
3. Add `awaiting_note_review` and finalization approval.
4. Add outline review after the note review path is stable.

This order gives immediate value while keeping the first implementation small enough to verify.

## Success Criteria

- Users can see why a generated note is or is not ready.
- Users can approve final output instead of receiving an unreviewed ZIP automatically.
- Duplicate frames are not selected by default.
- A chapter with weak coverage or missing frames is flagged before download.
- Users can fix the highest-value issues without regenerating the entire job.
