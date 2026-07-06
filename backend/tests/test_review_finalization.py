from __future__ import annotations

from pathlib import Path
from zipfile import ZipFile

import pytest
from fastapi.testclient import TestClient

from backend.app import main
from backend.app.frame_candidates import write_frame_candidate_index
from backend.app.job_store import JobStore
from backend.app.main import app
from backend.app.models import (
    Chapter,
    FrameCandidate,
    FrameCandidateIndex,
    JobStatus,
    KeyMoment,
    NoteDraft,
)
from backend.app.note_chunks import NoteChunkIndex, NoteChunkMeta, chunk_index_path, chunks_dir
from backend.app.processor import create_zip
from backend.app.review_finalization import (
    NOTE_REVIEW_PENDING_MARKER,
    finalize_reviewed_note,
    mark_note_review_pending,
)
from backend.app.review_drafts import build_review_draft, update_review_draft_paragraph


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


def test_finalize_reviewed_note_uses_human_review_draft_body(tmp_path) -> None:
    seed_review_job(tmp_path)
    draft = build_review_draft(tmp_path)
    update_review_draft_paragraph(
        tmp_path,
        draft.paragraphs[0].id,
        body="Human approved intro.",
        selected_frame_ids=["chapter_001_candidate_001"],
        status="approved",
    )
    mark_note_review_pending(tmp_path)

    finalize_reviewed_note(tmp_path)

    note_text = (tmp_path / "note.md").read_text(encoding="utf-8-sig")
    assert "Human approved intro." in note_text
    assert "Intro detail." not in note_text
    assert "![Selected intro frame](frames/frame_001.jpg)" in note_text


def test_finalize_reviewed_note_requires_pending_marker(tmp_path) -> None:
    seed_review_job(tmp_path)

    with pytest.raises(PermissionError):
        finalize_reviewed_note(tmp_path)


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


def test_finalize_endpoint_writes_zip_and_returns_succeeded_state(tmp_path, monkeypatch) -> None:
    outputs_root = tmp_path / "outputs"
    job_id = "finalize-job"
    job_dir = outputs_root / job_id
    job_dir.mkdir(parents=True)
    seed_review_job(job_dir)
    (job_dir / "transcript.json").write_text(
        '{"text":"hello","segments":[{"start":0,"end":1,"text":"hello"}]}',
        encoding="utf-8",
    )
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
        (job_dir / "note.md").write_text(
            "# Regenerated chunk\n\n### Opening\n\n`00:00:00 - 00:00:01`\n\nNew detail\n",
            encoding="utf-8-sig",
        )
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
