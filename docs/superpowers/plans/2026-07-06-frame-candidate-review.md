# Frame Candidate Review Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the second human-review slice: generate non-repetitive frame candidates for completed jobs, persist user select/reject choices, and show those choices in the frontend review area.

**Architecture:** This extends the existing phase-1 quality report without changing job states or final ZIP behavior yet. A new backend module extracts candidate frames under `review/frame_candidates/`, computes lightweight hashes, marks near-duplicates, selects non-duplicate defaults, and stores `review/frame_candidates.json`. The API exposes the candidate list plus select/reject mutations; the frontend renders grouped candidate strips beside the quality panel so the user can participate before the later finalization phase.

**Tech Stack:** FastAPI, Pydantic v2, pytest, existing FFmpeg frame extraction, Vite React TypeScript.

---

## File Structure

- Modify `backend/app/models.py`
  - Add `FrameCandidate` and `FrameCandidateIndex` response models.
- Create `backend/app/frame_candidates.py`
  - Owns candidate time generation, frame extraction, perceptual hash comparison, default selection, persistence, and select/reject mutation helpers.
- Modify `backend/app/main.py`
  - Add `GET /api/jobs/{job_id}/frame-candidates`.
  - Add `POST /api/jobs/{job_id}/frame-candidates/{candidate_id}/select`.
  - Add `POST /api/jobs/{job_id}/frame-candidates/{candidate_id}/reject`.
- Modify `backend/app/job_store.py`
  - Add `review/frame_candidates.json` to job artifacts when present.
- Create `backend/tests/test_frame_candidates.py`
  - Cover model shape, candidate generation, duplicate default selection, persistence, and select/reject mutation.
- Modify `backend/tests/test_job_history.py`
  - Cover artifact listing for `review/frame_candidates.json`.
- Modify `frontend/src/types.ts`
  - Add frame candidate types.
- Modify `frontend/src/api.ts`
  - Add fetch/select/reject helpers.
- Modify `frontend/src/App.tsx`
  - Fetch candidates for jobs with `note.md`, show candidate strips grouped by chapter, and wire select/reject buttons.
- Modify `frontend/src/styles.css`
  - Add compact review-oriented styling for frame candidate strips.

---

## Scope Guard

This phase intentionally does not introduce `awaiting_note_review`, does not rewrite `note.md`, and does not rebuild `download.zip` from selected candidates. User choices are persisted in `review/frame_candidates.json` so the next phase can use them for finalization. This keeps the change small enough to verify while directly moving toward the user's requirements: users can inspect and choose frames, and repeated frames are not selected by default.

---

### Task 1: Add Frame Candidate Models

**Files:**
- Modify: `backend/app/models.py`
- Create: `backend/tests/test_frame_candidates.py`

- [ ] **Step 1: Write the failing model serialization test**

Create `backend/tests/test_frame_candidates.py`:

```python
from __future__ import annotations

from backend.app.models import FrameCandidate, FrameCandidateIndex


def test_frame_candidate_models_serialize_expected_shape() -> None:
    index = FrameCandidateIndex(
        candidates=[
            FrameCandidate(
                id="chapter_001_candidate_001",
                chapter_index=0,
                time=12.5,
                path="review/frame_candidates/chapter_001/candidate_001.jpg",
                reason="Opening concept slide",
                source="chapter_fallback",
                hash="010101",
                duplicate_of=None,
                similarity=0.0,
                risk_flags=[],
                selected=True,
                rejected=False,
            )
        ]
    )

    payload = index.model_dump(mode="json")

    assert payload["candidates"][0]["id"] == "chapter_001_candidate_001"
    assert payload["candidates"][0]["selected"] is True
    assert payload["candidates"][0]["risk_flags"] == []
```

- [ ] **Step 2: Run the model test and verify RED**

Run:

```bash
pytest backend/tests/test_frame_candidates.py::test_frame_candidate_models_serialize_expected_shape -q
```

Expected: FAIL with an import error for `FrameCandidate` or `FrameCandidateIndex`.

- [ ] **Step 3: Add the Pydantic models**

In `backend/app/models.py`, after `QualityReport`, add:

```python
class FrameCandidate(BaseModel):
    id: str
    chapter_index: int
    time: float
    path: str
    reason: str
    source: Literal["note_key_moment", "chapter_fallback"]
    hash: str
    duplicate_of: str | None = None
    similarity: float = Field(ge=0, le=1)
    risk_flags: list[str] = Field(default_factory=list)
    selected: bool = False
    rejected: bool = False


class FrameCandidateIndex(BaseModel):
    candidates: list[FrameCandidate] = Field(default_factory=list)
```

- [ ] **Step 4: Run the model test and verify GREEN**

Run:

```bash
pytest backend/tests/test_frame_candidates.py::test_frame_candidate_models_serialize_expected_shape -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/models.py backend/tests/test_frame_candidates.py
git commit -m "feat: add frame candidate models"
```

---

### Task 2: Build Candidate Generation And De-Duplication

**Files:**
- Create: `backend/app/frame_candidates.py`
- Modify: `backend/tests/test_frame_candidates.py`

- [ ] **Step 1: Add candidate generation tests**

Append to `backend/tests/test_frame_candidates.py`:

```python
import json
from pathlib import Path

from backend.app.frame_candidates import (
    build_frame_candidate_index,
    load_frame_candidate_index,
    reject_frame_candidate,
    select_frame_candidate,
    write_frame_candidate_index,
)


def write_candidate_job(job_dir: Path) -> Path:
    (job_dir / "metadata.json").write_text(json.dumps({"duration_seconds": 120}), encoding="utf-8")
    (job_dir / "note.md").write_text(
        "\n".join(
            [
                "# Demo",
                "",
                "### Intro",
                "",
                "`00:00:00 - 00:01:00`",
                "",
                "> 关键帧：`00:00:20`：Intro slide",
                "",
                "Intro details",
                "",
                "### Advanced",
                "",
                "`00:01:00 - 00:02:00`",
                "",
                "Advanced details",
            ]
        ),
        encoding="utf-8-sig",
    )
    video_path = job_dir / "source_video" / "input.mp4"
    video_path.parent.mkdir(parents=True)
    video_path.write_bytes(b"video")
    return video_path


def test_build_frame_candidate_index_selects_non_duplicate_defaults(tmp_path, monkeypatch) -> None:
    video_path = write_candidate_job(tmp_path)
    extracted: list[float] = []

    def fake_extract_frame(_video_path: Path, output_path: Path, timestamp: float, _duration: float | None) -> float:
        extracted.append(timestamp)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(f"jpg-{timestamp}".encode())
        return timestamp

    hashes = [
        "0000000000000000",
        "0000000000000000",
        "1111111111111111",
        "2222222222222222",
        "2222222222222222",
        "3333333333333333",
    ]

    monkeypatch.setattr("backend.app.frame_candidates.extract_frame", fake_extract_frame)
    monkeypatch.setattr("backend.app.frame_candidates.average_hash", lambda _path: hashes.pop(0))

    index = build_frame_candidate_index(tmp_path, video_path, duration=120, candidates_per_chapter=3)

    assert len(index.candidates) == 6
    assert extracted
    assert index.candidates[0].selected is True
    assert index.candidates[1].selected is False
    assert index.candidates[1].duplicate_of == index.candidates[0].id
    assert "duplicate_frame" in index.candidates[1].risk_flags
    assert [candidate.selected for candidate in index.candidates if candidate.chapter_index == 0].count(True) == 1
    assert [candidate.selected for candidate in index.candidates if candidate.chapter_index == 1].count(True) == 1


def test_frame_candidate_index_persists_and_mutations_update_choices(tmp_path, monkeypatch) -> None:
    video_path = write_candidate_job(tmp_path)

    def fake_extract_frame(_video_path: Path, output_path: Path, timestamp: float, _duration: float | None) -> float:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(f"jpg-{timestamp}".encode())
        return timestamp

    monkeypatch.setattr("backend.app.frame_candidates.extract_frame", fake_extract_frame)
    monkeypatch.setattr("backend.app.frame_candidates.average_hash", lambda path: path.name)

    index = build_frame_candidate_index(tmp_path, video_path, duration=120, candidates_per_chapter=2)
    write_frame_candidate_index(tmp_path, index)

    loaded = load_frame_candidate_index(tmp_path)
    assert loaded is not None
    assert len(loaded.candidates) == 4

    second_id = loaded.candidates[1].id
    selected = select_frame_candidate(tmp_path, second_id)
    selected_candidates = [candidate for candidate in selected.candidates if candidate.chapter_index == 0 and candidate.selected]
    assert [candidate.id for candidate in selected_candidates] == [second_id]

    rejected = reject_frame_candidate(tmp_path, second_id)
    rejected_candidate = next(candidate for candidate in rejected.candidates if candidate.id == second_id)
    assert rejected_candidate.selected is False
    assert rejected_candidate.rejected is True
```

- [ ] **Step 2: Run the candidate tests and verify RED**

Run:

```bash
pytest backend/tests/test_frame_candidates.py -q
```

Expected: model test passes and the new tests fail because `backend.app.frame_candidates` does not exist.

- [ ] **Step 3: Create `backend/app/frame_candidates.py`**

Implement these public functions and keep helpers private:

```python
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from .ffmpeg_tools import extract_frame
from .models import FrameCandidate, FrameCandidateIndex


FRAME_CANDIDATES_INDEX = Path("review") / "frame_candidates.json"
TIME_RANGE_PATTERN = re.compile(r"`?(\d{2}:\d{2}:\d{2})\s+-\s+(\d{2}:\d{2}:\d{2})`?")
KEY_FRAME_PATTERN = re.compile(r"关键帧：`?(\d{2}:\d{2}:\d{2})`?：?(.+)?")
HEADING_PATTERN = re.compile(r"^###\s+(.+?)\s*$")
HASH_DUPLICATE_DISTANCE = 6


@dataclass(frozen=True)
class CandidateChapter:
    index: int
    title: str
    start_time: float
    end_time: float
    key_times: list[tuple[float, str]]


def build_frame_candidate_index(
    job_dir: Path,
    video_path: Path,
    *,
    duration: float | None,
    candidates_per_chapter: int = 3,
) -> FrameCandidateIndex:
    note_text = (job_dir / "note.md").read_text(encoding="utf-8-sig")
    chapters = _parse_candidate_chapters(note_text, duration)
    candidates: list[FrameCandidate] = []
    selected_by_chapter: set[int] = set()
    prior_hashes: list[tuple[str, str]] = []

    for chapter in chapters:
        for candidate_number, seed in enumerate(_candidate_seeds(chapter, candidates_per_chapter), start=1):
            candidate_id = f"chapter_{chapter.index + 1:03d}_candidate_{candidate_number:03d}"
            rel_path = f"review/frame_candidates/chapter_{chapter.index + 1:03d}/candidate_{candidate_number:03d}.jpg"
            actual_time = extract_frame(video_path, job_dir / rel_path, seed.time, duration)
            hash_value = average_hash(job_dir / rel_path)
            duplicate_of, similarity = _nearest_duplicate(hash_value, prior_hashes)
            risk_flags = ["duplicate_frame"] if duplicate_of else []
            selected = duplicate_of is None and chapter.index not in selected_by_chapter
            if selected:
                selected_by_chapter.add(chapter.index)
            candidates.append(
                FrameCandidate(
                    id=candidate_id,
                    chapter_index=chapter.index,
                    time=actual_time,
                    path=rel_path,
                    reason=seed.reason,
                    source=seed.source,
                    hash=hash_value,
                    duplicate_of=duplicate_of,
                    similarity=similarity,
                    risk_flags=risk_flags,
                    selected=selected,
                    rejected=False,
                )
            )
            prior_hashes.append((candidate_id, hash_value))
    return FrameCandidateIndex(candidates=candidates)
```

Also implement:

```python
def write_frame_candidate_index(job_dir: Path, index: FrameCandidateIndex) -> Path:
    path = job_dir / FRAME_CANDIDATES_INDEX
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(index.model_dump_json(indent=2), encoding="utf-8")
    return path


def load_frame_candidate_index(job_dir: Path) -> FrameCandidateIndex | None:
    path = job_dir / FRAME_CANDIDATES_INDEX
    if not path.exists():
        return None
    try:
        return FrameCandidateIndex.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def select_frame_candidate(job_dir: Path, candidate_id: str) -> FrameCandidateIndex:
    index = _require_frame_candidate_index(job_dir)
    target = _require_candidate(index, candidate_id)
    updated = []
    for candidate in index.candidates:
        if candidate.chapter_index != target.chapter_index:
            updated.append(candidate)
        elif candidate.id == candidate_id:
            updated.append(candidate.model_copy(update={"selected": True, "rejected": False}))
        else:
            updated.append(candidate.model_copy(update={"selected": False}))
    new_index = FrameCandidateIndex(candidates=updated)
    write_frame_candidate_index(job_dir, new_index)
    return new_index


def reject_frame_candidate(job_dir: Path, candidate_id: str) -> FrameCandidateIndex:
    index = _require_frame_candidate_index(job_dir)
    _require_candidate(index, candidate_id)
    updated = [
        candidate.model_copy(update={"selected": False, "rejected": True})
        if candidate.id == candidate_id
        else candidate
        for candidate in index.candidates
    ]
    new_index = FrameCandidateIndex(candidates=updated)
    write_frame_candidate_index(job_dir, new_index)
    return new_index
```

Required private helper behavior:

- `_parse_candidate_chapters(note_text, duration)` parses `###` headings and the first chapter time range; when no heading exists, it returns one whole-note chapter from `0` to `duration or 0`.
- `_candidate_seeds(chapter, limit)` returns model/note key-frame timestamps first, then chapter fallback timestamps at 25%, 50%, and 75% of the range until `limit` is reached.
- `average_hash(path)` computes a small deterministic content hash. First implementation may use a stable byte digest and should be replaceable later by FFmpeg grayscale hashing:

```python
import hashlib


def average_hash(path: Path) -> str:
    data = path.read_bytes()
    if not data:
        return ""
    return hashlib.blake2b(data, digest_size=8).hexdigest()
```

Use `_hamming_distance` over hex strings for `_nearest_duplicate`; return `(candidate_id, similarity)` when distance is `<= HASH_DUPLICATE_DISTANCE`, otherwise `(None, 0.0)`.

- [ ] **Step 4: Run candidate tests and verify GREEN**

Run:

```bash
pytest backend/tests/test_frame_candidates.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/frame_candidates.py backend/tests/test_frame_candidates.py
git commit -m "feat: generate frame candidates"
```

---

### Task 3: Expose Frame Candidate API And Artifact

**Files:**
- Modify: `backend/app/main.py`
- Modify: `backend/app/job_store.py`
- Modify: `backend/tests/test_frame_candidates.py`
- Modify: `backend/tests/test_job_history.py`

- [ ] **Step 1: Add API tests**

Append to `backend/tests/test_frame_candidates.py`:

```python
from fastapi.testclient import TestClient

from backend.app import main
from backend.app.job_store import JobStore
from backend.app.main import app


def test_frame_candidate_endpoint_generates_and_returns_candidates(tmp_path, monkeypatch) -> None:
    outputs_root = tmp_path / "outputs"
    job_id = "frame-candidates-job"
    job_dir = outputs_root / job_id
    job_dir.mkdir(parents=True)
    video_path = write_candidate_job(job_dir)

    def fake_extract_frame(_video_path: Path, output_path: Path, timestamp: float, _duration: float | None) -> float:
        assert _video_path == video_path
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(f"jpg-{timestamp}".encode())
        return timestamp

    monkeypatch.setattr(main, "OUTPUTS_ROOT", outputs_root)
    monkeypatch.setattr(main, "store", JobStore(outputs_root))
    monkeypatch.setattr("backend.app.frame_candidates.extract_frame", fake_extract_frame)
    monkeypatch.setattr("backend.app.frame_candidates.average_hash", lambda path: path.name)

    response = TestClient(app).get(f"/api/jobs/{job_id}/frame-candidates")

    assert response.status_code == 200
    payload = response.json()
    assert len(payload["candidates"]) > 0
    assert (job_dir / "review" / "frame_candidates.json").exists()


def test_frame_candidate_select_and_reject_endpoints_persist_choice(tmp_path, monkeypatch) -> None:
    outputs_root = tmp_path / "outputs"
    job_id = "frame-choice-job"
    job_dir = outputs_root / job_id
    job_dir.mkdir(parents=True)
    video_path = write_candidate_job(job_dir)

    def fake_extract_frame(_video_path: Path, output_path: Path, timestamp: float, _duration: float | None) -> float:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(f"jpg-{timestamp}".encode())
        return timestamp

    monkeypatch.setattr(main, "OUTPUTS_ROOT", outputs_root)
    monkeypatch.setattr(main, "store", JobStore(outputs_root))
    monkeypatch.setattr("backend.app.frame_candidates.extract_frame", fake_extract_frame)
    monkeypatch.setattr("backend.app.frame_candidates.average_hash", lambda path: path.name)

    client = TestClient(app)
    first_payload = client.get(f"/api/jobs/{job_id}/frame-candidates").json()
    candidate_id = first_payload["candidates"][1]["id"]

    selected = client.post(f"/api/jobs/{job_id}/frame-candidates/{candidate_id}/select")
    assert selected.status_code == 200
    assert next(candidate for candidate in selected.json()["candidates"] if candidate["id"] == candidate_id)["selected"] is True

    rejected = client.post(f"/api/jobs/{job_id}/frame-candidates/{candidate_id}/reject")
    assert rejected.status_code == 200
    candidate = next(candidate for candidate in rejected.json()["candidates"] if candidate["id"] == candidate_id)
    assert candidate["selected"] is False
    assert candidate["rejected"] is True
```

Append to `backend/tests/test_job_history.py`:

```python
def test_refresh_artifacts_includes_frame_candidate_index(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(main, "OUTPUTS_ROOT", tmp_path)
    monkeypatch.setattr(main, "store", JobStore(tmp_path))
    job_dir = tmp_path / "frame-candidate-artifacts"
    job_dir.mkdir()
    review_dir = job_dir / "review"
    review_dir.mkdir()
    (review_dir / "frame_candidates.json").write_text('{"candidates":[]}', encoding="utf-8")

    artifacts = main.store.refresh_artifacts("frame-candidate-artifacts")

    assert {artifact.path for artifact in artifacts} >= {"review/frame_candidates.json"}
```

- [ ] **Step 2: Run API tests and verify RED**

Run:

```bash
pytest backend/tests/test_frame_candidates.py::test_frame_candidate_endpoint_generates_and_returns_candidates backend/tests/test_frame_candidates.py::test_frame_candidate_select_and_reject_endpoints_persist_choice backend/tests/test_job_history.py::test_refresh_artifacts_includes_frame_candidate_index -q
```

Expected: endpoint tests fail with 404 and artifact test fails because the artifact is not listed.

- [ ] **Step 3: Add artifact listing**

In `backend/app/job_store.py`, extend `review_candidates`:

```python
                ("frame_candidates.json", "配图候选 JSON", "json"),
```

- [ ] **Step 4: Add API endpoint imports and handlers**

In `backend/app/main.py`, import:

```python
from .frame_candidates import (
    build_frame_candidate_index,
    load_frame_candidate_index,
    reject_frame_candidate,
    select_frame_candidate,
    write_frame_candidate_index,
)
from .models import FrameCandidateIndex
from .note_versions import find_source_video
```

Add near the quality-report endpoint:

```python
@app.get("/api/jobs/{job_id}/frame-candidates", response_model=FrameCandidateIndex)
def get_frame_candidates(job_id: str) -> FrameCandidateIndex:
    job_dir = safe_job_dir(job_id)
    if not (job_dir / "note.md").exists():
        raise HTTPException(status_code=400, detail="frame candidates require note.md.")
    existing = load_frame_candidate_index(job_dir)
    if existing is not None:
        return existing
    try:
        video_path = find_source_video(job_dir)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    metadata = read_job_metadata(job_dir)
    duration = metadata.get("duration_seconds")
    index = build_frame_candidate_index(
        job_dir,
        video_path,
        duration=float(duration) if duration is not None else None,
    )
    write_frame_candidate_index(job_dir, index)
    store.refresh_artifacts(job_id)
    return index


@app.post("/api/jobs/{job_id}/frame-candidates/{candidate_id}/select", response_model=FrameCandidateIndex)
def select_job_frame_candidate(job_id: str, candidate_id: str) -> FrameCandidateIndex:
    job_dir = safe_job_dir(job_id)
    try:
        index = select_frame_candidate(job_dir, candidate_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    store.refresh_artifacts(job_id)
    return index


@app.post("/api/jobs/{job_id}/frame-candidates/{candidate_id}/reject", response_model=FrameCandidateIndex)
def reject_job_frame_candidate(job_id: str, candidate_id: str) -> FrameCandidateIndex:
    job_dir = safe_job_dir(job_id)
    try:
        index = reject_frame_candidate(job_dir, candidate_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    store.refresh_artifacts(job_id)
    return index
```

If `read_job_metadata` does not exist in `main.py`, add a small private helper near `safe_job_path`:

```python
def read_job_metadata(job_dir: Path) -> dict:
    metadata_path = job_dir / "metadata.json"
    if not metadata_path.exists():
        return {}
    try:
        return json.loads(metadata_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
```

- [ ] **Step 5: Run backend tests and verify GREEN**

Run:

```bash
pytest backend/tests/test_frame_candidates.py backend/tests/test_job_history.py::test_refresh_artifacts_includes_frame_candidate_index -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/main.py backend/app/job_store.py backend/tests/test_frame_candidates.py backend/tests/test_job_history.py
git commit -m "feat: expose frame candidates"
```

---

### Task 4: Render Candidate Review In Frontend

**Files:**
- Modify: `frontend/src/types.ts`
- Modify: `frontend/src/api.ts`
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/styles.css`

- [ ] **Step 1: Add frontend types**

In `frontend/src/types.ts`, after `QualityReport`, add:

```ts
export type FrameCandidate = {
  id: string;
  chapter_index: number;
  time: number;
  path: string;
  reason: string;
  source: "note_key_moment" | "chapter_fallback";
  hash: string;
  duplicate_of?: string | null;
  similarity: number;
  risk_flags: string[];
  selected: boolean;
  rejected: boolean;
};

export type FrameCandidateIndex = {
  candidates: FrameCandidate[];
};
```

- [ ] **Step 2: Add API helpers**

In `frontend/src/api.ts`, add `FrameCandidateIndex` to the type import and add:

```ts
export async function fetchFrameCandidates(jobId: string): Promise<FrameCandidateIndex> {
  const response = await fetch(`/api/jobs/${jobId}/frame-candidates`);
  if (!response.ok) {
    throw new Error(await readResponseError(response, "配图候选读取失败。"));
  }
  return response.json();
}

export async function selectFrameCandidate(jobId: string, candidateId: string): Promise<FrameCandidateIndex> {
  const response = await fetch(`/api/jobs/${jobId}/frame-candidates/${candidateId}/select`, { method: "POST" });
  if (!response.ok) {
    throw new Error(await readResponseError(response, "配图候选选择失败。"));
  }
  return response.json();
}

export async function rejectFrameCandidate(jobId: string, candidateId: string): Promise<FrameCandidateIndex> {
  const response = await fetch(`/api/jobs/${jobId}/frame-candidates/${candidateId}/reject`, { method: "POST" });
  if (!response.ok) {
    throw new Error(await readResponseError(response, "配图候选拒绝失败。"));
  }
  return response.json();
}
```

- [ ] **Step 3: Wire frontend state and actions**

In `frontend/src/App.tsx`:

- Import the three API helpers.
- Import `FrameCandidateIndex`.
- Add state near the quality report state:

```ts
const [frameCandidateIndex, setFrameCandidateIndex] = useState<FrameCandidateIndex | null>(null);
const [frameCandidateError, setFrameCandidateError] = useState("");
const [frameCandidateBusyId, setFrameCandidateBusyId] = useState("");
```

- Add a `useEffect` mirroring the quality report fetch. It should fetch candidates only when the job has `note.md`; on failure, clear the index and set `frameCandidateError`.
- Add action handlers:

```ts
async function handleSelectFrameCandidate(candidateId: string) {
  if (!job?.job_id) return;
  setFrameCandidateBusyId(candidateId);
  try {
    setFrameCandidateIndex(await selectFrameCandidate(job.job_id, candidateId));
    setFrameCandidateError("");
  } catch (error) {
    setFrameCandidateError(error instanceof Error ? error.message : "配图候选选择失败。");
  } finally {
    setFrameCandidateBusyId("");
  }
}

async function handleRejectFrameCandidate(candidateId: string) {
  if (!job?.job_id) return;
  setFrameCandidateBusyId(candidateId);
  try {
    setFrameCandidateIndex(await rejectFrameCandidate(job.job_id, candidateId));
    setFrameCandidateError("");
  } catch (error) {
    setFrameCandidateError(error instanceof Error ? error.message : "配图候选拒绝失败。");
  } finally {
    setFrameCandidateBusyId("");
  }
}
```

- Render a `frame-candidate-panel` after the quality panel. Group candidates by `chapter_index`, show image thumbnails via `/api/jobs/${job.job_id}/assets/${candidate.path}`, badges for selected/rejected/duplicate, and two buttons: `选用` and `拒绝`.

- [ ] **Step 4: Add frontend styles**

Append compact styles to `frontend/src/styles.css`:

```css
.frame-candidate-panel {
  border: 1px solid rgba(148, 163, 184, 0.28);
  border-radius: 8px;
  padding: 12px;
  background: rgba(255, 255, 255, 0.75);
}

.frame-candidate-groups {
  display: grid;
  gap: 12px;
  margin-top: 10px;
}

.frame-candidate-strip {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(132px, 1fr));
  gap: 8px;
}

.frame-candidate-card {
  border: 1px solid rgba(148, 163, 184, 0.22);
  border-radius: 6px;
  overflow: hidden;
  background: #fff;
}

.frame-candidate-card img {
  width: 100%;
  aspect-ratio: 16 / 9;
  object-fit: cover;
  display: block;
}

.frame-candidate-body {
  display: grid;
  gap: 6px;
  padding: 8px;
}

.frame-candidate-actions {
  display: flex;
  gap: 6px;
}
```

Use existing button classes where possible instead of creating a new button system.

- [ ] **Step 5: Run frontend build**

Run:

```bash
npm --prefix frontend run build
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/types.ts frontend/src/api.ts frontend/src/App.tsx frontend/src/styles.css
git commit -m "feat: show frame candidate review"
```

---

### Task 5: Verify Phase 2 Slice

**Files:**
- No new code files.

- [ ] **Step 1: Run focused backend tests**

Run:

```bash
pytest backend/tests/test_frame_candidates.py backend/tests/test_review_quality.py backend/tests/test_job_history.py::test_refresh_artifacts_includes_frame_candidate_index -q
```

Expected: PASS.

- [ ] **Step 2: Run broader backend tests that touch artifacts and notes**

Run:

```bash
pytest backend/tests/test_job_history.py backend/tests/test_processor.py backend/tests/test_note_versions.py -q
```

Expected: PASS.

- [ ] **Step 3: Run full backend test suite**

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

Expected: branch is clean after commits. Do not commit generated `frontend/dist` changes unless the repository already tracks them for this branch.

---

## Self-Review Against Spec

- User participation: covered by persisted select/reject choices in the frontend.
- Duplicate frames: covered by hash-based duplicate marking and non-duplicate default selection.
- Candidate extraction: covered for completed jobs, generated on demand under `review/`.
- Stable final artifacts: preserved; `note.md`, `frames/`, and `download.zip` are not changed in this phase.
- Approval/finalization: not covered in this phase by design; this becomes the next plan after candidate review is stable.
