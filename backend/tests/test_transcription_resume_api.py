from __future__ import annotations

import json

from fastapi.testclient import TestClient

from backend.app import main
from backend.app.job_store import JobStore
from backend.app.main import app
from backend.app.models import JobStatus


def _write_job(job_dir, *, mode: str) -> None:
    (job_dir / "source_video").mkdir(parents=True)
    (job_dir / "source_video" / "input.mp4").write_bytes(b"video")
    (job_dir / "metadata.json").write_text(
        json.dumps(
            {
                "job_id": job_dir.name,
                "title": "Resume",
                "original_filename": "input.mp4",
                "transcription_mode": mode,
                "transcription_model": "small",
                "local_whisper_device": "cpu",
                "local_whisper_compute_type": "int8",
                "performance_mode": "accurate",
                "transcription_language": "zh",
                "note_base_url": "https://api.openai.com/v1",
                "note_model": "gpt-5.5",
                "note_language": "zh",
                "note_style": "detailed",
                "frame_limit": 6,
            }
        ),
        encoding="utf-8",
    )


def test_resume_cancelled_local_transcription_requeues_saved_job(tmp_path, monkeypatch) -> None:
    job_id = "resume-api"
    job_dir = tmp_path / job_id
    _write_job(job_dir, mode="local_faster_whisper")
    store = JobStore(tmp_path)
    store.create(job_id)
    store.update(job_id, status=JobStatus.running, step="字幕生成", progress=45)
    store.request_cancel(job_id)
    store.mark_cancelled(job_id)
    monkeypatch.setattr(main, "OUTPUTS_ROOT", tmp_path)
    monkeypatch.setattr(main, "store", store)
    queued: list[tuple] = []
    monkeypatch.setattr(
        main,
        "enqueue_serialized",
        lambda background_tasks, task, **kwargs: queued.append((task, kwargs)),
    )
    monkeypatch.setattr(main, "ensure_local_transcription_ready", lambda _config: None)

    response = TestClient(app).post(f"/api/jobs/{job_id}/transcription/resume")

    assert response.status_code == 200
    assert response.json()["resumed"] is True
    assert store.get(job_id).status == JobStatus.pending
    assert len(queued) == 1
    task, kwargs = queued[0]
    assert task is main.process_transcription_job
    assert kwargs["video_path"] == job_dir / "source_video" / "input.mp4"
    assert kwargs["config"].performance_mode.value == "accurate"
    assert kwargs["config"].transcription_language == "zh"


def test_resume_transcription_rejects_remote_and_running_jobs(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(main, "OUTPUTS_ROOT", tmp_path)
    store = JobStore(tmp_path)
    monkeypatch.setattr(main, "store", store)

    remote_id = "remote-resume"
    _write_job(tmp_path / remote_id, mode="audio_transcriptions")
    store.create(remote_id)
    store.update(remote_id, status=JobStatus.failed, step="失败", progress=50)

    running_id = "running-resume"
    _write_job(tmp_path / running_id, mode="local_faster_whisper")
    store.create(running_id)
    store.update(running_id, status=JobStatus.running, step="字幕生成", progress=45)

    client = TestClient(app)
    assert client.post(f"/api/jobs/{remote_id}/transcription/resume").status_code == 409
    assert client.post(f"/api/jobs/{running_id}/transcription/resume").status_code == 409
