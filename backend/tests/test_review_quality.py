from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from backend.app import main
from backend.app.job_store import JobStore
from backend.app.main import app
from backend.app.models import ChapterQualityReport, QualityIssue, QualityReport, QualityScores
from backend.app.review_quality import build_quality_report, write_quality_report


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
