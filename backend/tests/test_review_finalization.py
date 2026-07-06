from __future__ import annotations

from pathlib import Path

import pytest

from backend.app.frame_candidates import write_frame_candidate_index
from backend.app.models import FrameCandidate, FrameCandidateIndex
from backend.app.review_finalization import (
    NOTE_REVIEW_PENDING_MARKER,
    finalize_reviewed_note,
    mark_note_review_pending,
)


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


def test_finalize_reviewed_note_requires_pending_marker(tmp_path) -> None:
    seed_review_job(tmp_path)

    with pytest.raises(PermissionError):
        finalize_reviewed_note(tmp_path)
