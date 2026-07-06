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
