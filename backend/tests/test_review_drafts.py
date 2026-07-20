from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from backend.app import main
from backend.app.frame_candidates import write_frame_candidate_index
from backend.app.job_store import JobStore
from backend.app.main import app
from backend.app.models import FrameCandidate, FrameCandidateIndex, NoteStyle, NoteVersion, NoteVersionIndex
from backend.app.note_versions import activate_note_version, write_note_version_index
from backend.app.review_drafts import build_review_draft, get_or_build_review_draft, load_review_draft, update_review_draft_paragraph


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


def seed_versioned_review_job(job_dir: Path) -> None:
    versions: list[NoteVersion] = []
    for version_id, title, body in (
        ("note_001", "Version One", "Body one."),
        ("note_002", "Version Two", "Body two."),
    ):
        version_dir = job_dir / "note_versions" / version_id
        (version_dir / "frames").mkdir(parents=True)
        (version_dir / "note.md").write_text(
            f"# {title}\n\n### Chapter\n\n\u006000:00:00 - 00:00:10\u0060\n\n{body}",
            encoding="utf-8-sig",
        )
        versions.append(
            NoteVersion(
                id=version_id,
                label=title,
                note_style=NoteStyle.detailed,
                note_language="zh",
                note_model="test",
                note_base_url="https://example.test/v1",
                frame_limit=1,
                note_path=f"note_versions/{version_id}/note.md",
                frame_dir=f"note_versions/{version_id}/frames",
            )
        )
    write_note_version_index(
        job_dir,
        NoteVersionIndex(
            active_version_id="note_001",
            selected_version_ids=["note_001", "note_002"],
            versions=versions,
        ),
    )


def test_review_drafts_are_bound_to_the_selected_note_version(tmp_path) -> None:
    seed_versioned_review_job(tmp_path)

    activate_note_version(tmp_path, "note_001")
    first = build_review_draft(tmp_path, "note_001")
    activate_note_version(tmp_path, "note_002")
    second = get_or_build_review_draft(tmp_path, "note_002")

    assert first.note_version_id == "note_001"
    assert first.title == "Version One"
    assert first.paragraphs[0].body == "Body one."
    assert second.note_version_id == "note_002"
    assert second.title == "Version Two"
    assert second.paragraphs[0].body == "Body two."
    assert load_review_draft(tmp_path, "note_001").paragraphs[0].body == "Body one."


def test_review_draft_api_returns_the_requested_note_version(tmp_path, monkeypatch) -> None:
    outputs_root = tmp_path / "outputs"
    job_id = "versioned-review-job"
    job_dir = outputs_root / job_id
    job_dir.mkdir(parents=True)
    seed_versioned_review_job(job_dir)
    activate_note_version(job_dir, "note_002")
    monkeypatch.setattr(main, "OUTPUTS_ROOT", outputs_root)
    monkeypatch.setattr(main, "store", JobStore(outputs_root))

    response = TestClient(app).get(f"/api/jobs/{job_id}/review-draft?version_id=note_002")

    assert response.status_code == 200
    assert response.json()["note_version_id"] == "note_002"
    assert response.json()["paragraphs"][0]["body"] == "Body two."


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
