from __future__ import annotations

import json

from fastapi.testclient import TestClient

from backend.app import main
from backend.app.job_state import load_job_state
from backend.app.job_store import JobStore
from backend.app.main import app
from backend.app.models import JobStatus, TranscriptionWorkProgress
from backend.app.storage_policy import (
    cleanup_transcription_cache,
    estimate_local_job_storage,
    job_storage_usage,
)


def test_local_storage_estimate_includes_audio_cache_frames_and_headroom() -> None:
    estimate = estimate_local_job_storage(
        source_bytes=1_000_000_000,
        duration_seconds=2 * 3600,
        frame_limit=12,
    )

    assert estimate.mp3_bytes > 0
    assert estimate.asr_work_bytes > estimate.mp3_bytes
    assert estimate.frame_bytes > 0
    assert estimate.temporary_headroom_bytes > 0
    assert estimate.required_free_bytes >= (
        estimate.mp3_bytes + estimate.asr_work_bytes + estimate.frame_bytes
    )


def test_cleanup_transcription_cache_preserves_public_and_review_artifacts(tmp_path) -> None:
    job_dir = tmp_path / "job"
    cache_dir = job_dir / "work" / "asr"
    cache_dir.mkdir(parents=True)
    (cache_dir / "chunk.flac").write_bytes(b"cache" * 100)
    (job_dir / "audio.mp3").write_bytes(b"audio")
    (job_dir / "transcript.json").write_text("{}", encoding="utf-8")
    (job_dir / "note.md").write_text("# note", encoding="utf-8")
    (job_dir / "frames").mkdir()
    (job_dir / "frames" / "frame.jpg").write_bytes(b"frame")

    before = job_storage_usage(job_dir)
    freed = cleanup_transcription_cache(job_dir)
    after = job_storage_usage(job_dir)

    assert freed >= 500
    assert before.cache_bytes >= 500
    assert after.cache_bytes == 0
    assert (job_dir / "audio.mp3").exists()
    assert (job_dir / "transcript.json").exists()
    assert (job_dir / "note.md").exists()
    assert (job_dir / "frames" / "frame.jpg").exists()


def test_storage_usage_separates_cache_from_total(tmp_path) -> None:
    job_dir = tmp_path / "job"
    (job_dir / "work" / "asr").mkdir(parents=True)
    (job_dir / "work" / "asr" / "cache.bin").write_bytes(b"c" * 10)
    (job_dir / "note.md").write_bytes(b"n" * 5)

    usage = job_storage_usage(job_dir)

    assert usage.cache_bytes == 10
    assert usage.total_bytes == 15
    assert usage.final_bytes == 5


def test_cache_cleanup_api_rejects_active_job_and_preserves_final_files(tmp_path, monkeypatch) -> None:
    job_id = "storage-api"
    job_dir = tmp_path / job_id
    cache_dir = job_dir / "work" / "asr"
    cache_dir.mkdir(parents=True)
    (cache_dir / "cache.bin").write_bytes(b"cache")
    (job_dir / "note.md").write_text("# note", encoding="utf-8")
    (job_dir / "metadata.json").write_text(
        json.dumps({"job_id": job_id, "title": "Storage", "original_filename": "input.mp4"}),
        encoding="utf-8",
    )
    store = JobStore(tmp_path)
    store.create(job_id)
    store.update(
        job_id,
        status=JobStatus.running,
        step="字幕生成",
        progress=35,
        work_progress=TranscriptionWorkProgress(
            completed_seconds=60,
            total_seconds=120,
            completed_chunks=2,
            total_chunks=4,
            resumable=True,
            cache_hits=2,
        ),
    )
    monkeypatch.setattr(main, "OUTPUTS_ROOT", tmp_path)
    monkeypatch.setattr(main, "store", store)
    client = TestClient(app)

    assert client.delete(f"/api/jobs/{job_id}/transcription/cache").status_code == 409

    store.update(job_id, status=JobStatus.failed, step="失败", progress=35)
    revision_before_cleanup = store.get(job_id).state_revision
    response = client.delete(f"/api/jobs/{job_id}/transcription/cache")

    assert response.status_code == 200
    assert response.json()["freed_bytes"] == 5
    assert not cache_dir.exists()
    assert (job_dir / "note.md").exists()
    state = store.get(job_id)
    persisted = load_job_state(job_dir)
    assert state is not None
    assert state.work_progress is not None
    assert state.work_progress.resumable is False
    assert state.work_progress.cache_hits == 0
    assert state.state_revision == revision_before_cleanup + 1
    assert persisted is not None
    assert persisted.work_progress == state.work_progress
    assert persisted.state_revision == state.state_revision
