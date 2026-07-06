# Review Chunk Regeneration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let users fix weak note sections during `awaiting_note_review` by regenerating existing note chunks, then return to the review gate instead of creating an unreviewed ZIP.

**Architecture:** Reuse the existing `note_chunks` metadata and `/api/jobs/{job_id}/note-chunks/{chunk_id}/regenerate` endpoint. The regenerate worker should rebuild the active note version, regenerate frame candidates and quality reports, remove any stale ZIP, mark `.note-review.pending`, and return the job to `awaiting_note_review`.

**Tech Stack:** FastAPI background tasks, pytest, existing note chunk reduction, existing review/finalization helpers, React/Vite.

---

## File Structure

- Modify `backend/app/main.py`
  - Fix `_regenerate_chunk_job` so it creates a reviewed draft state instead of direct `succeeded`.
- Modify `backend/tests/test_review_finalization.py`
  - Add endpoint coverage for chunk regeneration returning to `awaiting_note_review`.
- Modify `frontend/src/App.tsx`
  - Fetch and show note chunks during both `awaiting_note_review` and `succeeded`.

---

### Task 1: Backend Chunk Regeneration Returns To Review

**Files:**
- Modify: `backend/app/main.py`
- Modify: `backend/tests/test_review_finalization.py`

- [ ] **Step 1: Write failing endpoint test**

Append to `backend/tests/test_review_finalization.py`:

```python
from backend.app.note_chunks import NoteChunkIndex, NoteChunkMeta, chunk_index_path, chunks_dir
from backend.app.models import Chapter, JobConfig, JobStatus, KeyMoment, NoteDraft, NoteLanguage, NoteStyle, TranscriptionMode


def seed_note_chunk_index(job_dir: Path) -> None:
    chunks_dir(job_dir).mkdir(parents=True, exist_ok=True)
    index = NoteChunkIndex(
        total_segments=1,
        chunks=[
            NoteChunkMeta(
                id="chunk_001",
                index=1,
                total=1,
                label="Chunk 1/1",
                start_time=0,
                end_time=1,
                segment_start=0,
                segment_end=0,
                status="succeeded",
                title="Old chunk",
            )
        ],
    )
    chunk_index_path(job_dir).write_text(index.model_dump_json(), encoding="utf-8")
    (chunks_dir(job_dir) / "chunk_001.json").write_text(
        NoteDraft(title="Old", summary="old").model_dump_json(),
        encoding="utf-8",
    )


def test_regenerate_note_chunk_returns_to_note_review(tmp_path, monkeypatch) -> None:
    outputs_root = tmp_path / "outputs"
    job_id = "chunk-review-job"
    job_dir = outputs_root / job_id
    job_dir.mkdir(parents=True)
    (job_dir / "source_video").mkdir()
    (job_dir / "source_video" / "input.mp4").write_bytes(b"video")
    (job_dir / "metadata.json").write_text(
        '{"original_filename":"input.mp4","duration_seconds":10}',
        encoding="utf-8",
    )
    (job_dir / "transcript.json").write_text(
        '{"text":"hello","segments":[{"start":0,"end":1,"text":"hello"}]}',
        encoding="utf-8",
    )
    (job_dir / "note.md").write_text("# Old", encoding="utf-8-sig")
    (job_dir / "download.zip").write_bytes(b"stale zip")
    mark_note_review_pending(job_dir)
    seed_note_chunk_index(job_dir)

    def fake_regenerate_chunk_and_reduce(*_args, **_kwargs) -> NoteDraft:
        return NoteDraft(
            title="Regenerated chunk",
            summary="summary",
            chapters=[Chapter(title="Opening", start_time=0, end_time=1, detail="New detail")],
            key_moments=[KeyMoment(time=0.5, reason="New frame", chapter_index=0)],
        )

    def fake_create_note_version_from_draft(*, job_dir, video_path, draft, duration, config, version_id=None):
        (job_dir / "note.md").write_text("# Regenerated chunk\n\n### Opening\n\n`00:00:00 - 00:00:01`\n\nNew detail\n", encoding="utf-8-sig")
        frames_dir = job_dir / "frames"
        frames_dir.mkdir(exist_ok=True)
        (frames_dir / "frame_001.jpg").write_bytes(b"jpg")

    def fake_build_frame_candidate_index(*_args, **_kwargs):
        return FrameCandidateIndex(candidates=[])

    store = JobStore(outputs_root)
    store.create(job_id)
    store.update(job_id, status=JobStatus.awaiting_note_review, step="等待复核笔记", progress=92)
    monkeypatch.setattr(main, "OUTPUTS_ROOT", outputs_root)
    monkeypatch.setattr(main, "store", store)
    monkeypatch.setattr(main, "regenerate_chunk_and_reduce", fake_regenerate_chunk_and_reduce)
    monkeypatch.setattr(main, "create_note_version_from_draft", fake_create_note_version_from_draft)
    monkeypatch.setattr(main, "build_frame_candidate_index", fake_build_frame_candidate_index)

    response = TestClient(app).post(
        f"/api/jobs/{job_id}/note-chunks/chunk_001/regenerate",
        data={
            "note_api_key": "key",
            "note_base_url": "https://api.openai.com/v1",
            "note_model": "gpt-5.5",
            "note_language": "zh",
            "note_style": "detailed",
            "frame_limit": "1",
        },
    )

    assert response.status_code == 200
    state = store.get(job_id)
    assert state is not None
    assert state.status == JobStatus.awaiting_note_review
    assert (job_dir / ".note-review.pending").exists()
    assert (job_dir / "review" / "quality_report.json").exists()
    assert (job_dir / "review" / "frame_candidates.json").exists()
    assert not (job_dir / "download.zip").exists()
```

- [ ] **Step 2: Run test and verify RED**

Run:

```bash
pytest backend/tests/test_review_finalization.py::test_regenerate_note_chunk_returns_to_note_review -q
```

Expected: FAIL because `_regenerate_chunk_job` currently creates ZIP / succeeds and imports a missing helper.

- [ ] **Step 3: Update `_regenerate_chunk_job`**

In `backend/app/main.py`:

- Import `create_note_version_from_draft` from `note_versions`.
- Import `mark_note_review_pending` from `review_finalization`.
- In `_regenerate_chunk_job`, remove stale `download.zip`.
- Use `find_source_video(job_dir)` and `create_note_version_from_draft(...)` with the regenerated draft.
- Rebuild `review/frame_candidates.json` with `build_frame_candidate_index` and `write_frame_candidate_index`.
- Rebuild `quality_report.*`.
- Call `mark_note_review_pending(job_dir)`.
- Refresh artifacts and update status to `JobStatus.awaiting_note_review`.
- Do not call `create_zip`.

- [ ] **Step 4: Run test and verify GREEN**

Run:

```bash
pytest backend/tests/test_review_finalization.py::test_regenerate_note_chunk_returns_to_note_review -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/main.py backend/tests/test_review_finalization.py
git commit -m "feat: return chunk regeneration to review"
```

---

### Task 2: Frontend Shows Chunks During Review

**Files:**
- Modify: `frontend/src/App.tsx`

- [ ] **Step 1: Update chunk fetch condition**

In `frontend/src/App.tsx`, change the note chunk effect so it fetches chunks when:

```ts
job.status === "succeeded" || job.status === "awaiting_note_review"
```

- [ ] **Step 2: Build frontend**

Run:

```bash
npm --prefix frontend run build
```

Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/App.tsx
git commit -m "feat: show chunks during note review"
```

---

### Task 3: Final Verification

**Files:**
- No new code files.

- [ ] **Step 1: Run focused tests**

Run:

```bash
pytest backend/tests/test_review_finalization.py backend/tests/test_processor.py -q
```

Expected: PASS.

- [ ] **Step 2: Run full backend suite and frontend build**

Run:

```bash
pytest backend/tests -q
npm --prefix frontend run build
```

Expected: both PASS.

---

## Self-Review Against Spec

- Users can fix weak note sections before finalization: covered through chunk regeneration during note review.
- Review approval remains required after regeneration: covered by returning to `awaiting_note_review` and not creating ZIP.
- Per-chapter regeneration remains future work; this uses existing chunk boundaries to avoid a larger schema rewrite.
