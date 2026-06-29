# 字幕 AI 修正与差异确认 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a minimal workflow that sends transcript segments to the note LLM for terminology correction, shows a side-by-side diff, and applies the corrected transcript to regenerate subtitles and a new note version.

**Architecture:** Add a focused backend module for transcript correction and validation. Reuse existing `JobConfig`, subtitle rendering, note-version regeneration, and background job flow. Frontend changes stay local to the existing subtitle preview area and a modal; no broad layout redesign.

**Tech Stack:** FastAPI, Pydantic, OpenAI-compatible chat completions, pytest, React, TypeScript, Vite, lucide-react.

---

## File Structure

- Create: `backend/app/transcript_corrections.py`
  - Build correction prompts, call the note model, validate one corrected text per original segment, write/read pending and applied corrected transcript files, render subtitle files from corrected segments.
- Modify: `backend/app/llm.py`
  - Add a generic strict JSON chat helper or correction-specific helper that returns parsed JSON without `NoteDraft` parsing.
- Modify: `backend/app/models.py`
  - Add request/response models for transcript correction preview and apply payloads.
- Modify: `backend/app/main.py`
  - Add `POST /api/jobs/{job_id}/transcript-corrections` and `POST /api/jobs/{job_id}/transcript-corrections/apply`.
- Modify: `backend/app/note_versions.py`
  - Make `regenerate_note_version()` prefer `transcript.corrected.json` over `transcript.json`.
- Modify: `backend/app/processor.py`
  - Keep existing `regenerate_note_job()` path, relying on `note_versions.py` to choose the corrected transcript.
- Create: `backend/tests/test_transcript_corrections.py`
  - Cover success, malformed model output, apply behavior, and corrected transcript note regeneration.
- Modify: `frontend/src/App.tsx`
  - Add correction state, API calls, subtitle button, diff modal, and refresh behavior after apply.
- Modify: `frontend/src/styles.css`
  - Add local modal/diff styles matching existing modal and panel tokens.

---

### Task 1: Backend correction module and tests

**Files:**
- Create: `backend/tests/test_transcript_corrections.py`
- Create: `backend/app/transcript_corrections.py`
- Modify: `backend/app/llm.py`
- Modify: `backend/app/models.py`

- [ ] **Step 1: Write failing tests for correction preview**

Create `backend/tests/test_transcript_corrections.py` with tests equivalent to:

```python
import json

import pytest

from backend.app.models import JobConfig, NoteLanguage, NoteStyle, TranscriptionMode
from backend.app.transcript_corrections import (
    TRANSCRIPT_CORRECTED_PENDING,
    TranscriptCorrectionError,
    create_transcript_correction,
)


def make_config() -> JobConfig:
    return JobConfig(
        transcription_mode=TranscriptionMode.local_faster_whisper,
        transcription_model="small",
        note_api_key="note-key",
        note_base_url="https://api.openai.com/v1",
        note_model="gpt-5.5",
        note_language=NoteLanguage.zh,
        note_style=NoteStyle.detailed,
        frame_limit=6,
        original_filename="demo.mp4",
    )


def write_transcript(job_dir, text="低贩 工作流"):
    (job_dir / "transcript.json").write_text(
        json.dumps(
            {
                "text": text,
                "segments": [{"start": 0.0, "end": 2.0, "text": text}],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def test_create_transcript_correction_writes_pending_file(tmp_path, monkeypatch):
    write_transcript(tmp_path)

    def fake_correct(_config, segments, _instructions=""):
        return [{"index": 0, "text": "Dify 工作流"}]

    monkeypatch.setattr("backend.app.transcript_corrections.correct_transcript_segments", fake_correct)

    result = create_transcript_correction(tmp_path, make_config())

    assert result.changed_count == 1
    assert result.segments[0].original_text == "Dify 工作流"
    assert result.segments[0].corrected_text == "Dify 工作流"
    assert (tmp_path / TRANSCRIPT_CORRECTED_PENDING).exists()
```

Then tighten the assertion to expect `original_text == "Dify 工作流"` only if the existing normalization already converts it; otherwise expect the raw parsed segment text. Use the actual observed behavior after the RED run.

- [ ] **Step 2: Write failing test for invalid model output**

Add:

```python
def test_create_transcript_correction_rejects_missing_segment(tmp_path, monkeypatch):
    write_transcript(tmp_path)

    def fake_correct(_config, _segments, _instructions=""):
        return []

    monkeypatch.setattr("backend.app.transcript_corrections.correct_transcript_segments", fake_correct)

    with pytest.raises(TranscriptCorrectionError):
        create_transcript_correction(tmp_path, make_config())

    assert not (tmp_path / TRANSCRIPT_CORRECTED_PENDING).exists()
```

- [ ] **Step 3: Run RED tests**

Run:

```powershell
python -m pytest backend/tests/test_transcript_corrections.py -q
```

Expected: fail because module/functions do not exist.

- [ ] **Step 4: Add response/request models**

In `backend/app/models.py`, add:

```python
class TranscriptCorrectionRequest(BaseModel):
    note_api_key: str
    note_base_url: str = "https://api.openai.com/v1"
    note_model: str = "gpt-5.5"
    instructions: str = ""


class TranscriptCorrectionSegment(BaseModel):
    index: int
    start: float
    end: float
    original_text: str
    corrected_text: str
    changed: bool = False


class TranscriptCorrectionPreview(BaseModel):
    job_id: str = ""
    changed_count: int
    segments: list[TranscriptCorrectionSegment] = Field(default_factory=list)


class TranscriptCorrectionApplyRequest(BaseModel):
    note_language: NoteLanguage
    note_style: NoteStyle = NoteStyle.detailed
    extras: str = ""
    note_api_key: str
    note_base_url: str = "https://api.openai.com/v1"
    note_model: str = "gpt-5.5"
    frame_limit: int = Field(default=6, ge=1, le=24)
```

- [ ] **Step 5: Add generic JSON chat helper**

In `backend/app/llm.py`, add:

```python
def call_json_model(config: JobConfig, messages: list[dict], max_tokens: int = 3000) -> dict:
    client = make_client(config.note_api_key, config.note_base_url)
    response = client.chat.completions.create(
        model=config.note_model,
        messages=messages,
        response_format={"type": "json_object"},
        temperature=0.1,
        max_tokens=max_tokens,
    )
    text = response.choices[0].message.content or ""
    try:
        return extract_json(text)
    except Exception as exc:
        raise LLMError(f"Model returned invalid correction JSON: {exc}") from exc
```

- [ ] **Step 6: Implement `backend/app/transcript_corrections.py`**

Create helpers:

```python
TRANSCRIPT_ORIGINAL = "transcript.json"
TRANSCRIPT_CORRECTED_PENDING = "transcript.corrected.pending.json"
TRANSCRIPT_CORRECTED = "transcript.corrected.json"

class TranscriptCorrectionError(RuntimeError):
    pass
```

Implement:

- `load_original_segments(job_dir: Path) -> list[TranscriptSegment]`
- `correct_transcript_segments(config: JobConfig, segments: list[TranscriptSegment], instructions: str = "") -> list[dict]`
- `build_correction_preview(original, corrected) -> TranscriptCorrectionPreview`
- `create_transcript_correction(job_dir: Path, config: JobConfig, instructions: str = "") -> TranscriptCorrectionPreview`
- `apply_pending_transcript_correction(job_dir: Path) -> TranscriptCorrectionPreview`
- `load_preferred_transcript_payload(job_dir: Path) -> dict`

Behavior:

- Validate corrected length equals original length.
- Validate each corrected item index equals its original segment index.
- Strip corrected text; empty corrected text falls back to original text.
- Write pending/applied payloads as transcript JSON with `text` and `segments`.
- Use `write_subtitle_files()` when applying.

- [ ] **Step 7: Run GREEN tests**

Run:

```powershell
python -m pytest backend/tests/test_transcript_corrections.py -q
```

Expected: pass.

- [ ] **Step 8: Commit**

```powershell
git add backend/app/llm.py backend/app/models.py backend/app/transcript_corrections.py backend/tests/test_transcript_corrections.py
git commit -m "feat: add transcript correction engine"
```

---

### Task 2: Backend API and corrected transcript note regeneration

**Files:**
- Modify: `backend/tests/test_transcript_corrections.py`
- Modify: `backend/app/main.py`
- Modify: `backend/app/note_versions.py`

- [ ] **Step 1: Add API tests**

In `backend/tests/test_transcript_corrections.py`, add tests using `TestClient`:

```python
def test_transcript_correction_endpoint_returns_preview(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from backend.app import main
    from backend.app.job_store import JobStore

    job_dir = tmp_path / "job-1"
    job_dir.mkdir()
    write_transcript(job_dir)
    monkeypatch.setattr(main, "OUTPUTS_ROOT", tmp_path)
    monkeypatch.setattr(main, "store", JobStore(tmp_path))
    monkeypatch.setattr(
        "backend.app.transcript_corrections.correct_transcript_segments",
        lambda _config, _segments, _instructions="": [{"index": 0, "text": "Dify 工作流"}],
    )

    response = TestClient(main.app, raise_server_exceptions=False).post(
        "/api/jobs/job-1/transcript-corrections",
        json={"note_api_key": "key", "note_base_url": "https://api.openai.com/v1", "note_model": "gpt-5.5"},
    )

    assert response.status_code == 200
    assert response.json()["changed_count"] == 1
```

Add another test for apply endpoint that asserts `transcript.corrected.json` exists and `subtitles.md` contains corrected text.

- [ ] **Step 2: Add note regeneration preference test**

Add a test that writes both `transcript.json` and `transcript.corrected.json`, monkeypatches `backend.app.note_versions.generate_note_draft`, calls `regenerate_note_version()`, and asserts the fake draft saw corrected text.

- [ ] **Step 3: Run RED tests**

Run:

```powershell
python -m pytest backend/tests/test_transcript_corrections.py -q
```

Expected: API and preference tests fail until endpoints and note regeneration preference exist.

- [ ] **Step 4: Wire endpoints in `main.py`**

Import:

```python
from .models import TranscriptCorrectionApplyRequest, TranscriptCorrectionPreview, TranscriptCorrectionRequest
from .transcript_corrections import TranscriptCorrectionError, apply_pending_transcript_correction, create_transcript_correction
```

Add endpoints:

```python
@app.post("/api/jobs/{job_id}/transcript-corrections", response_model=TranscriptCorrectionPreview)
def create_transcript_correction_endpoint(job_id: str, request: TranscriptCorrectionRequest) -> TranscriptCorrectionPreview:
    job_dir = safe_job_dir(job_id)
    if not request.note_api_key.strip():
        raise HTTPException(status_code=400, detail="Note API Key is required.")
    if not request.note_model.strip():
        raise HTTPException(status_code=400, detail="Note model is required.")
    metadata = read_metadata(job_dir)
    config = JobConfig(
        transcription_mode=TranscriptionMode.local_faster_whisper,
        transcription_model="reuse-transcript",
        note_api_key=request.note_api_key,
        note_base_url=request.note_base_url,
        note_model=request.note_model,
        note_language=NoteLanguage(str(metadata.get("note_language") or "zh")),
        note_style=NoteStyle(str(metadata.get("note_style") or "detailed")),
        frame_limit=int(metadata.get("frame_limit") or 6),
        original_filename=str(metadata.get("original_filename") or "video"),
    )
    try:
        preview = create_transcript_correction(job_dir, config, request.instructions)
        return preview.model_copy(update={"job_id": job_id})
    except (TranscriptCorrectionError, FileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
```

Add apply endpoint that calls `apply_pending_transcript_correction(job_dir)`, validates request fields, creates `JobConfig`, enqueues `regenerate_note_job()`, refreshes artifacts, and returns `{"job_id": job_id, "status": "queued"}`.

- [ ] **Step 5: Prefer corrected transcript in `note_versions.py`**

Replace direct `transcript.json` loading in `regenerate_note_version()` with:

```python
from .transcript_corrections import load_preferred_transcript_payload

transcript_payload = load_preferred_transcript_payload(job_dir)
segments = transcript_segments_from_payload(transcript_payload)
```

- [ ] **Step 6: Run GREEN tests**

Run:

```powershell
python -m pytest backend/tests/test_transcript_corrections.py -q
```

Expected: pass.

- [ ] **Step 7: Run backend suite**

Run:

```powershell
python -m pytest backend/tests -q
```

Expected: pass.

- [ ] **Step 8: Commit**

```powershell
git add backend/app/main.py backend/app/note_versions.py backend/tests/test_transcript_corrections.py
git commit -m "feat: expose transcript correction workflow"
```

---

### Task 3: Frontend subtitle correction button and diff modal

**Files:**
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/styles.css`

- [ ] **Step 1: Add frontend types and state**

In `frontend/src/App.tsx`, add types:

```ts
type TranscriptCorrectionSegment = {
  index: number;
  start: number;
  end: number;
  original_text: string;
  corrected_text: string;
  changed: boolean;
};

type TranscriptCorrectionPreview = {
  job_id: string;
  changed_count: number;
  segments: TranscriptCorrectionSegment[];
};
```

In `App()`, add state:

```ts
const [correctionPreview, setCorrectionPreview] = useState<TranscriptCorrectionPreview | null>(null);
const [correctionError, setCorrectionError] = useState("");
const [isCorrectingTranscript, setIsCorrectingTranscript] = useState(false);
const [isApplyingCorrection, setIsApplyingCorrection] = useState(false);
```

- [ ] **Step 2: Add API handlers**

Add `handleCreateTranscriptCorrection()` and `handleApplyTranscriptCorrection()` inside `App()`:

Use this shape:

```tsx
async function handleCreateTranscriptCorrection() {
  if (!job) return;
  setCorrectionError("");
  setIsCorrectingTranscript(true);
  try {
    const response = await fetch(`/api/jobs/${job.job_id}/transcript-corrections`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        note_api_key: noteApiKey,
        note_base_url: noteBaseUrl,
        note_model: noteModel,
        instructions: extras
      })
    });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.detail || "字幕修正失败。");
    setCorrectionPreview(payload);
  } catch (error) {
    setCorrectionError(error instanceof Error ? error.message : "字幕修正失败。");
  } finally {
    setIsCorrectingTranscript(false);
  }
}

async function handleApplyTranscriptCorrection() {
  if (!job || !correctionPreview) return;
  setCorrectionError("");
  setIsApplyingCorrection(true);
  try {
    const response = await fetch(`/api/jobs/${job.job_id}/transcript-corrections/apply`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        note_language: noteLanguage,
        note_style: noteStyle,
        extras,
        note_api_key: noteApiKey,
        note_base_url: noteBaseUrl,
        note_model: noteModel,
        frame_limit: frameLimit
      })
    });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.detail || "采用字幕修正失败。");
    setCorrectionPreview(null);
    const nextJob = await fetchJob(job.job_id);
    setJob(nextJob);
    await refreshJobHistory();
  } catch (error) {
    setCorrectionError(error instanceof Error ? error.message : "采用字幕修正失败。");
  } finally {
    setIsApplyingCorrection(false);
  }
}
```

- [ ] **Step 3: Add button beside subtitle preview**

Change subtitle `PreviewBlock` usage to support a title action, or add a small action row above the subtitle preview. Keep layout local:

```tsx
<PreviewBlock
  assetBasePath={previewAssetBasePath}
  empty="字幕生成后会显示在这里。"
  jobId={job?.job_id}
  text={subtitlePreview}
  title="字幕"
  titleAction={job?.artifacts.some((artifact) => artifact.path === "transcript.json") ? (
    <button className="small-button" disabled={isBusy || isCorrectingTranscript} onClick={() => void handleCreateTranscriptCorrection()} type="button">
      {isCorrectingTranscript ? <Loader2 className="spin" size={15} /> : <Captions size={15} />}
      AI 修正字幕
    </button>
  ) : null}
/>
```

Update `PreviewBlock` props to render title and action in one header row.

- [ ] **Step 4: Add diff modal component**

Add `TranscriptCorrectionModal` below `PreviewBlock()`:

```tsx
function TranscriptCorrectionModal({
  error,
  isApplying,
  onApply,
  onClose,
  preview
}: {
  error: string;
  isApplying: boolean;
  onApply: () => void;
  onClose: () => void;
  preview: TranscriptCorrectionPreview | null;
}) {
  if (!preview) return null;
  return (
    <div className="modal-backdrop">
      <section className="modal correction-modal">
        <div className="modal-header">
          <div>
            <p className="eyebrow">Transcript correction</p>
            <h2>AI 字幕修正对比</h2>
          </div>
          <button className="icon-button" onClick={onClose} type="button">
            <X size={18} />
          </button>
        </div>
        <p className="correction-summary">共 {preview.changed_count} 段发生变化。确认后会重写字幕文件，并生成新的笔记版本。</p>
        {error && <p className="inline-error">{error}</p>}
        <div className="correction-diff-grid">
          <div className="correction-column-title">原始字幕</div>
          <div className="correction-column-title">AI 修正版</div>
          {preview.segments.map((segment) => (
            <React.Fragment key={segment.index}>
              <div className={segment.changed ? "correction-row changed" : "correction-row"}>
                <strong>{formatSecondsRange(segment.start, segment.end)}</strong>
                <span>{segment.original_text}</span>
              </div>
              <div className={segment.changed ? "correction-row changed" : "correction-row"}>
                <strong>{formatSecondsRange(segment.start, segment.end)}</strong>
                <span>{segment.corrected_text}</span>
              </div>
            </React.Fragment>
          ))}
        </div>
        <div className="modal-footer">
          <button className="small-button" disabled={isApplying} onClick={onClose} type="button">取消</button>
          <button className="small-button strong" disabled={isApplying} onClick={onApply} type="button">
            {isApplying ? <Loader2 className="spin" size={15} /> : <CheckCircle2 size={15} />}
            采用修正版并重新生成笔记
          </button>
        </div>
      </section>
    </div>
  );
}
```

Render each segment with:

- timestamp
- original text in left column
- corrected text in right column
- changed row class when `segment.changed`

- [ ] **Step 5: Add styles**

In `frontend/src/styles.css`, add:

```css
.preview-title-row {
  align-items: center;
  display: flex;
  gap: 10px;
  justify-content: space-between;
}

.correction-modal { max-width: 1080px; width: min(1080px, calc(100vw - 28px)); }
.correction-summary {
  color: var(--muted);
  font-size: 13px;
  line-height: 1.45;
  margin: 0 0 12px;
}
.correction-diff-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; max-height: 58vh; overflow: auto; }
.correction-row { border: 1px solid var(--line); border-radius: 8px; padding: 8px; }
.correction-row.changed { background: #fff8e8; border-color: #e7c46a; }
@media (max-width: 860px) { .correction-diff-grid { grid-template-columns: 1fr; } }
```

Use existing colors and 8px radius.

- [ ] **Step 6: Build verification**

Run:

```powershell
npm --prefix frontend run build
```

Expected: pass.

- [ ] **Step 7: Commit**

```powershell
git add frontend/src/App.tsx frontend/src/styles.css
git commit -m "feat: review transcript corrections in UI"
```

---

### Task 4: Final verification and desktop build

**Files:**
- No code changes unless verification reveals a failure.

- [ ] **Step 1: Run backend tests**

```powershell
python -m pytest backend/tests -q
```

Expected: pass.

- [ ] **Step 2: Run frontend build**

```powershell
npm --prefix frontend run build
```

Expected: pass.

- [ ] **Step 3: Confirm frontend scope**

```powershell
git diff --stat codex/usability-stability-main-ui..HEAD -- frontend/src/App.tsx frontend/src/styles.css
```

Expected: only localized additions for button/modal/diff styles, no broad layout rewrite.

- [ ] **Step 4: Build EXE**

```powershell
.\scripts\build-desktop.ps1
```

Expected: `dist/VideoNoteGenerator/VideoNoteGenerator.exe` exists.

- [ ] **Step 5: Report**

Summarize changed files, tests, build path, and note that original `transcript.json` remains untouched until user applies corrections.
