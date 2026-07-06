# Note Review Finalization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the approval gate that pauses completed note drafts at `awaiting_note_review` and only builds the final ZIP after the user confirms the reviewed note and selected frames.

**Architecture:** Keep the existing subtitle confirmation gate and note version system. After note generation, the backend writes draft `note.md`, frame candidates, and quality reports, then writes `.note-review.pending` and returns `awaiting_note_review` without creating `download.zip`. A new finalization helper applies selected frame candidates to `frames/` and `note.md`, refreshes `quality_report.*`, rebuilds `download.zip`, removes the marker, and sets the job to `succeeded`.

**Tech Stack:** FastAPI, Pydantic v2, pytest, existing note versioning, existing React/Vite frontend.

---

## File Structure

- Modify `backend/app/models.py`
  - Add `awaiting_note_review` to `JobStatus`.
- Create `backend/app/review_finalization.py`
  - Owns `.note-review.pending`, selected-frame application, final `note.md` rendering, and note version synchronization.
- Modify `backend/app/processor.py`
  - Include review artifacts in ZIP.
  - Pause `continue_job_to_notes` at `awaiting_note_review`.
  - Clear stale review artifacts when regenerating subtitles.
- Modify `backend/app/job_store.py`
  - Infer `awaiting_note_review` from `.note-review.pending`.
  - Preserve paused-state wording for disk-loaded jobs.
- Modify `backend/app/main.py`
  - Add `POST /api/jobs/{job_id}/finalize`.
  - Use finalization helper and return refreshed `JobPublicState`.
- Create `backend/tests/test_review_finalization.py`
  - Cover applying selected candidates, marker checks, and finalization API.
- Modify `backend/tests/test_processor.py`
  - Update note-generation expectations from immediate `succeeded` to `awaiting_note_review`.
- Modify `backend/tests/test_job_history.py`
  - Cover disk inference of `awaiting_note_review`.
- Modify `frontend/src/types.ts`
  - Add `awaiting_note_review` to `JobStatus`.
- Modify `frontend/src/constants.ts`
  - Add display text for `awaiting_note_review`.
- Modify `frontend/src/api.ts`
  - Add `finalizeJob(jobId)`.
- Modify `frontend/src/App.tsx`
  - Show a confirm-finalize action during note review.

---

## Scope Guard

This phase does not add outline review or per-chapter text regeneration. It does make the user approval meaningful: `download.zip` is no longer created until the user confirms the reviewed draft and frame choices.

---

### Task 1: Add Note Review Status And Disk Inference

**Files:**
- Modify: `backend/app/models.py`
- Modify: `backend/app/job_store.py`
- Modify: `backend/tests/test_job_history.py`

- [ ] **Step 1: Write failing disk inference test**

Append to `backend/tests/test_job_history.py`:

```python
def test_get_job_loads_note_review_pending_state_from_disk(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(main, "OUTPUTS_ROOT", tmp_path)
    monkeypatch.setattr(main, "store", JobStore(tmp_path))
    write_history_job(
        tmp_path,
        "note-review-job",
        created_at="2026-07-06T00:00:00+00:00",
        title="Review",
        original_filename="review.mp4",
    )
    (tmp_path / "note-review-job" / ".note-review.pending").write_text("1", encoding="utf-8")

    response = TestClient(app).get("/api/jobs/note-review-job")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "awaiting_note_review"
    assert payload["progress"] == 92
```

- [ ] **Step 2: Run test and verify RED**

Run:

```bash
pytest backend/tests/test_job_history.py::test_get_job_loads_note_review_pending_state_from_disk -q
```

Expected: FAIL because `awaiting_note_review` is not a valid `JobStatus` and disk inference returns `succeeded`.

- [ ] **Step 3: Add status and disk inference**

In `backend/app/models.py`, add:

```python
awaiting_note_review = "awaiting_note_review"
```

In `backend/app/job_store.py`:

- In `_infer_disk_job_status`, before checking `note.md`, return `JobStatus.awaiting_note_review` when `(job_dir / ".note-review.pending").exists()`.
- In `load_from_disk`, add paused wording and no error for `JobStatus.awaiting_note_review`.
- Set progress to `92` for `awaiting_note_review` and `100` for terminal loaded states.

- [ ] **Step 4: Run test and verify GREEN**

Run:

```bash
pytest backend/tests/test_job_history.py::test_get_job_loads_note_review_pending_state_from_disk -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/models.py backend/app/job_store.py backend/tests/test_job_history.py
git commit -m "feat: infer note review state"
```

---

### Task 2: Apply Selected Frame Candidates To Final Note

**Files:**
- Create: `backend/app/review_finalization.py`
- Create: `backend/tests/test_review_finalization.py`

- [ ] **Step 1: Write failing finalization helper tests**

Create `backend/tests/test_review_finalization.py`:

```python
from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend.app.models import FrameCandidate, FrameCandidateIndex
from backend.app.review_finalization import (
    NOTE_REVIEW_PENDING_MARKER,
    finalize_reviewed_note,
    mark_note_review_pending,
)
from backend.app.frame_candidates import write_frame_candidate_index


def seed_review_job(job_dir: Path) -> None:
    (job_dir / "note.md").write_text(
        "\n".join(
            [
                "# Demo",
                "",
                "### Intro",
                "",
                "`00:00:00 - 00:01:00`",
                "",
                "![old](frames/frame_001.jpg)",
                "",
                "> 关键帧：`00:00:10`：old",
                "",
                "Intro detail.",
                "",
                "### Advanced",
                "",
                "`00:01:00 - 00:02:00`",
                "",
                "Advanced detail.",
            ]
        ),
        encoding="utf-8-sig",
    )
    (job_dir / "frames").mkdir()
    (job_dir / "frames" / "frame_001.jpg").write_bytes(b"old")
    (job_dir / "review" / "frame_candidates" / "chapter_001").mkdir(parents=True)
    (job_dir / "review" / "frame_candidates" / "chapter_001" / "candidate_001.jpg").write_bytes(b"new-one")
    (job_dir / "review" / "frame_candidates" / "chapter_002").mkdir(parents=True)
    (job_dir / "review" / "frame_candidates" / "chapter_002" / "candidate_001.jpg").write_bytes(b"new-two")
    write_frame_candidate_index(
        job_dir,
        FrameCandidateIndex(
            candidates=[
                FrameCandidate(
                    id="chapter_001_candidate_001",
                    chapter_index=0,
                    time=15,
                    path="review/frame_candidates/chapter_001/candidate_001.jpg",
                    reason="Selected intro frame",
                    source="chapter_fallback",
                    hash="a",
                    similarity=0,
                    selected=True,
                ),
                FrameCandidate(
                    id="chapter_002_candidate_001",
                    chapter_index=1,
                    time=75,
                    path="review/frame_candidates/chapter_002/candidate_001.jpg",
                    reason="Selected advanced frame",
                    source="chapter_fallback",
                    hash="b",
                    similarity=0,
                    selected=True,
                ),
            ]
        ),
    )


def test_finalize_reviewed_note_applies_selected_frames_and_removes_marker(tmp_path) -> None:
    seed_review_job(tmp_path)
    mark_note_review_pending(tmp_path)

    finalize_reviewed_note(tmp_path)

    assert not (tmp_path / NOTE_REVIEW_PENDING_MARKER).exists()
    assert (tmp_path / "frames" / "frame_001.jpg").read_bytes() == b"new-one"
    assert (tmp_path / "frames" / "frame_002.jpg").read_bytes() == b"new-two"
    note_text = (tmp_path / "note.md").read_text(encoding="utf-8-sig")
    assert "![Selected intro frame](frames/frame_001.jpg)" in note_text
    assert "![Selected advanced frame](frames/frame_002.jpg)" in note_text
    assert "![old](frames/frame_001.jpg)" not in note_text


def test_finalize_reviewed_note_requires_pending_marker(tmp_path) -> None:
    seed_review_job(tmp_path)

    with pytest.raises(PermissionError):
        finalize_reviewed_note(tmp_path)
```

- [ ] **Step 2: Run tests and verify RED**

Run:

```bash
pytest backend/tests/test_review_finalization.py -q
```

Expected: FAIL because `backend.app.review_finalization` does not exist.

- [ ] **Step 3: Create finalization helper**

Create `backend/app/review_finalization.py` with:

```python
from __future__ import annotations

import shutil
from collections import defaultdict
from pathlib import Path

from .frame_candidates import load_frame_candidate_index
from .models import FrameCandidate
from .note_versions import load_note_version_index, resolve_job_relative_path
from .time_utils import seconds_to_hhmmss


NOTE_REVIEW_PENDING_MARKER = ".note-review.pending"


def mark_note_review_pending(job_dir: Path) -> None:
    (job_dir / NOTE_REVIEW_PENDING_MARKER).write_text("1", encoding="utf-8")


def is_note_review_pending(job_dir: Path) -> bool:
    return (job_dir / NOTE_REVIEW_PENDING_MARKER).exists()


def finalize_reviewed_note(job_dir: Path) -> None:
    marker = job_dir / NOTE_REVIEW_PENDING_MARKER
    if not marker.exists():
        raise PermissionError("note review is not pending.")
    selected = _selected_candidates(job_dir)
    if not selected:
        raise ValueError("No selected frame candidates.")
    frame_map = _copy_selected_frames(job_dir, selected)
    source_note = (job_dir / "note.md").read_text(encoding="utf-8-sig")
    final_note = _render_note_with_selected_frames(source_note, selected, frame_map)
    (job_dir / "note.md").write_text(final_note, encoding="utf-8-sig")
    _sync_active_note_version(job_dir, final_note)
    marker.unlink()
```

Required helper behavior:

- `_selected_candidates(job_dir)` loads `review/frame_candidates.json`, filters `selected and not rejected`, and sorts by `(chapter_index, time, id)`.
- `_copy_selected_frames(job_dir, selected)` rebuilds `frames/` from selected candidate image paths as `frames/frame_001.jpg`, `frames/frame_002.jpg`, and returns `{candidate.id: "frames/frame_001.jpg"}`.
- `_render_note_with_selected_frames(note_text, selected, frame_map)` parses `###` sections, removes markdown image lines and adjacent `> 关键帧...` lines, then inserts selected candidate markdown after the chapter time range.
- `_sync_active_note_version(job_dir, final_note)` writes the final note and copies root `frames/` into the active note version paths when an active version exists and its paths are safe.

- [ ] **Step 4: Run tests and verify GREEN**

Run:

```bash
pytest backend/tests/test_review_finalization.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/review_finalization.py backend/tests/test_review_finalization.py
git commit -m "feat: finalize reviewed notes"
```

---

### Task 3: Pause Processor At Note Review And Include Review Artifacts In ZIP

**Files:**
- Modify: `backend/app/processor.py`
- Modify: `backend/tests/test_processor.py`
- Modify: `backend/tests/test_review_finalization.py`

- [ ] **Step 1: Update processor tests for note review pause**

In `backend/tests/test_processor.py`:

- Update successful note generation assertions to expect `JobStatus.awaiting_note_review`.
- Assert `.note-review.pending`, `review/quality_report.json`, and `review/frame_candidates.json` exist.
- Assert `download.zip` does not exist before finalization.
- Replace debug expectation `create_zip` with `await_note_review`.

Add a focused ZIP test to `backend/tests/test_review_finalization.py`:

```python
from zipfile import ZipFile

from backend.app.processor import create_zip


def test_create_zip_includes_review_reports(tmp_path) -> None:
    (tmp_path / "note.md").write_text("# Demo", encoding="utf-8")
    (tmp_path / "review").mkdir()
    (tmp_path / "review" / "quality_report.json").write_text("{}", encoding="utf-8")
    (tmp_path / "review" / "quality_report.md").write_text("# Quality Report", encoding="utf-8")
    (tmp_path / "review" / "frame_candidates.json").write_text('{"candidates":[]}', encoding="utf-8")

    zip_path = create_zip(tmp_path)

    with ZipFile(zip_path) as archive:
        names = set(archive.namelist())

    assert "review/quality_report.json" in names
    assert "review/quality_report.md" in names
    assert "review/frame_candidates.json" in names
```

- [ ] **Step 2: Run tests and verify RED**

Run:

```bash
pytest backend/tests/test_processor.py backend/tests/test_review_finalization.py::test_create_zip_includes_review_reports -q
```

Expected: FAIL because processor still creates ZIP immediately and ZIP omits review reports.

- [ ] **Step 3: Update processor**

In `backend/app/processor.py`:

- Import `build_frame_candidate_index`, `write_frame_candidate_index`, `build_quality_report`, `write_quality_report`, and `mark_note_review_pending`.
- In `create_zip`, add existing `review/quality_report.json`, `review/quality_report.md`, and `review/frame_candidates.json` to the archive.
- In `continue_job_to_notes`, after `create_note_version_from_draft` and `store.refresh_artifacts(job_id)`:
  - build and write frame candidates
  - build and write quality report
  - call `mark_note_review_pending(job_dir)`
  - refresh artifacts
  - update state to `JobStatus.awaiting_note_review`, step `"等待复核笔记"`, progress `92`
  - log `await_note_review`
  - return without `create_zip`
- In `regenerate_subtitles_job`, remove stale `.note-review.pending` and `review/` together with old notes.

- [ ] **Step 4: Run tests and verify GREEN**

Run:

```bash
pytest backend/tests/test_processor.py backend/tests/test_review_finalization.py::test_create_zip_includes_review_reports -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/processor.py backend/tests/test_processor.py backend/tests/test_review_finalization.py
git commit -m "feat: pause jobs for note review"
```

---

### Task 4: Add Finalize API

**Files:**
- Modify: `backend/app/main.py`
- Modify: `backend/tests/test_review_finalization.py`

- [ ] **Step 1: Add failing API tests**

Append to `backend/tests/test_review_finalization.py`:

```python
from fastapi.testclient import TestClient

from backend.app import main
from backend.app.job_store import JobStore
from backend.app.main import app


def test_finalize_endpoint_writes_zip_and_returns_succeeded_state(tmp_path, monkeypatch) -> None:
    outputs_root = tmp_path / "outputs"
    job_id = "finalize-job"
    job_dir = outputs_root / job_id
    job_dir.mkdir(parents=True)
    seed_review_job(job_dir)
    (job_dir / "transcript.json").write_text('{"text":"hello","segments":[{"start":0,"end":1,"text":"hello"}]}', encoding="utf-8")
    mark_note_review_pending(job_dir)
    store = JobStore(outputs_root)
    store.create(job_id)
    store.update(job_id, status=main.JobStatus.awaiting_note_review, step="等待复核笔记", progress=92)
    monkeypatch.setattr(main, "OUTPUTS_ROOT", outputs_root)
    monkeypatch.setattr(main, "store", store)

    response = TestClient(app).post(f"/api/jobs/{job_id}/finalize")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "succeeded"
    assert (job_dir / "download.zip").exists()
    assert (job_dir / "review" / "quality_report.json").exists()


def test_finalize_endpoint_rejects_job_without_pending_review(tmp_path, monkeypatch) -> None:
    outputs_root = tmp_path / "outputs"
    job_id = "not-pending-finalize"
    job_dir = outputs_root / job_id
    job_dir.mkdir(parents=True)
    seed_review_job(job_dir)
    monkeypatch.setattr(main, "OUTPUTS_ROOT", outputs_root)
    monkeypatch.setattr(main, "store", JobStore(outputs_root))

    response = TestClient(app).post(f"/api/jobs/{job_id}/finalize")

    assert response.status_code == 409
```

- [ ] **Step 2: Run tests and verify RED**

Run:

```bash
pytest backend/tests/test_review_finalization.py::test_finalize_endpoint_writes_zip_and_returns_succeeded_state backend/tests/test_review_finalization.py::test_finalize_endpoint_rejects_job_without_pending_review -q
```

Expected: FAIL with 404 for missing endpoint.

- [ ] **Step 3: Add finalize endpoint**

In `backend/app/main.py`:

- Import `finalize_reviewed_note` and `is_note_review_pending`.
- Add:

```python
@app.post("/api/jobs/{job_id}/finalize", response_model=JobPublicState)
def finalize_job(job_id: str) -> JobPublicState:
    job_dir = safe_job_dir(job_id)
    if not is_note_review_pending(job_dir):
        raise HTTPException(status_code=409, detail="note review is not pending.")
    try:
        finalize_reviewed_note(job_dir)
        report = build_quality_report(job_dir)
        write_quality_report(job_dir, report)
        create_zip(job_dir)
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    store.refresh_artifacts(job_id)
    if not store.get(job_id):
        store.load_from_disk(job_id)
    store.update(job_id, status=JobStatus.succeeded, step="完成", progress=100, error="")
    state = store.get(job_id)
    if not state:
        raise HTTPException(status_code=404, detail="Job not found.")
    return state
```

- [ ] **Step 4: Run tests and verify GREEN**

Run:

```bash
pytest backend/tests/test_review_finalization.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/main.py backend/tests/test_review_finalization.py
git commit -m "feat: add finalize endpoint"
```

---

### Task 5: Add Frontend Finalize Action

**Files:**
- Modify: `frontend/src/types.ts`
- Modify: `frontend/src/constants.ts`
- Modify: `frontend/src/api.ts`
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/styles.css`

- [ ] **Step 1: Add frontend state and API helper**

Make these edits:

- `frontend/src/types.ts`: add `"awaiting_note_review"` to `JobStatus`.
- `frontend/src/constants.ts`: add `awaiting_note_review: "待复核笔记"`.
- `frontend/src/api.ts`: add:

```ts
export async function finalizeJob(jobId: string): Promise<JobState> {
  const response = await fetch(`/api/jobs/${jobId}/finalize`, { method: "POST" });
  if (!response.ok) {
    throw new Error(await readResponseError(response, "确认定稿失败。"));
  }
  return response.json();
}
```

- [ ] **Step 2: Add App finalize UI**

In `frontend/src/App.tsx`:

- Import `finalizeJob`.
- Add state:

```ts
const [isFinalizingJob, setIsFinalizingJob] = useState(false);
const [finalizeError, setFinalizeError] = useState("");
```

- Include `isFinalizingJob` in `isBusy`.
- Add `handleFinalizeJob` that calls `finalizeJob(job.job_id)`, updates `job`, clears errors, and refreshes history.
- In the result panel when `job.status === "awaiting_note_review"`, render a compact `note-review-gate` with one primary button: `"确认定稿并生成 ZIP"`.

- [ ] **Step 3: Run frontend build**

Run:

```bash
npm --prefix frontend run build
```

Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/types.ts frontend/src/constants.ts frontend/src/api.ts frontend/src/App.tsx frontend/src/styles.css
git commit -m "feat: confirm reviewed notes in frontend"
```

---

### Task 6: Final Verification

**Files:**
- No new code files.

- [ ] **Step 1: Run focused review tests**

Run:

```bash
pytest backend/tests/test_review_finalization.py backend/tests/test_frame_candidates.py backend/tests/test_review_quality.py -q
```

Expected: PASS.

- [ ] **Step 2: Run broader backend tests**

Run:

```bash
pytest backend/tests/test_processor.py backend/tests/test_job_history.py backend/tests/test_job_validation.py backend/tests/test_note_versions.py -q
```

Expected: PASS.

- [ ] **Step 3: Run full backend suite**

Run:

```bash
pytest backend/tests -q
```

Expected: PASS.

- [ ] **Step 4: Run frontend build**

Run:

```bash
npm --prefix frontend run build
```

Expected: PASS.

- [ ] **Step 5: Inspect git status**

Run:

```bash
git status --short --branch
```

Expected: clean branch.

---

## Self-Review Against Spec

- User approval before final ZIP: covered.
- `awaiting_note_review`: covered.
- Selected frames applied to final `frames/` and `note.md`: covered.
- Quality report written before ZIP: covered.
- Duplicate frame defaults: already covered by phase 2 and preserved.
- Outline review: explicitly deferred to the next rollout slice.
