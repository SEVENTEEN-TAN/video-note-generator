from __future__ import annotations

import json

from backend.app import job_migrations
from backend.app.job_migrations import CURRENT_JOB_SCHEMA_VERSION, migrate_job_directory
from backend.app.job_store import JobStore


def test_migrate_job_directory_adds_schema_version(tmp_path) -> None:
    metadata_path = tmp_path / "metadata.json"
    metadata_path.write_text(json.dumps({"job_id": "legacy"}), encoding="utf-8")

    payload = migrate_job_directory(tmp_path)

    assert payload["schema_version"] == CURRENT_JOB_SCHEMA_VERSION
    persisted = json.loads(metadata_path.read_text(encoding="utf-8"))
    assert persisted["schema_version"] == CURRENT_JOB_SCHEMA_VERSION


def test_migrate_job_directory_repairs_invalid_schema_version(tmp_path) -> None:
    metadata_path = tmp_path / "metadata.json"
    metadata_path.write_text(
        json.dumps({"job_id": "invalid", "schema_version": "not-a-number"}),
        encoding="utf-8",
    )

    payload = migrate_job_directory(tmp_path)

    assert payload["schema_version"] == CURRENT_JOB_SCHEMA_VERSION
    assert json.loads(metadata_path.read_text(encoding="utf-8"))["schema_version"] == CURRENT_JOB_SCHEMA_VERSION


def test_migrate_job_directory_preserves_future_schema_version(tmp_path) -> None:
    metadata_path = tmp_path / "metadata.json"
    metadata_path.write_text(json.dumps({"schema_version": 99}), encoding="utf-8")

    payload = migrate_job_directory(tmp_path)

    assert payload["schema_version"] == 99
    assert json.loads(metadata_path.read_text(encoding="utf-8"))["schema_version"] == 99


def test_migrate_job_directory_keeps_reads_available_when_write_fails(tmp_path, monkeypatch) -> None:
    metadata_path = tmp_path / "metadata.json"
    metadata_path.write_text(json.dumps({"job_id": "read-only"}), encoding="utf-8")
    monkeypatch.setattr(
        job_migrations,
        "_write_metadata_atomically",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(PermissionError("read only")),
    )

    payload = migrate_job_directory(tmp_path)

    assert payload["schema_version"] == CURRENT_JOB_SCHEMA_VERSION
    assert "schema_version" not in json.loads(metadata_path.read_text(encoding="utf-8"))


def test_job_history_survives_invalid_schema_version(tmp_path) -> None:
    job_dir = tmp_path / "invalid-history-job"
    job_dir.mkdir()
    (job_dir / "metadata.json").write_text(
        json.dumps(
            {
                "job_id": job_dir.name,
                "title": "Invalid schema",
                "original_filename": "input.mp4",
                "schema_version": {},
            }
        ),
        encoding="utf-8",
    )

    history = JobStore(tmp_path).list_history()

    assert len(history) == 1
    assert history[0].job_id == job_dir.name
