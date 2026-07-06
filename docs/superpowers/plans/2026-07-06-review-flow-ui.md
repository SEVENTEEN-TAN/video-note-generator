# Review Flow UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement a simpler, coherent review flow with top-step progress, inline subtitle actions, modal frame review with context and multi-select, protected manual versions, readable progress labels, and title-based ZIP download naming.

**Architecture:** Keep the existing FastAPI + React shape. Add small backend fields/helpers for review context, manual-version snapshots, and download names; keep frontend changes inside the existing single-page app without introducing a router or large redesign.

**Tech Stack:** FastAPI, Pydantic, pytest, React, TypeScript, Vite, CSS.

---

## Files

- Modify `backend/app/models.py`: add `FrameCandidateChapterContext`, optional `FrameCandidateIndex.chapter_contexts`, and `JobPublicState.download_filename`.
- Modify `backend/app/processor.py`: replace corrupted progress strings.
- Modify `backend/app/job_store.py`: derive ZIP download filename and protect unmatched manual notes on disk load.
- Modify `backend/app/note_versions.py`: add manual version snapshot helpers.
- Modify `backend/app/frame_candidates.py`: build chapter context and allow multiple selected candidates per chapter.
- Modify `backend/app/review_finalization.py`: keep finalization behavior but align naming through UI.
- Modify `frontend/src/types.ts`: mirror backend type additions.
- Modify `frontend/src/App.tsx`: move progress to stepper, move subtitle actions to preview header, add frame review modal, update finalization wording, use ZIP filename.
- Modify `frontend/src/styles.css`: style top progress, subtitle title actions, review gate button, and frame modal.
- Modify tests under `backend/tests/`.

## Task 1: Backend Text And Download Metadata

- [ ] Write failing processor tests asserting readable progress labels after phase one, note continuation, subtitle regeneration, and failures.
- [ ] Run `pytest backend/tests/test_processor.py -q`; expected failure because labels currently include `????`.
- [ ] Replace `????` labels with `分析视频`, `音频分离`, `字幕生成`, `等待确认字幕`, `笔记生成`, `关键帧抽取`, and `失败`.
- [ ] Add `download_filename: str | None = None` to `JobPublicState`.
- [ ] Add a small filename sanitizer in `job_store.py` and set `download_filename` from metadata title when `download.zip` exists.
- [ ] Add API/history test proving `download_filename` becomes `<title>.zip`.
- [ ] Run `pytest backend/tests/test_processor.py backend/tests/test_job_history.py -q`; expected pass.
- [ ] Commit with `fix: restore progress labels and title zip names`.

## Task 2: Manual Note Protection

- [ ] Write failing note-version test for a disk job with root `note.md` and no matching version; loading from disk creates `manual_001` with label `manual_001 · 手工版本`.
- [ ] Write failing note-version test for root `note.md` differing from active version note; loading from disk creates the next manual version and makes it active.
- [ ] Add helpers in `note_versions.py`: `next_manual_version_id()`, `snapshot_root_note_as_manual_version()`, and `ensure_root_note_has_version()`.
- [ ] Call `ensure_root_note_has_version()` inside `JobStore.load_from_disk()` after artifacts and before state is returned.
- [ ] Run `pytest backend/tests/test_note_versions.py backend/tests/test_job_history.py -q`; expected pass.
- [ ] Commit with `feat: protect manually edited loaded notes`.

## Task 3: Frame Candidate Context And Multi-Select

- [ ] Write failing tests in `backend/tests/test_frame_candidates.py` proving two candidates in the same chapter can both be selected.
- [ ] Write failing tests proving selecting beyond the supplied frame limit raises a clear error.
- [ ] Add `FrameCandidateChapterContext` model with `chapter_index`, `title`, `start_time`, `end_time`, `note_excerpt`, and `subtitle_excerpt`.
- [ ] Populate `chapter_contexts` in `build_frame_candidate_index()` from parsed note chapters and transcript segments when available.
- [ ] Change `select_frame_candidate(job_dir, candidate_id, frame_limit=None)` so it toggles only the target candidate to selected and does not clear the rest of the chapter.
- [ ] Keep `reject_frame_candidate()` clearing selected for that candidate only.
- [ ] Update endpoint to pass frame limit from metadata.
- [ ] Run `pytest backend/tests/test_frame_candidates.py backend/tests/test_review_finalization.py -q`; expected pass.
- [ ] Commit with `feat: support contextual multi-select frame review`.

## Task 4: Frontend Review Flow

- [ ] Write/update `backend/tests/test_frontend_styles.py` to assert:
  - `.step-progress-bar` exists near `ProcessSteps`.
  - `.job-progress-bar` is no longer inside `.result-body-scroll`.
  - subtitle actions render inside `PreviewBlock` header.
  - inline `.frame-candidate-panel` is gone.
  - `.frame-review-modal` and `审核配图` entry button exist.
  - finalization copy says `确认定稿` and not `生成 ZIP`.
- [ ] Run `pytest backend/tests/test_frontend_styles.py -q`; expected failure before frontend edits.
- [ ] Update `types.ts` for `download_filename`, `chapter_contexts`, and chapter context type.
- [ ] Update `App.tsx`:
  - render top progress under `ProcessSteps`;
  - pass subtitle actions into `PreviewBlock`;
  - replace inline frame candidates with modal state and open button;
  - render contextual frame candidate modal;
  - show `确认定稿`;
  - pass `job.download_filename` to ZIP download button.
- [ ] Update `styles.css` with compact top progress and modal styles matching the existing operational UI.
- [ ] Run `pytest backend/tests/test_frontend_styles.py -q`; expected pass.
- [ ] Run `npm --prefix frontend run build`; expected pass.
- [ ] Commit with `feat: simplify review flow UI`.

## Task 5: Full Verification And Merge

- [ ] Run `pytest backend/tests -q`; expected all pass.
- [ ] Run `npm --prefix frontend run build`; expected pass.
- [ ] Inspect `git status --short --branch`; expected clean on `codex/review-flow-ui`.
- [ ] Merge branch into `main`.
- [ ] Run `pytest backend/tests -q` and `npm --prefix frontend run build` on `main`; expected pass.
- [ ] Clean the temporary worktree and delete the merged branch.
