from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from backend.app import main
from backend.app.frame_candidates import write_frame_candidate_index
from backend.app.job_store import JobStore
from backend.app.main import app
from backend.app.models import (
    FrameCandidate,
    FrameCandidateIndex,
    JobStage,
    JobStatus,
    NoteStyle,
    NoteVersion,
    NoteVersionIndex,
    ReviewDraft,
    ReviewDraftParagraph,
)
from backend.app.note_versions import write_note_version_index
from backend.app.review_drafts import load_review_draft, write_review_draft
from backend.app.review_finalization import mark_note_review_pending


def _seed_store(outputs_root: Path, job_id: str) -> tuple[JobStore, Path]:
    job_dir = outputs_root / job_id
    job_dir.mkdir(parents=True)
    (job_dir / "metadata.json").write_text(
        json.dumps(
            {
                "job_id": job_id,
                "title": "Revision guard",
                "original_filename": "input.mp4",
                "frame_limit": 6,
            }
        ),
        encoding="utf-8",
    )
    store = JobStore(outputs_root)
    store.create(job_id)
    store.update(
        job_id,
        status=JobStatus.awaiting_note_review,
        stage=JobStage.awaiting_note_review,
        step="等待复核笔记",
        progress=92,
    )
    return store, job_dir


def _guard_query(state) -> str:
    return (
        f"?expected_state_revision={state.state_revision}"
        f"&expected_artifact_revision={state.artifact_revision}"
    )


def _candidate_index() -> FrameCandidateIndex:
    return FrameCandidateIndex(
        candidates=[
            FrameCandidate(
                id="candidate_001",
                chapter_index=0,
                time=1,
                path="review/frame_candidates/chapter_001/candidate_001.jpg",
                reason="Candidate",
                source="chapter_fallback",
                hash="hash",
                similarity=0,
            )
        ]
    )


def _version(version_id: str) -> NoteVersion:
    return NoteVersion(
        id=version_id,
        label=version_id,
        note_style=NoteStyle.detailed,
        note_language="zh",
        note_model="test",
        note_base_url="https://example.test/v1",
        frame_limit=1,
        note_path=f"note_versions/{version_id}/note.md",
        frame_dir=f"note_versions/{version_id}/frames",
    )


def test_frame_candidate_mutation_rejects_stale_artifact_revision_without_writing(
    tmp_path,
    monkeypatch,
) -> None:
    outputs_root = tmp_path / "outputs"
    job_id = "stale-frame"
    store, job_dir = _seed_store(outputs_root, job_id)
    index = _candidate_index()
    candidate_path = job_dir / index.candidates[0].path
    candidate_path.parent.mkdir(parents=True)
    candidate_path.write_bytes(b"jpg")
    write_frame_candidate_index(job_dir, index)
    store.refresh_artifacts(job_id)
    stale = store.get(job_id)
    assert stale is not None
    (job_dir / "subtitles.md").write_text("new artifact revision", encoding="utf-8")
    monkeypatch.setattr(main, "OUTPUTS_ROOT", outputs_root)
    monkeypatch.setattr(main, "store", store)

    response = TestClient(app).post(
        f"/api/jobs/{job_id}/frame-candidates/candidate_001/select{_guard_query(stale)}"
    )

    assert response.status_code == 409
    assert "artifacts changed" in response.json()["detail"]
    persisted = json.loads((job_dir / "review" / "frame_candidates.json").read_text(encoding="utf-8"))
    assert persisted["candidates"][0]["selected"] is False


def test_note_version_mutation_rejects_stale_state_revision_without_switching(
    tmp_path,
    monkeypatch,
) -> None:
    outputs_root = tmp_path / "outputs"
    job_id = "stale-version"
    store, job_dir = _seed_store(outputs_root, job_id)
    versions = [_version("note_001"), _version("note_002")]
    for version in versions:
        version_dir = job_dir / "note_versions" / version.id
        (version_dir / "frames").mkdir(parents=True)
        (version_dir / "note.md").write_text(f"# {version.id}", encoding="utf-8")
        (version_dir / "frames" / "frame.jpg").write_bytes(version.id.encode())
    write_note_version_index(
        job_dir,
        NoteVersionIndex(
            active_version_id="note_001",
            selected_version_ids=["note_001", "note_002"],
            versions=[
                versions[0].model_copy(update={"active": True}),
                versions[1],
            ],
        ),
    )
    (job_dir / "note.md").write_text("# note_001", encoding="utf-8")
    (job_dir / "frames").mkdir()
    (job_dir / "frames" / "frame.jpg").write_bytes(b"note_001")
    store.refresh_artifacts(job_id)
    stale = store.get(job_id)
    assert stale is not None
    store.update(job_id, step="另一个窗口已更新状态", progress=93)
    monkeypatch.setattr(main, "OUTPUTS_ROOT", outputs_root)
    monkeypatch.setattr(main, "store", store)

    response = TestClient(app).patch(
        f"/api/jobs/{job_id}/note-versions{_guard_query(stale)}",
        json={
            "active_version_id": "note_002",
            "selected_version_ids": ["note_001", "note_002"],
        },
    )

    assert response.status_code == 409
    assert "state changed" in response.json()["detail"]
    assert json.loads((job_dir / "note_versions" / "versions.json").read_text(encoding="utf-8"))[
        "active_version_id"
    ] == "note_001"
    assert (job_dir / "note.md").read_text(encoding="utf-8") == "# note_001"


def test_review_paragraph_mutation_rejects_stale_artifact_revision_without_saving(
    tmp_path,
    monkeypatch,
) -> None:
    outputs_root = tmp_path / "outputs"
    job_id = "stale-review-paragraph"
    store, job_dir = _seed_store(outputs_root, job_id)
    write_review_draft(
        job_dir,
        ReviewDraft(
            schema_version=2,
            title="Review",
            paragraphs=[
                ReviewDraftParagraph(
                    id="paragraph_001",
                    chapter_index=0,
                    title="Intro",
                    start_time=0,
                    end_time=10,
                    body="Original body.",
                )
            ],
        ),
    )
    store.refresh_artifacts(job_id)
    stale = store.get(job_id)
    assert stale is not None
    (job_dir / "subtitles.md").write_text("new artifact revision", encoding="utf-8")
    monkeypatch.setattr(main, "OUTPUTS_ROOT", outputs_root)
    monkeypatch.setattr(main, "store", store)

    response = TestClient(app).patch(
        f"/api/jobs/{job_id}/review-draft/paragraphs/paragraph_001{_guard_query(stale)}",
        json={
            "body": "Stale overwrite.",
            "selected_frame_ids": [],
            "status": "approved",
        },
    )

    assert response.status_code == 409
    assert "artifacts changed" in response.json()["detail"]
    persisted = load_review_draft(job_dir)
    assert persisted is not None
    assert persisted.paragraphs[0].body == "Original body."
    assert persisted.paragraphs[0].status == "needs_review"


def test_finalize_rejects_stale_revision_before_publishing_zip(tmp_path, monkeypatch) -> None:
    outputs_root = tmp_path / "outputs"
    job_id = "stale-finalize"
    store, job_dir = _seed_store(outputs_root, job_id)
    mark_note_review_pending(job_dir)
    stale = store.get(job_id)
    assert stale is not None
    store.update(job_id, step="复核内容已被更新", progress=92)
    monkeypatch.setattr(main, "OUTPUTS_ROOT", outputs_root)
    monkeypatch.setattr(main, "store", store)

    response = TestClient(app).post(
        f"/api/jobs/{job_id}/finalize{_guard_query(stale)}"
    )

    assert response.status_code == 409
    assert "state changed" in response.json()["detail"]
    assert not (job_dir / "download.zip").exists()
    assert (job_dir / ".note-review.pending").exists()


def test_revision_guard_remains_optional_for_legacy_clients(tmp_path, monkeypatch) -> None:
    outputs_root = tmp_path / "outputs"
    job_id = "legacy-revision-client"
    store, job_dir = _seed_store(outputs_root, job_id)
    index = _candidate_index()
    candidate_path = job_dir / index.candidates[0].path
    candidate_path.parent.mkdir(parents=True)
    candidate_path.write_bytes(b"jpg")
    write_frame_candidate_index(job_dir, index)
    monkeypatch.setattr(main, "OUTPUTS_ROOT", outputs_root)
    monkeypatch.setattr(main, "store", store)

    response = TestClient(app).post(
        f"/api/jobs/{job_id}/frame-candidates/candidate_001/select"
    )

    assert response.status_code == 200
    assert response.json()["candidates"][0]["selected"] is True
