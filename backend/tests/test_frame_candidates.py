from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.app import main
from backend.app.frame_candidates import (
    build_frame_candidate_index,
    load_frame_candidate_index,
    reject_frame_candidate,
    select_frame_candidate,
    write_frame_candidate_index,
)
from backend.app.job_store import JobStore
from backend.app.main import app
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
    assert [candidate.id for candidate in selected_candidates] == [loaded.candidates[0].id, second_id]

    unselected = select_frame_candidate(tmp_path, second_id)
    toggled_candidate = next(candidate for candidate in unselected.candidates if candidate.id == second_id)
    assert toggled_candidate.selected is False
    assert toggled_candidate.rejected is False

    select_frame_candidate(tmp_path, second_id)
    rejected = reject_frame_candidate(tmp_path, second_id)
    rejected_candidate = next(candidate for candidate in rejected.candidates if candidate.id == second_id)
    assert rejected_candidate.selected is False
    assert rejected_candidate.rejected is True


def test_select_frame_candidate_respects_global_frame_limit(tmp_path, monkeypatch) -> None:
    video_path = write_candidate_job(tmp_path)

    def fake_extract_frame(_video_path: Path, output_path: Path, timestamp: float, _duration: float | None) -> float:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(f"jpg-{timestamp}".encode())
        return timestamp

    monkeypatch.setattr("backend.app.frame_candidates.extract_frame", fake_extract_frame)
    monkeypatch.setattr("backend.app.frame_candidates.average_hash", lambda path: path.name)
    index = build_frame_candidate_index(tmp_path, video_path, duration=120, candidates_per_chapter=2)
    write_frame_candidate_index(tmp_path, index)

    with pytest.raises(ValueError, match="frame limit"):
        select_frame_candidate(tmp_path, index.candidates[1].id, frame_limit=1)


def test_build_frame_candidate_index_includes_chapter_context(tmp_path, monkeypatch) -> None:
    video_path = write_candidate_job(tmp_path)
    (tmp_path / "transcript.json").write_text(
        json.dumps(
            {
                "text": "Intro transcript Advanced transcript",
                "segments": [
                    {"start": 5, "end": 8, "text": "Intro transcript"},
                    {"start": 70, "end": 75, "text": "Advanced transcript"},
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    def fake_extract_frame(_video_path: Path, output_path: Path, timestamp: float, _duration: float | None) -> float:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(f"jpg-{timestamp}".encode())
        return timestamp

    monkeypatch.setattr("backend.app.frame_candidates.extract_frame", fake_extract_frame)
    monkeypatch.setattr("backend.app.frame_candidates.average_hash", lambda path: path.name)

    index = build_frame_candidate_index(tmp_path, video_path, duration=120, candidates_per_chapter=1)

    assert index.chapter_contexts[0].title == "Intro"
    assert "Intro details" in index.chapter_contexts[0].note_excerpt
    assert "Intro transcript" in index.chapter_contexts[0].subtitle_excerpt


def test_load_legacy_frame_candidate_index_backfills_chapter_context(tmp_path) -> None:
    write_candidate_job(tmp_path)
    (tmp_path / "transcript.json").write_text(
        json.dumps(
            {
                "segments": [
                    {"start": 5, "end": 8, "text": "Intro transcript"},
                    {"start": 70, "end": 75, "text": "Advanced transcript"},
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    candidate = FrameCandidate(
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
    legacy_payload = {"candidates": [candidate.model_dump(mode="json")]}
    index_path = tmp_path / "review" / "frame_candidates.json"
    index_path.parent.mkdir(parents=True)
    index_path.write_text(json.dumps(legacy_payload), encoding="utf-8")

    loaded = load_frame_candidate_index(tmp_path)

    assert loaded is not None
    assert loaded.chapter_contexts[0].title == "Intro"
    assert "Intro details" in loaded.chapter_contexts[0].note_excerpt
    assert "Intro transcript" in loaded.chapter_contexts[0].subtitle_excerpt


def test_select_frame_candidate_rejects_missing_candidate(tmp_path) -> None:
    write_frame_candidate_index(tmp_path, FrameCandidateIndex())

    with pytest.raises(FileNotFoundError):
        select_frame_candidate(tmp_path, "missing")


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
    write_candidate_job(job_dir)

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
