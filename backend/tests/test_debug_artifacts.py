from __future__ import annotations

from io import BytesIO
from zipfile import ZipFile

from fastapi.testclient import TestClient

from backend.app import main
from backend.app.job_store import JobStore
from backend.app.main import app
from backend.app.models import JobStage, JobStatus


def test_job_store_exposes_debug_log_artifacts(tmp_path) -> None:
    job_id = "debug-job"
    job_dir = tmp_path / job_id
    (job_dir / "debug").mkdir(parents=True)
    (job_dir / "debug.log").write_text("job log", encoding="utf-8")
    (job_dir / "debug" / "note-model-response-attempt-1.txt").write_text("bad json", encoding="utf-8")

    store = JobStore(tmp_path)
    store.create(job_id)

    artifacts = store.refresh_artifacts(job_id)

    assert [(artifact.path, artifact.kind) for artifact in artifacts] == [
        ("debug.log", "log"),
        ("debug/note-model-response-attempt-1.txt", "log"),
    ]


def test_diagnostics_zip_api_is_explicit_and_rejects_active_jobs(tmp_path, monkeypatch) -> None:
    job_id = "diagnostics-job"
    job_dir = tmp_path / job_id
    (job_dir / "debug").mkdir(parents=True)
    (job_dir / "metadata.json").write_text(
        '{"job_id":"diagnostics-job","title":"Diagnostics","original_filename":"input.mp4"}',
        encoding="utf-8",
    )
    (job_dir / "debug.log").write_text("job log", encoding="utf-8")
    (job_dir / "debug" / "model-response.txt").write_text("raw response", encoding="utf-8")
    store = JobStore(tmp_path)
    store.create(job_id)
    store.update(
        job_id,
        status=JobStatus.running,
        stage=JobStage.generating_note,
        step="生成笔记",
        progress=65,
    )
    monkeypatch.setattr(main, "OUTPUTS_ROOT", tmp_path)
    monkeypatch.setattr(main, "store", store)
    client = TestClient(app)

    active_response = client.get(f"/api/jobs/{job_id}/diagnostics.zip")

    assert active_response.status_code == 409

    store.update(
        job_id,
        status=JobStatus.failed,
        stage=JobStage.failed,
        step="失败",
        progress=100,
        error="test failure",
    )
    response = client.get(f"/api/jobs/{job_id}/diagnostics.zip")

    assert response.status_code == 200
    assert "video-note-diagnostics-job-diagnostics.zip" in response.headers["content-disposition"]
    with ZipFile(BytesIO(response.content)) as archive:
        names = set(archive.namelist())
    assert "debug.log" in names
    assert "debug/model-response.txt" in names
    assert ".job-state.json" in names
