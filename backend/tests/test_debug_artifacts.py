from __future__ import annotations

from backend.app.job_store import JobStore


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
