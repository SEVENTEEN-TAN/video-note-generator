# Quality Report Review Panel Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a first human-review quality layer that generates measurable note quality signals for completed jobs and shows them in the frontend result panel.

**Architecture:** This is the first rollout slice from the human review quality-control design. It does not add new job states yet. A new backend quality module reads existing artifacts (`note.md`, `transcript.json`, `debug.log`, `frames/`) and writes `review/quality_report.json` plus `review/quality_report.md`; a new API endpoint returns that report; the frontend shows a compact review panel so users can decide whether the output is ready or needs manual review.

**Tech Stack:** FastAPI, Pydantic v2, pytest, Vite React TypeScript, existing local filesystem artifact layout.

---

## File Structure

- Create `backend/app/review_quality.py`
  - Owns parsing current job artifacts, building quality signals, writing `review/quality_report.*`, and loading reports from disk.
- Modify `backend/app/models.py`
  - Adds Pydantic response models for `QualityReport`, `QualityScores`, `QualityIssue`, and `ChapterQualityReport`.
- Modify `backend/app/main.py`
  - Adds `GET /api/jobs/{job_id}/quality-report`.
- Modify `backend/app/job_store.py`
  - Adds `review/quality_report.json` and `review/quality_report.md` to artifacts when present.
- Create `backend/tests/test_review_quality.py`
  - Unit tests for report generation, coverage flags, duplicate frame reference flags, and debug-log stability flags.
- Modify `backend/tests/test_job_history.py`
  - Adds a focused artifact-listing assertion for review reports.
- Modify `frontend/src/types.ts`
  - Adds quality report TypeScript types.
- Modify `frontend/src/api.ts`
  - Adds `fetchQualityReport(jobId)`.
- Modify `frontend/src/App.tsx`
  - Fetches the quality report for jobs with `note.md`, displays score cards and issues in the result panel.
- Modify `frontend/src/styles.css`
  - Adds compact review-panel styling that matches the existing operational UI.

---

### Task 1: Add Quality Report Models

**Files:**
- Modify: `backend/app/models.py`
- Test: `backend/tests/test_review_quality.py`

- [ ] **Step 1: Write the model serialization test**

Create `backend/tests/test_review_quality.py` with this initial content:

```python
from __future__ import annotations

from backend.app.models import ChapterQualityReport, QualityIssue, QualityReport, QualityScores


def test_quality_report_models_serialize_expected_shape() -> None:
    report = QualityReport(
        status="review_recommended",
        scores=QualityScores(coverage=0.75, structure=1.0, frames=0.5, stability=0.8),
        issues=[
            QualityIssue(
                severity="warning",
                type="low_chapter_coverage",
                message="Chapter note is short compared with transcript coverage.",
                chapter_index=0,
                frame_ids=[],
            )
        ],
        chapter_reports=[
            ChapterQualityReport(
                chapter_index=0,
                title="Intro",
                start_time=0,
                end_time=60,
                transcript_chars=1200,
                note_chars=180,
                selected_frame_count=0,
                issues=["low_chapter_coverage"],
            )
        ],
    )

    payload = report.model_dump(mode="json")

    assert payload["status"] == "review_recommended"
    assert payload["scores"]["coverage"] == 0.75
    assert payload["issues"][0]["type"] == "low_chapter_coverage"
    assert payload["chapter_reports"][0]["title"] == "Intro"
```

- [ ] **Step 2: Run the model test to verify it fails**

Run:

```bash
pytest backend/tests/test_review_quality.py::test_quality_report_models_serialize_expected_shape -q
```

Expected: FAIL with an import error for `ChapterQualityReport`, `QualityIssue`, `QualityReport`, or `QualityScores`.

- [ ] **Step 3: Add the Pydantic models**

In `backend/app/models.py`, after `TranscriptPayload`, add:

```python
class QualityScores(BaseModel):
    coverage: float = Field(ge=0, le=1)
    structure: float = Field(ge=0, le=1)
    frames: float = Field(ge=0, le=1)
    stability: float = Field(ge=0, le=1)


class QualityIssue(BaseModel):
    severity: Literal["info", "warning", "error"]
    type: str
    message: str
    chapter_index: int | None = None
    frame_ids: list[str] = Field(default_factory=list)


class ChapterQualityReport(BaseModel):
    chapter_index: int
    title: str
    start_time: float
    end_time: float
    transcript_chars: int
    note_chars: int
    selected_frame_count: int
    issues: list[str] = Field(default_factory=list)


class QualityReport(BaseModel):
    status: Literal["ready", "review_recommended", "needs_attention"]
    scores: QualityScores
    issues: list[QualityIssue] = Field(default_factory=list)
    chapter_reports: list[ChapterQualityReport] = Field(default_factory=list)
```

- [ ] **Step 4: Run the model test to verify it passes**

Run:

```bash
pytest backend/tests/test_review_quality.py::test_quality_report_models_serialize_expected_shape -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/models.py backend/tests/test_review_quality.py
git commit -m "feat: add quality report models"
```

---

### Task 2: Build Quality Report Generation

**Files:**
- Create: `backend/app/review_quality.py`
- Modify: `backend/tests/test_review_quality.py`

- [ ] **Step 1: Add quality generation tests**

Append these tests to `backend/tests/test_review_quality.py`:

```python
import json
from pathlib import Path

from backend.app.review_quality import build_quality_report, write_quality_report


def write_transcript(job_dir: Path) -> None:
    payload = {
        "text": " ".join(["intro"] * 1000),
        "segments": [
            {"start": 0.0, "end": 30.0, "text": " ".join(["intro"] * 180)},
            {"start": 30.0, "end": 60.0, "text": " ".join(["intro"] * 180)},
            {"start": 60.0, "end": 120.0, "text": " ".join(["advanced"] * 220)},
        ],
    }
    (job_dir / "transcript.json").write_text(json.dumps(payload), encoding="utf-8")


def test_build_quality_report_flags_low_coverage_and_missing_frames(tmp_path) -> None:
    write_transcript(tmp_path)
    (tmp_path / "note.md").write_text(
        "\n".join(
            [
                "# Course",
                "",
                "## 分章节笔记",
                "",
                "### Intro",
                "",
                "`00:00:00 - 00:01:00`",
                "",
                "Short note.",
                "",
                "### Advanced",
                "",
                "`00:01:00 - 00:02:00`",
                "",
                "![same](frames/frame_001.jpg)",
                "",
                "Detailed explanation " * 80,
                "",
                "参考时间：",
                "- `00:01:05 - 00:01:20`",
            ]
        ),
        encoding="utf-8-sig",
    )

    report = build_quality_report(tmp_path)

    assert report.status == "review_recommended"
    assert any(issue.type == "low_chapter_coverage" for issue in report.issues)
    assert any(issue.type == "missing_chapter_frame" for issue in report.issues)
    intro = report.chapter_reports[0]
    assert intro.title == "Intro"
    assert "low_chapter_coverage" in intro.issues
    assert "missing_chapter_frame" in intro.issues


def test_build_quality_report_flags_duplicate_frame_references(tmp_path) -> None:
    write_transcript(tmp_path)
    (tmp_path / "note.md").write_text(
        "\n".join(
            [
                "# Course",
                "",
                "### First",
                "",
                "`00:00:00 - 00:01:00`",
                "",
                "![one](frames/frame_001.jpg)",
                "",
                "![two](frames/frame_001.jpg)",
                "",
                "A detailed enough section " * 80,
            ]
        ),
        encoding="utf-8-sig",
    )

    report = build_quality_report(tmp_path)

    duplicate_issues = [issue for issue in report.issues if issue.type == "duplicate_frame_reference"]
    assert len(duplicate_issues) == 1
    assert duplicate_issues[0].frame_ids == ["frames/frame_001.jpg"]
    assert report.scores.frames < 1


def test_build_quality_report_uses_debug_log_for_stability(tmp_path) -> None:
    write_transcript(tmp_path)
    (tmp_path / "note.md").write_text(
        "\n".join(
            [
                "# Course",
                "",
                "### Stable Enough",
                "",
                "`00:00:00 - 00:02:00`",
                "",
                "![frame](frames/frame_001.jpg)",
                "",
                "A detailed enough section " * 120,
            ]
        ),
        encoding="utf-8-sig",
    )
    events = [
        {"stage": "note_model_call", "message": "invalid_json", "details": {"context": "note-reduce"}},
        {"stage": "generate_chunked_note_draft", "message": "fallback_to_transcript_chunk", "details": {}},
        {"stage": "note_model_call", "message": "response_received", "details": {"finish_reason": "length"}},
    ]
    (tmp_path / "debug.log").write_text(
        "\n".join(json.dumps(event) for event in events) + "\n",
        encoding="utf-8",
    )

    report = build_quality_report(tmp_path)

    assert report.scores.stability < 1
    assert any(issue.type == "generation_instability" for issue in report.issues)


def test_write_quality_report_persists_json_and_markdown(tmp_path) -> None:
    write_transcript(tmp_path)
    (tmp_path / "note.md").write_text(
        "\n".join(
            [
                "# Course",
                "",
                "### Chapter",
                "",
                "`00:00:00 - 00:02:00`",
                "",
                "![frame](frames/frame_001.jpg)",
                "",
                "A detailed enough section " * 120,
            ]
        ),
        encoding="utf-8-sig",
    )

    report = build_quality_report(tmp_path)
    paths = write_quality_report(tmp_path, report)

    assert paths.json_path == tmp_path / "review" / "quality_report.json"
    assert paths.markdown_path == tmp_path / "review" / "quality_report.md"
    assert "Quality Report" in paths.markdown_path.read_text(encoding="utf-8")
    saved = json.loads(paths.json_path.read_text(encoding="utf-8"))
    assert saved["status"] in {"ready", "review_recommended", "needs_attention"}
```

- [ ] **Step 2: Run the generation tests to verify they fail**

Run:

```bash
pytest backend/tests/test_review_quality.py -q
```

Expected: the model test passes, and the new tests fail because `backend.app.review_quality` does not exist.

- [ ] **Step 3: Create the review quality module**

Create `backend/app/review_quality.py` with:

```python
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from .models import ChapterQualityReport, QualityIssue, QualityReport, QualityScores, TranscriptPayload
from .time_utils import seconds_to_hhmmss


LOW_COVERAGE_TRANSCRIPT_CHARS = 900
LOW_COVERAGE_NOTE_CHARS = 180
LONG_CHAPTER_TRANSCRIPT_CHARS = 1800
LONG_CHAPTER_NOTE_CHARS = 360
IMAGE_PATTERN = re.compile(r"!\[[^\]]*\]\(([^)]+)\)")
HEADING_PATTERN = re.compile(r"^###\s+(.+?)\s*$")
TIME_RANGE_PATTERN = re.compile(r"`?(\d{2}:\d{2}:\d{2})\s+-\s+(\d{2}:\d{2}:\d{2})`?")
REFERENCE_TIME_PATTERN = re.compile(r"\d{2}:\d{2}:\d{2}\s+-\s+\d{2}:\d{2}:\d{2}")


@dataclass(frozen=True)
class NoteSection:
    index: int
    title: str
    start_time: float
    end_time: float
    body: str
    image_paths: list[str]
    has_reference_times: bool


@dataclass(frozen=True)
class QualityReportPaths:
    json_path: Path
    markdown_path: Path


def build_quality_report(job_dir: Path) -> QualityReport:
    note_text = _read_text(job_dir / "note.md", encoding="utf-8-sig")
    transcript = _read_transcript(job_dir / "transcript.json")
    sections = _parse_note_sections(note_text)
    chapter_reports: list[ChapterQualityReport] = []
    issues: list[QualityIssue] = []

    for section in sections:
        transcript_chars = _transcript_chars_for_range(transcript, section.start_time, section.end_time)
        note_chars = _visible_text_chars(section.body)
        section_issue_types: list[str] = []

        if _is_low_coverage(transcript_chars, note_chars):
            section_issue_types.append("low_chapter_coverage")
            issues.append(
                QualityIssue(
                    severity="warning",
                    type="low_chapter_coverage",
                    message="Chapter note is short compared with transcript coverage.",
                    chapter_index=section.index,
                )
            )

        if not section.image_paths:
            section_issue_types.append("missing_chapter_frame")
            issues.append(
                QualityIssue(
                    severity="warning",
                    type="missing_chapter_frame",
                    message="Chapter has no selected frame.",
                    chapter_index=section.index,
                )
            )

        if not section.has_reference_times:
            section_issue_types.append("missing_timestamp_reference")
            issues.append(
                QualityIssue(
                    severity="info",
                    type="missing_timestamp_reference",
                    message="Chapter has no explicit reference timestamp range.",
                    chapter_index=section.index,
                )
            )

        chapter_reports.append(
            ChapterQualityReport(
                chapter_index=section.index,
                title=section.title,
                start_time=section.start_time,
                end_time=section.end_time,
                transcript_chars=transcript_chars,
                note_chars=note_chars,
                selected_frame_count=len(section.image_paths),
                issues=section_issue_types,
            )
        )

    _append_duplicate_frame_issues(sections, issues)
    _append_generation_stability_issues(job_dir, issues)

    scores = _score_report(sections, chapter_reports, issues)
    return QualityReport(status=_status_from_scores(scores, issues), scores=scores, issues=issues, chapter_reports=chapter_reports)


def write_quality_report(job_dir: Path, report: QualityReport) -> QualityReportPaths:
    review_dir = job_dir / "review"
    review_dir.mkdir(parents=True, exist_ok=True)
    json_path = review_dir / "quality_report.json"
    markdown_path = review_dir / "quality_report.md"
    json_path.write_text(report.model_dump_json(indent=2), encoding="utf-8")
    markdown_path.write_text(render_quality_report_markdown(report), encoding="utf-8")
    return QualityReportPaths(json_path=json_path, markdown_path=markdown_path)


def load_quality_report(job_dir: Path) -> QualityReport | None:
    path = job_dir / "review" / "quality_report.json"
    if not path.exists():
        return None
    try:
        return QualityReport.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def render_quality_report_markdown(report: QualityReport) -> str:
    lines = [
        "# Quality Report",
        "",
        f"- Status: `{report.status}`",
        f"- Coverage: `{report.scores.coverage:.2f}`",
        f"- Structure: `{report.scores.structure:.2f}`",
        f"- Frames: `{report.scores.frames:.2f}`",
        f"- Stability: `{report.scores.stability:.2f}`",
        "",
        "## Issues",
        "",
    ]
    if report.issues:
        for issue in report.issues:
            location = f" chapter {issue.chapter_index + 1}" if issue.chapter_index is not None else ""
            lines.append(f"- `{issue.severity}` `{issue.type}`{location}: {issue.message}")
    else:
        lines.append("- No measurable issues detected.")
    lines.extend(["", "## Chapter Coverage", ""])
    for chapter in report.chapter_reports:
        lines.append(
            f"- {chapter.chapter_index + 1}. {chapter.title} "
            f"`{seconds_to_hhmmss(chapter.start_time)} - {seconds_to_hhmmss(chapter.end_time)}` "
            f"transcript={chapter.transcript_chars} note={chapter.note_chars} frames={chapter.selected_frame_count}"
        )
    lines.append("")
    return "\n".join(lines)


def _read_text(path: Path, *, encoding: str) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding=encoding)


def _read_transcript(path: Path) -> TranscriptPayload:
    if not path.exists():
        return TranscriptPayload()
    return TranscriptPayload.model_validate_json(path.read_text(encoding="utf-8"))


def _parse_note_sections(note_text: str) -> list[NoteSection]:
    lines = note_text.splitlines()
    heading_indexes = [(index, match.group(1).strip()) for index, line in enumerate(lines) if (match := HEADING_PATTERN.match(line))]
    sections: list[NoteSection] = []
    for section_index, (line_index, title) in enumerate(heading_indexes):
        next_line_index = heading_indexes[section_index + 1][0] if section_index + 1 < len(heading_indexes) else len(lines)
        body_lines = lines[line_index + 1 : next_line_index]
        start_time, end_time = _find_section_time_range(body_lines)
        body = "\n".join(body_lines)
        sections.append(
            NoteSection(
                index=section_index,
                title=title,
                start_time=start_time,
                end_time=end_time,
                body=body,
                image_paths=IMAGE_PATTERN.findall(body),
                has_reference_times=bool(REFERENCE_TIME_PATTERN.search(body)),
            )
        )
    if sections:
        return sections
    return [
        NoteSection(
            index=0,
            title="全文",
            start_time=0,
            end_time=max((segment.end for segment in _read_transcript_from_text_fallback(note_text).segments), default=0),
            body=note_text,
            image_paths=IMAGE_PATTERN.findall(note_text),
            has_reference_times=bool(REFERENCE_TIME_PATTERN.search(note_text)),
        )
    ]


def _read_transcript_from_text_fallback(_note_text: str) -> TranscriptPayload:
    return TranscriptPayload()


def _find_section_time_range(lines: list[str]) -> tuple[float, float]:
    for line in lines[:8]:
        match = TIME_RANGE_PATTERN.search(line)
        if match:
            return _hhmmss_to_seconds(match.group(1)), _hhmmss_to_seconds(match.group(2))
    return 0.0, 0.0


def _hhmmss_to_seconds(value: str) -> float:
    hours, minutes, seconds = [int(part) for part in value.split(":")]
    return float(hours * 3600 + minutes * 60 + seconds)


def _transcript_chars_for_range(transcript: TranscriptPayload, start_time: float, end_time: float) -> int:
    if end_time <= start_time:
        return len(transcript.text)
    return sum(len(segment.text) for segment in transcript.segments if segment.end >= start_time and segment.start <= end_time)


def _visible_text_chars(markdown: str) -> int:
    without_images = IMAGE_PATTERN.sub("", markdown)
    without_code_ticks = without_images.replace("`", "")
    return len("".join(char for char in without_code_ticks if not char.isspace()))


def _is_low_coverage(transcript_chars: int, note_chars: int) -> bool:
    if transcript_chars >= LONG_CHAPTER_TRANSCRIPT_CHARS:
        return note_chars < LONG_CHAPTER_NOTE_CHARS
    if transcript_chars >= LOW_COVERAGE_TRANSCRIPT_CHARS:
        return note_chars < LOW_COVERAGE_NOTE_CHARS
    return False


def _append_duplicate_frame_issues(sections: list[NoteSection], issues: list[QualityIssue]) -> None:
    seen: dict[str, int] = {}
    for section in sections:
        for path in section.image_paths:
            if path in seen:
                issues.append(
                    QualityIssue(
                        severity="warning",
                        type="duplicate_frame_reference",
                        message="The same frame is referenced more than once.",
                        chapter_index=section.index,
                        frame_ids=[path],
                    )
                )
            else:
                seen[path] = section.index


def _append_generation_stability_issues(job_dir: Path, issues: list[QualityIssue]) -> None:
    log_path = job_dir / "debug.log"
    if not log_path.exists():
        return
    instability_count = 0
    for line in log_path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        message = str(event.get("message") or "")
        stage = str(event.get("stage") or "")
        details = event.get("details") if isinstance(event.get("details"), dict) else {}
        finish_reason = str(details.get("finish_reason") or "")
        if message in {"invalid_json", "failed"} or "fallback" in message or finish_reason in {"length", "content_filter"}:
            instability_count += 1
        if stage == "reduce_note_drafts" and message == "fallback_to_deterministic_merge":
            instability_count += 1
    if instability_count:
        issues.append(
            QualityIssue(
                severity="warning",
                type="generation_instability",
                message=f"Generation had {instability_count} retry, fallback, or truncation signals.",
            )
        )


def _score_report(
    sections: list[NoteSection],
    chapters: list[ChapterQualityReport],
    issues: list[QualityIssue],
) -> QualityScores:
    chapter_count = max(1, len(chapters))
    low_coverage = sum("low_chapter_coverage" in chapter.issues for chapter in chapters)
    missing_frames = sum("missing_chapter_frame" in chapter.issues for chapter in chapters)
    missing_refs = sum("missing_timestamp_reference" in chapter.issues for chapter in chapters)
    duplicate_frames = sum(issue.type == "duplicate_frame_reference" for issue in issues)
    instability = sum(issue.type == "generation_instability" for issue in issues)
    coverage = _clamp01(1.0 - (low_coverage / chapter_count) * 0.7 - (missing_refs / chapter_count) * 0.2)
    structure = _clamp01(1.0 if sections else 0.0)
    frames = _clamp01(1.0 - (missing_frames / chapter_count) * 0.6 - min(0.4, duplicate_frames * 0.2))
    stability = _clamp01(1.0 - min(0.8, instability * 0.25))
    return QualityScores(coverage=coverage, structure=structure, frames=frames, stability=stability)


def _status_from_scores(scores: QualityScores, issues: list[QualityIssue]) -> str:
    if any(issue.severity == "error" for issue in issues) or min(scores.coverage, scores.frames, scores.stability) < 0.5:
        return "needs_attention"
    if issues or min(scores.coverage, scores.frames, scores.stability) < 0.8:
        return "review_recommended"
    return "ready"


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, round(value, 2)))
```

- [ ] **Step 4: Run the generation tests**

Run:

```bash
pytest backend/tests/test_review_quality.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/review_quality.py backend/tests/test_review_quality.py
git commit -m "feat: generate quality reports"
```

---

### Task 3: Add Quality Report API And Artifact Listing

**Files:**
- Modify: `backend/app/main.py`
- Modify: `backend/app/job_store.py`
- Modify: `backend/tests/test_review_quality.py`
- Modify: `backend/tests/test_job_history.py`

- [ ] **Step 1: Add API and artifact tests**

Append this test to `backend/tests/test_review_quality.py`:

```python
from fastapi.testclient import TestClient

from backend.app import main
from backend.app.job_store import JobStore
from backend.app.main import app


def test_quality_report_endpoint_generates_and_returns_report(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(main, "OUTPUTS_ROOT", tmp_path)
    monkeypatch.setattr(main, "store", JobStore(tmp_path))
    job_id = "quality-job"
    job_dir = tmp_path / job_id
    job_dir.mkdir()
    write_transcript(job_dir)
    (job_dir / "note.md").write_text(
        "\n".join(
            [
                "# Course",
                "",
                "### Chapter",
                "",
                "`00:00:00 - 00:02:00`",
                "",
                "![frame](frames/frame_001.jpg)",
                "",
                "A detailed enough section " * 120,
            ]
        ),
        encoding="utf-8-sig",
    )

    response = TestClient(app).get(f"/api/jobs/{job_id}/quality-report")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] in {"ready", "review_recommended", "needs_attention"}
    assert (job_dir / "review" / "quality_report.json").exists()
    assert (job_dir / "review" / "quality_report.md").exists()


def test_quality_report_endpoint_rejects_job_without_note(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(main, "OUTPUTS_ROOT", tmp_path)
    monkeypatch.setattr(main, "store", JobStore(tmp_path))
    job_dir = tmp_path / "no-note-job"
    job_dir.mkdir()
    write_transcript(job_dir)

    response = TestClient(app).get("/api/jobs/no-note-job/quality-report")

    assert response.status_code == 400
    assert "note.md" in response.json()["detail"]
```

Append this test to `backend/tests/test_job_history.py`:

```python
def test_refresh_artifacts_includes_quality_report_files(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(main, "OUTPUTS_ROOT", tmp_path)
    monkeypatch.setattr(main, "store", JobStore(tmp_path))
    job_dir = tmp_path / "quality-artifacts"
    job_dir.mkdir()
    review_dir = job_dir / "review"
    review_dir.mkdir()
    (review_dir / "quality_report.json").write_text("{}", encoding="utf-8")
    (review_dir / "quality_report.md").write_text("# Quality Report", encoding="utf-8")

    artifacts = main.store.refresh_artifacts("quality-artifacts")

    assert {artifact.path for artifact in artifacts} >= {
        "review/quality_report.json",
        "review/quality_report.md",
    }
```

- [ ] **Step 2: Run API and artifact tests to verify they fail**

Run:

```bash
pytest backend/tests/test_review_quality.py::test_quality_report_endpoint_generates_and_returns_report backend/tests/test_review_quality.py::test_quality_report_endpoint_rejects_job_without_note backend/tests/test_job_history.py::test_refresh_artifacts_includes_quality_report_files -q
```

Expected: endpoint tests fail with 404; artifact test fails because review report files are not listed.

- [ ] **Step 3: Add artifact listing**

In `backend/app/job_store.py`, inside `refresh_artifacts` after the `debug_dir` block or before it, add:

```python
        review_dir = job_dir / "review"
        if review_dir.exists():
            review_candidates = [
                ("quality_report.json", "质量报告 JSON", "json"),
                ("quality_report.md", "质量报告 Markdown", "markdown"),
            ]
            for filename, label, kind in review_candidates:
                review_path = review_dir / filename
                if review_path.exists():
                    rel = review_path.relative_to(job_dir).as_posix()
                    artifacts.append(Artifact(label=label, path=rel, kind=kind, asset_url=f"/api/jobs/{job_id}/assets/{rel}"))
```

- [ ] **Step 4: Add the API endpoint**

In `backend/app/main.py`, add imports:

```python
from .models import (
    ...
    QualityReport,
    ...
)
from .review_quality import build_quality_report, write_quality_report
```

Then add this endpoint near the existing job preview endpoints:

```python
@app.get("/api/jobs/{job_id}/quality-report", response_model=QualityReport)
def get_quality_report(job_id: str) -> QualityReport:
    job_dir = OUTPUTS_ROOT / job_id
    if not job_dir.exists():
        raise HTTPException(status_code=404, detail="Job not found.")
    if not (job_dir / "note.md").exists():
        raise HTTPException(status_code=400, detail="quality report requires note.md.")
    if not (job_dir / "transcript.json").exists():
        raise HTTPException(status_code=400, detail="quality report requires transcript.json.")
    report = build_quality_report(job_dir)
    write_quality_report(job_dir, report)
    store.refresh_artifacts(job_id)
    return report
```

- [ ] **Step 5: Run API and artifact tests**

Run:

```bash
pytest backend/tests/test_review_quality.py backend/tests/test_job_history.py::test_refresh_artifacts_includes_quality_report_files -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/main.py backend/app/job_store.py backend/tests/test_review_quality.py backend/tests/test_job_history.py
git commit -m "feat: expose quality reports"
```

---

### Task 4: Add Frontend Types And Fetching

**Files:**
- Modify: `frontend/src/types.ts`
- Modify: `frontend/src/api.ts`
- Modify: `frontend/src/App.tsx`

- [ ] **Step 1: Add TypeScript quality types**

In `frontend/src/types.ts`, after `PreviewImage`, add:

```ts
export type QualityScores = {
  coverage: number;
  structure: number;
  frames: number;
  stability: number;
};

export type QualityIssue = {
  severity: "info" | "warning" | "error";
  type: string;
  message: string;
  chapter_index?: number | null;
  frame_ids: string[];
};

export type ChapterQualityReport = {
  chapter_index: number;
  title: string;
  start_time: number;
  end_time: number;
  transcript_chars: number;
  note_chars: number;
  selected_frame_count: number;
  issues: string[];
};

export type QualityReport = {
  status: "ready" | "review_recommended" | "needs_attention";
  scores: QualityScores;
  issues: QualityIssue[];
  chapter_reports: ChapterQualityReport[];
};
```

- [ ] **Step 2: Add API fetch helper**

In `frontend/src/api.ts`, change the import to:

```ts
import type { JobState, JobSummary, NoteVersionIndex, QualityReport } from "./types";
```

Then add:

```ts
export async function fetchQualityReport(jobId: string): Promise<QualityReport> {
  const response = await fetch(`/api/jobs/${jobId}/quality-report`);
  if (!response.ok) {
    throw new Error(await readResponseError(response, "质量报告读取失败。"));
  }
  return response.json();
}
```

- [ ] **Step 3: Wire state in App**

In `frontend/src/App.tsx`, update the API import:

```ts
import { downloadArtifact, fetchJob, fetchJobHistory, fetchNoteVersions, fetchQualityReport, readResponseError } from "./api";
```

Update the type import to include `QualityReport`:

```ts
import type {
  ...
  QualityReport,
  ...
} from "./types";
```

Add state near the other preview state:

```ts
const [qualityReport, setQualityReport] = useState<QualityReport | null>(null);
const [qualityReportError, setQualityReportError] = useState("");
```

Add this effect near the note/subtitle preview effects:

```ts
useEffect(() => {
  const currentJobId = job?.job_id;
  const hasNote = Boolean(job?.artifacts.some((artifact) => artifact.path === "note.md"));
  if (!currentJobId || !hasNote) {
    setQualityReport(null);
    setQualityReportError("");
    return;
  }

  let cancelled = false;
  fetchQualityReport(currentJobId)
    .then((report) => {
      if (!cancelled) {
        setQualityReport(report);
        setQualityReportError("");
      }
    })
    .catch((error: Error) => {
      if (!cancelled) {
        setQualityReport(null);
        setQualityReportError(error.message);
      }
    });

  return () => {
    cancelled = true;
  };
}, [job?.job_id, job?.artifacts]);
```

- [ ] **Step 4: Run frontend type check through build**

Run:

```bash
npm --prefix frontend run build
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/types.ts frontend/src/api.ts frontend/src/App.tsx
git commit -m "feat: fetch quality reports in frontend"
```

---

### Task 5: Render The Quality Review Panel

**Files:**
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/styles.css`

- [ ] **Step 1: Add local formatting helpers**

In `frontend/src/App.tsx`, near other formatting helpers, add:

```ts
function formatQualityScore(value: number) {
  return `${Math.round(value * 100)}%`;
}

function formatQualityStatus(status: QualityReport["status"]) {
  if (status === "ready") {
    return "可交付";
  }
  if (status === "needs_attention") {
    return "需要处理";
  }
  return "建议复核";
}

function formatQualityIssueType(type: string) {
  const labels: Record<string, string> = {
    low_chapter_coverage: "章节覆盖偏薄",
    missing_chapter_frame: "章节缺少配图",
    missing_timestamp_reference: "缺少引用时间",
    duplicate_frame_reference: "重复配图",
    generation_instability: "生成不稳定",
  };
  return labels[type] ?? type;
}
```

- [ ] **Step 2: Add the review panel JSX**

In `frontend/src/App.tsx`, inside the result panel after the subtitle gate block and before the running progress block, add:

```tsx
{qualityReport && (
  <section className={`quality-panel ${qualityReport.status}`} aria-label="质量复核">
    <div className="quality-panel-head">
      <div>
        <strong>质量复核</strong>
        <span>系统已检查覆盖、结构、配图和生成稳定性；最终准确性仍建议人工确认。</span>
      </div>
      <span className={`quality-status ${qualityReport.status}`}>{formatQualityStatus(qualityReport.status)}</span>
    </div>
    <div className="quality-score-grid">
      <div>
        <span>覆盖</span>
        <strong>{formatQualityScore(qualityReport.scores.coverage)}</strong>
      </div>
      <div>
        <span>结构</span>
        <strong>{formatQualityScore(qualityReport.scores.structure)}</strong>
      </div>
      <div>
        <span>配图</span>
        <strong>{formatQualityScore(qualityReport.scores.frames)}</strong>
      </div>
      <div>
        <span>稳定性</span>
        <strong>{formatQualityScore(qualityReport.scores.stability)}</strong>
      </div>
    </div>
    {qualityReport.issues.length > 0 ? (
      <div className="quality-issues">
        {qualityReport.issues.slice(0, 5).map((issue, index) => (
          <div className={`quality-issue ${issue.severity}`} key={`${issue.type}-${issue.chapter_index ?? "global"}-${index}`}>
            <AlertTriangle size={14} />
            <span>
              {issue.chapter_index !== null && issue.chapter_index !== undefined ? `第 ${issue.chapter_index + 1} 章 · ` : ""}
              {formatQualityIssueType(issue.type)}：{issue.message}
            </span>
          </div>
        ))}
        {qualityReport.issues.length > 5 && <span className="quality-more">还有 {qualityReport.issues.length - 5} 个风险项</span>}
      </div>
    ) : (
      <p className="quality-empty">没有发现可测量的覆盖或配图风险。</p>
    )}
  </section>
)}
{qualityReportError && (
  <p className="inline-warning">
    <AlertTriangle size={15} />
    {qualityReportError}
  </p>
)}
```

- [ ] **Step 3: Add styling**

Append to `frontend/src/styles.css`:

```css
.quality-panel {
  border: 1px solid rgba(148, 163, 184, 0.28);
  border-radius: 8px;
  padding: 12px;
  background: rgba(15, 23, 42, 0.18);
}

.quality-panel.ready {
  border-color: rgba(34, 197, 94, 0.35);
}

.quality-panel.review_recommended {
  border-color: rgba(245, 158, 11, 0.38);
}

.quality-panel.needs_attention {
  border-color: rgba(239, 68, 68, 0.4);
}

.quality-panel-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}

.quality-panel-head div {
  display: grid;
  gap: 3px;
}

.quality-panel-head strong {
  color: var(--text);
  font-size: 14px;
}

.quality-panel-head span {
  color: var(--muted);
  font-size: 12px;
  line-height: 1.45;
}

.quality-status {
  flex: 0 0 auto;
  border-radius: 999px;
  padding: 4px 8px;
  font-size: 12px;
  font-weight: 700;
}

.quality-status.ready {
  color: #166534;
  background: #dcfce7;
}

.quality-status.review_recommended {
  color: #92400e;
  background: #fef3c7;
}

.quality-status.needs_attention {
  color: #991b1b;
  background: #fee2e2;
}

.quality-score-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 8px;
  margin-top: 12px;
}

.quality-score-grid div {
  display: grid;
  gap: 2px;
  border: 1px solid rgba(148, 163, 184, 0.18);
  border-radius: 6px;
  padding: 8px;
  background: rgba(255, 255, 255, 0.72);
}

.quality-score-grid span {
  color: var(--muted);
  font-size: 11px;
}

.quality-score-grid strong {
  color: var(--text);
  font-size: 15px;
}

.quality-issues {
  display: grid;
  gap: 6px;
  margin-top: 10px;
}

.quality-issue {
  display: flex;
  align-items: flex-start;
  gap: 6px;
  color: var(--muted);
  font-size: 12px;
  line-height: 1.45;
}

.quality-issue.warning svg,
.quality-issue.error svg {
  color: #f59e0b;
}

.quality-issue.error svg {
  color: #ef4444;
}

.quality-empty,
.quality-more {
  margin: 10px 0 0;
  color: var(--muted);
  font-size: 12px;
}

@media (max-width: 720px) {
  .quality-score-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}
```

- [ ] **Step 4: Build frontend**

Run:

```bash
npm --prefix frontend run build
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/App.tsx frontend/src/styles.css
git commit -m "feat: show quality review panel"
```

---

### Task 6: Verify Phase 1 End-To-End

**Files:**
- No new code files.

- [ ] **Step 1: Run focused backend tests**

Run:

```bash
pytest backend/tests/test_review_quality.py backend/tests/test_job_history.py::test_refresh_artifacts_includes_quality_report_files -q
```

Expected: PASS.

- [ ] **Step 2: Run broader backend tests that touch job state and artifacts**

Run:

```bash
pytest backend/tests/test_job_history.py backend/tests/test_processor.py backend/tests/test_note_versions.py -q
```

Expected: PASS.

- [ ] **Step 3: Run frontend build**

Run:

```bash
npm --prefix frontend run build
```

Expected: PASS.

- [ ] **Step 4: Inspect git status**

Run:

```bash
git status --short
```

Expected: no unstaged changes except build artifacts that already belong to the repository policy. If `frontend/dist` changes and is untracked or modified, do not commit it unless the repository already tracks it.

---

## Self-Review Against Spec

- User quality control: this phase adds visible scores and risks, but does not yet add approval states. Covered as first rollout slice.
- Coverage signals: implemented through chapter reports with transcript chars, note chars, frame counts, and issue types.
- Repeated frames: implemented for duplicate frame references in `note.md`; perceptual image hashing is reserved for the next plan because it needs candidate frame extraction.
- User frame selection: not in this phase; planned after frame candidate extraction.
- Job state changes: intentionally not in this phase, matching the rollout plan's first step.
- Stable final artifacts: preserved; endpoint writes only under `review/`.
