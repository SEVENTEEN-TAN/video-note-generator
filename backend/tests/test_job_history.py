from __future__ import annotations

import json

from fastapi.testclient import TestClient

from backend.app import main
from backend.app.job_store import JobStore
from backend.app.main import app
from backend.app.models import NoteStyle, NoteVersion, NoteVersionIndex


def write_history_job(
    outputs_root,
    job_id: str,
    *,
    created_at: str,
    title: str,
    original_filename: str,
    version_count: int = 1,
) -> None:
    job_dir = outputs_root / job_id
    job_dir.mkdir(parents=True)
    (job_dir / "note.md").write_text(f"# {title}", encoding="utf-8-sig")
    (job_dir / "subtitles.md").write_text("00:00:00 - 00:00:01 hello", encoding="utf-8-sig")
    (job_dir / "metadata.json").write_text(
        json.dumps(
            {
                "job_id": job_id,
                "created_at": created_at,
                "original_filename": original_filename,
                "title": title,
                "duration_seconds": 12.5,
            }
        ),
        encoding="utf-8",
    )

    versions = []
    selected_ids = []
    for index in range(1, version_count + 1):
        version_id = f"note_{index:03d}"
        version_dir = job_dir / "note_versions" / version_id
        version_dir.mkdir(parents=True)
        (version_dir / "note.md").write_text(f"# {title} {version_id}", encoding="utf-8-sig")
        versions.append(
            NoteVersion(
                id=version_id,
                label=f"{version_id} · detailed",
                note_style=NoteStyle.detailed,
                note_language="zh",
                note_model="gpt-5.5",
                note_base_url="https://api.openai.com/v1",
                frame_limit=6,
                note_path=f"note_versions/{version_id}/note.md",
                frame_dir=f"note_versions/{version_id}/frames",
                selected=True,
                active=index == version_count,
            )
        )
        selected_ids.append(version_id)
    (job_dir / "note_versions").mkdir(exist_ok=True)
    (job_dir / "note_versions" / "versions.json").write_text(
        NoteVersionIndex(
            active_version_id=selected_ids[-1],
            selected_version_ids=selected_ids,
            versions=versions,
        ).model_dump_json(indent=2),
        encoding="utf-8",
    )


def write_partial_history_job(
    outputs_root,
    job_id: str,
    *,
    created_at: str,
    title: str,
    original_filename: str,
) -> None:
    job_dir = outputs_root / job_id
    job_dir.mkdir(parents=True)
    (job_dir / "audio.mp3").write_bytes(b"partial audio")
    (job_dir / "metadata.json").write_text(
        json.dumps(
            {
                "job_id": job_id,
                "created_at": created_at,
                "original_filename": original_filename,
                "title": title,
                "duration_seconds": None,
            }
        ),
        encoding="utf-8",
    )


def test_list_jobs_returns_disk_history_with_note_version_counts(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(main, "OUTPUTS_ROOT", tmp_path)
    monkeypatch.setattr(main, "store", JobStore(tmp_path))
    write_history_job(
        tmp_path,
        "older-job",
        created_at="2026-06-20T00:00:00+00:00",
        title="Older",
        original_filename="older.mp4",
    )
    write_history_job(
        tmp_path,
        "newer-job",
        created_at="2026-06-21T00:00:00+00:00",
        title="Newer",
        original_filename="newer.mp4",
        version_count=2,
    )
    (tmp_path / ".frame-suggestions").mkdir()

    response = TestClient(app).get("/api/jobs")

    assert response.status_code == 200
    assert response.json()["jobs"] == [
        {
            "job_id": "newer-job",
            "title": "Newer",
            "original_filename": "newer.mp4",
            "created_at": "2026-06-21T00:00:00+00:00",
            "status": "succeeded",
            "duration_seconds": 12.5,
            "artifact_count": 3,
            "note_version_count": 2,
            "active_version_id": "note_002",
        },
        {
            "job_id": "older-job",
            "title": "Older",
            "original_filename": "older.mp4",
            "created_at": "2026-06-20T00:00:00+00:00",
            "status": "succeeded",
            "duration_seconds": 12.5,
            "artifact_count": 3,
            "note_version_count": 1,
            "active_version_id": "note_001",
        },
    ]


def test_list_jobs_marks_incomplete_disk_history_as_failed(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(main, "OUTPUTS_ROOT", tmp_path)
    monkeypatch.setattr(main, "store", JobStore(tmp_path))
    write_partial_history_job(
        tmp_path,
        "partial-job",
        created_at="2026-06-22T00:00:00+00:00",
        title="Partial",
        original_filename="partial.mp4",
    )

    response = TestClient(app).get("/api/jobs")

    assert response.status_code == 200
    assert response.json()["jobs"] == [
        {
            "job_id": "partial-job",
            "title": "Partial",
            "original_filename": "partial.mp4",
            "created_at": "2026-06-22T00:00:00+00:00",
            "status": "failed",
            "duration_seconds": None,
            "artifact_count": 2,
            "note_version_count": 0,
            "active_version_id": None,
        }
    ]


def test_get_job_loads_disk_history_when_job_is_not_in_memory(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(main, "OUTPUTS_ROOT", tmp_path)
    monkeypatch.setattr(main, "store", JobStore(tmp_path))
    write_history_job(
        tmp_path,
        "disk-job",
        created_at="2026-06-21T00:00:00+00:00",
        title="Disk",
        original_filename="disk.mp4",
    )

    response = TestClient(app).get("/api/jobs/disk-job")

    assert response.status_code == 200
    payload = response.json()
    assert payload["job_id"] == "disk-job"
    assert payload["status"] == "succeeded"
    assert payload["step"] == "已从历史记录载入"
    assert {artifact["path"] for artifact in payload["artifacts"]} == {"metadata.json", "note.md", "subtitles.md"}


def test_get_job_loads_incomplete_disk_history_as_failed(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(main, "OUTPUTS_ROOT", tmp_path)
    monkeypatch.setattr(main, "store", JobStore(tmp_path))
    write_partial_history_job(
        tmp_path,
        "partial-job",
        created_at="2026-06-22T00:00:00+00:00",
        title="Partial",
        original_filename="partial.mp4",
    )

    response = TestClient(app).get("/api/jobs/partial-job")

    assert response.status_code == 200
    payload = response.json()
    assert payload["job_id"] == "partial-job"
    assert payload["status"] == "failed"
    assert payload["step"] == "历史任务不完整"
    assert {artifact["path"] for artifact in payload["artifacts"]} == {"audio.mp3", "metadata.json"}


def test_delete_job_removes_disk_history(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(main, "OUTPUTS_ROOT", tmp_path)
    monkeypatch.setattr(main, "store", JobStore(tmp_path))
    write_history_job(
        tmp_path,
        "delete-job",
        created_at="2026-06-21T00:00:00+00:00",
        title="Delete",
        original_filename="delete.mp4",
    )

    response = TestClient(app).delete("/api/jobs/delete-job")

    assert response.status_code == 200
    assert response.json() == {"ok": True}
    assert not (tmp_path / "delete-job").exists()
    assert TestClient(app).get("/api/jobs/delete-job").status_code == 404


def test_delete_loaded_history_job_removes_memory_state_and_disk_files(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(main, "OUTPUTS_ROOT", tmp_path)
    monkeypatch.setattr(main, "store", JobStore(tmp_path))
    write_history_job(
        tmp_path,
        "loaded-job",
        created_at="2026-06-21T00:00:00+00:00",
        title="Loaded",
        original_filename="loaded.mp4",
    )
    client = TestClient(app, raise_server_exceptions=False)

    assert client.get("/api/jobs/loaded-job").status_code == 200
    response = client.delete("/api/jobs/loaded-job")

    assert response.status_code == 200
    assert response.json() == {"ok": True}
    assert not (tmp_path / "loaded-job").exists()
    assert main.store.get("loaded-job") is None


def test_delete_job_returns_json_error_when_files_are_in_use(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(main, "OUTPUTS_ROOT", tmp_path)
    monkeypatch.setattr(main, "store", JobStore(tmp_path))
    write_history_job(
        tmp_path,
        "locked-job",
        created_at="2026-06-21T00:00:00+00:00",
        title="Locked",
        original_filename="locked.mp4",
    )

    def fail_rmtree(_path) -> None:
        raise PermissionError("file is locked")

    monkeypatch.setattr(main.shutil, "rmtree", fail_rmtree)

    response = TestClient(app, raise_server_exceptions=False).delete("/api/jobs/locked-job")

    assert response.status_code == 409
    assert "files are in use" in response.json()["detail"]
    assert (tmp_path / "locked-job").exists()
