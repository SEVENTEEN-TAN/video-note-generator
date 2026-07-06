from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from backend.app import main
from backend.app.frame_candidates import write_frame_candidate_index
from backend.app.job_store import JobStore
from backend.app.main import app
from backend.app.models import FrameCandidate, FrameCandidateIndex
from backend.app.review_drafts import build_review_draft, load_review_draft, update_review_draft_paragraph


def seed_review_draft_job(job_dir: Path) -> None:
    (job_dir / "note.md").write_text(
        "\n".join(
            [
                "# Demo",
                "",
                "### Intro",
                "",
                "`00:00:00 - 00:01:00`",
                "",
                "Intro generated body.",
                "",
                "### Advanced",
                "",
                "`00:01:00 - 00:02:00`",
                "",
                "- Advanced bullet",
                "Advanced generated body.",
            ]
        ),
        encoding="utf-8-sig",
    )
    (job_dir / "transcript.json").write_text(
        json.dumps(
            {
                "segments": [
                    {"start": 5, "end": 8, "text": "intro subtitle"},
                    {"start": 70, "end": 75, "text": "advanced subtitle"},
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (job_dir / "review" / "frame_candidates" / "chapter_001").mkdir(parents=True)
    (job_dir / "review" / "frame_candidates" / "chapter_001" / "candidate_001.jpg").write_bytes(b"intro")
    write_frame_candidate_index(
        job_dir,
        FrameCandidateIndex(
            candidates=[
                FrameCandidate(
                    id="chapter_001_candidate_001",
                    chapter_index=0,
                    time=10,
                    path="review/frame_candidates/chapter_001/candidate_001.jpg",
                    reason="Intro frame",
                    source="chapter_fallback",
                    hash="a",
                    similarity=0,
                    selected=True,
                )
            ]
        ),
    )


def test_build_review_draft_uses_note_subtitles_and_selected_frames(tmp_path) -> None:
    seed_review_draft_job(tmp_path)

    draft = build_review_draft(tmp_path)

    assert draft.paragraphs[0].id == "paragraph_001"
    assert draft.paragraphs[0].title == "Intro"
    assert draft.paragraphs[0].body == "Intro generated body."
    assert draft.paragraphs[0].selected_frame_ids == ["chapter_001_candidate_001"]
    assert draft.paragraphs[0].subtitle_segments[0].text == "intro subtitle"
    assert draft.paragraphs[1].body == "- Advanced bullet\nAdvanced generated body."


def test_update_review_draft_paragraph_persists_human_edits(tmp_path) -> None:
    seed_review_draft_job(tmp_path)
    draft = build_review_draft(tmp_path)

    updated = update_review_draft_paragraph(
        tmp_path,
        draft.paragraphs[0].id,
        body="Human edited intro.",
        selected_frame_ids=[],
        status="edited",
    )

    reloaded = load_review_draft(tmp_path)
    assert reloaded is not None
    assert updated.paragraphs[0].body == "Human edited intro."
    assert updated.paragraphs[0].selected_frame_ids == []
    assert updated.paragraphs[0].status == "edited"
    assert reloaded.paragraphs[0].body == "Human edited intro."


def test_review_draft_api_builds_and_updates_paragraph(tmp_path, monkeypatch) -> None:
    outputs_root = tmp_path / "outputs"
    job_id = "review-draft-job"
    job_dir = outputs_root / job_id
    job_dir.mkdir(parents=True)
    seed_review_draft_job(job_dir)
    monkeypatch.setattr(main, "OUTPUTS_ROOT", outputs_root)
    monkeypatch.setattr(main, "store", JobStore(outputs_root))

    client = TestClient(app)
    response = client.get(f"/api/jobs/{job_id}/review-draft")

    assert response.status_code == 200
    payload = response.json()
    assert payload["paragraphs"][0]["body"] == "Intro generated body."

    update_response = client.patch(
        f"/api/jobs/{job_id}/review-draft/paragraphs/paragraph_001",
        json={
            "body": "Human edited via API.",
            "selected_frame_ids": [],
            "status": "approved",
        },
    )

    assert update_response.status_code == 200
    updated_payload = update_response.json()
    assert updated_payload["paragraphs"][0]["body"] == "Human edited via API."
    assert updated_payload["paragraphs"][0]["selected_frame_ids"] == []
    assert load_review_draft(job_dir).paragraphs[0].status == "approved"
