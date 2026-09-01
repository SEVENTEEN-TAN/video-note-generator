from __future__ import annotations

import json

from fastapi.testclient import TestClient

from backend.app import main
from backend.app.main import app
from backend.app.job_store import JobStore
from backend.app.models import NoteStyle, NoteVersion, NoteVersionIndex
from backend.app.note_versions import write_note_version_index
from backend.app.operation_recovery import recover_incomplete_operations
from backend.app.operation_leases import LeaseHeartbeat, OperationLeaseLostError, OperationLeaseStore
from backend.app.operation_store import (
    OperationStatus,
    create_job_operation,
    load_job_operation,
    update_job_operation,
)
from backend.app.processor import (
    process_transcription_job,
    resume_note_review_artifacts_job,
)


def write_metadata(job_dir, *, transcription_mode: str) -> None:
    (job_dir / "metadata.json").write_text(
        json.dumps(
            {
                "job_id": job_dir.name,
                "title": "Recovery",
                "original_filename": "input.mp4",
                "transcription_mode": transcription_mode,
                "transcription_base_url": "https://api.example.test/v1",
                "transcription_model": "small",
                "local_whisper_device": "cpu",
                "local_whisper_compute_type": "int8",
                "performance_mode": "balanced",
                "transcription_language": "zh",
                "note_base_url": "https://api.example.test/v1",
                "note_model": "example-model",
                "note_language": "zh",
                "note_style": "detailed",
                "frame_limit": 6,
                "duration_seconds": 120,
            }
        ),
        encoding="utf-8",
    )


def seed_source_video(job_dir) -> None:
    source = job_dir / "source_video" / "input.mp4"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"video")


def test_startup_recovery_requeues_local_transcription_without_secrets(tmp_path) -> None:
    job_id = "local-recovery"
    job_dir = tmp_path / job_id
    seed_source_video(job_dir)
    write_metadata(job_dir, transcription_mode="local_faster_whisper")
    operation = create_job_operation(
        job_dir=job_dir,
        job_id=job_id,
        operation_type="process_transcription_job",
    )
    update_job_operation(
        job_dir,
        operation_id=operation.id,
        status=OperationStatus.running,
        stage="transcribing",
        progress=35,
    )
    started: list[tuple] = []

    decisions = recover_incomplete_operations(
        tmp_path,
        JobStore(tmp_path),
        starter=lambda task, **kwargs: started.append((task, kwargs)),
    )

    assert decisions[0].action == "started"
    assert started[0][0] is process_transcription_job
    kwargs = started[0][1]
    assert kwargs["job_id"] == job_id
    assert kwargs["config"].transcription_api_key == ""
    assert not hasattr(kwargs["config"], "note_api_key")
    persisted = (job_dir / ".operation.json").read_text(encoding="utf-8")
    assert "note_api_key" not in persisted
    assert load_job_operation(job_dir).status == OperationStatus.recovering

    repeated = recover_incomplete_operations(
        tmp_path,
        JobStore(tmp_path),
        starter=lambda task, **kwargs: started.append((task, kwargs)),
    )

    assert repeated[0].action == "skipped"
    assert repeated[0].reason == "already_claimed"
    assert len(started) == 1


def test_startup_recovery_does_not_touch_an_operation_owned_by_another_instance(tmp_path) -> None:
    job_id = "leased-recovery"
    job_dir = tmp_path / job_id
    seed_source_video(job_dir)
    write_metadata(job_dir, transcription_mode="local_faster_whisper")
    operation = create_job_operation(
        job_dir=job_dir,
        job_id=job_id,
        operation_type="process_transcription_job",
    )
    update_job_operation(
        job_dir,
        operation_id=operation.id,
        status=OperationStatus.running,
        stage="transcribing",
        progress=35,
    )
    lease = OperationLeaseStore(tmp_path).acquire(
        job_id,
        operation_id=operation.id,
        owner_id="already-running-instance",
    )
    assert lease is not None
    operation_before = (job_dir / ".operation.json").read_bytes()
    started: list[tuple] = []

    decisions = recover_incomplete_operations(
        tmp_path,
        JobStore(tmp_path),
        starter=lambda task, **kwargs: started.append((task, kwargs)),
    )

    assert decisions == [
        decisions[0].__class__(job_id, operation.id, "skipped", "already_claimed")
    ]
    assert started == []
    assert (job_dir / ".operation.json").read_bytes() == operation_before


def test_startup_recovery_skips_cleanly_if_its_claimed_lease_is_lost(tmp_path, monkeypatch) -> None:
    job_id = "lost-recovery-claim"
    job_dir = tmp_path / job_id
    seed_source_video(job_dir)
    write_metadata(job_dir, transcription_mode="local_faster_whisper")
    operation = create_job_operation(
        job_dir=job_dir,
        job_id=job_id,
        operation_type="process_transcription_job",
    )
    update_job_operation(
        job_dir,
        operation_id=operation.id,
        status=OperationStatus.running,
        stage="transcribing",
        progress=35,
    )
    started: list[tuple] = []
    monkeypatch.setattr(
        LeaseHeartbeat,
        "assert_current",
        lambda self: (_ for _ in ()).throw(
            OperationLeaseLostError(f"replaced: {self.lease.job_id}")
        ),
    )

    decisions = recover_incomplete_operations(
        tmp_path,
        JobStore(tmp_path),
        starter=lambda task, **kwargs: started.append((task, kwargs)),
    )

    assert decisions[0].action == "skipped"
    assert decisions[0].reason == "lease_lost"
    assert started == []


def test_startup_recovery_waits_for_remote_transcription_credentials(tmp_path) -> None:
    job_id = "remote-recovery"
    job_dir = tmp_path / job_id
    seed_source_video(job_dir)
    write_metadata(job_dir, transcription_mode="audio_transcriptions")
    operation = create_job_operation(
        job_dir=job_dir,
        job_id=job_id,
        operation_type="process_transcription_job",
        required_credentials=["transcription_service"],
    )
    update_job_operation(
        job_dir,
        operation_id=operation.id,
        status=OperationStatus.running,
        stage="transcribing",
        progress=35,
    )
    started: list[tuple] = []
    store = JobStore(tmp_path)

    decisions = recover_incomplete_operations(
        tmp_path,
        store,
        starter=lambda task, **kwargs: started.append((task, kwargs)),
    )

    assert started == []
    assert decisions[0].action == "waiting_for_retry"
    assert decisions[0].reason == "credentials_required"
    recovered = load_job_operation(job_dir)
    assert recovered is not None
    assert recovered.status == OperationStatus.waiting_for_credentials
    assert "transcription service credential" in recovered.error
    assert store.get(job_id).status.value == "failed"

    reloaded_store = JobStore(tmp_path)
    reloaded = reloaded_store.load_from_disk(job_id)
    assert reloaded is not None
    assert reloaded.status.value == "failed"
    assert reloaded.step == "等待重试"
    assert "transcription service credential" in (reloaded.error or "")


def test_startup_recovery_resumes_deterministic_review_preparation(tmp_path) -> None:
    job_id = "review-recovery"
    job_dir = tmp_path / job_id
    seed_source_video(job_dir)
    write_metadata(job_dir, transcription_mode="local_faster_whisper")
    (job_dir / "note.md").write_text("# Current note", encoding="utf-8")
    version_dir = job_dir / "note_versions" / "note_001"
    (version_dir / "frames").mkdir(parents=True)
    (version_dir / "note.md").write_text("# Current note", encoding="utf-8")
    write_note_version_index(
        job_dir,
        NoteVersionIndex(
            active_version_id="note_001",
            selected_version_ids=["note_001"],
            versions=[
                NoteVersion(
                    id="note_001",
                    label="Recovered note",
                    note_style=NoteStyle.detailed,
                    note_language="zh",
                    note_model="example-model",
                    note_base_url="https://api.example.test/v1",
                    frame_limit=6,
                    note_path="note_versions/note_001/note.md",
                    frame_dir="note_versions/note_001/frames",
                )
            ],
        ),
    )
    operation = create_job_operation(
        job_dir=job_dir,
        job_id=job_id,
        operation_type="regenerate_note_job",
        required_credentials=["note_service"],
    )
    update_job_operation(
        job_dir,
        operation_id=operation.id,
        status=OperationStatus.running,
        stage="preparing_review",
        progress=88,
    )
    started: list[tuple] = []

    decisions = recover_incomplete_operations(
        tmp_path,
        JobStore(tmp_path),
        starter=lambda task, **kwargs: started.append((task, kwargs)),
    )

    assert decisions[0].action == "started"
    assert started[0][0] is resume_note_review_artifacts_job
    assert started[0][1]["video_path"] == job_dir / "source_video" / "input.mp4"


def test_startup_recovery_reconciles_existing_review_marker(tmp_path) -> None:
    job_id = "already-reviewing"
    job_dir = tmp_path / job_id
    job_dir.mkdir()
    write_metadata(job_dir, transcription_mode="local_faster_whisper")
    (job_dir / "note.md").write_text("# Ready", encoding="utf-8")
    (job_dir / ".note-review.pending").write_text("1", encoding="utf-8")
    operation = create_job_operation(
        job_dir=job_dir,
        job_id=job_id,
        operation_type="regenerate_note_job",
        required_credentials=["note_service"],
    )
    update_job_operation(
        job_dir,
        operation_id=operation.id,
        status=OperationStatus.running,
        stage="preparing_review",
    )
    started: list[tuple] = []

    decisions = recover_incomplete_operations(
        tmp_path,
        JobStore(tmp_path),
        starter=lambda task, **kwargs: started.append((task, kwargs)),
    )

    assert started == []
    assert decisions[0].action == "reconciled"
    assert load_job_operation(job_dir).status == OperationStatus.completed


def test_application_lifespan_runs_operation_recovery(tmp_path, monkeypatch) -> None:
    calls: list[tuple] = []
    store = JobStore(tmp_path)
    monkeypatch.setattr(main, "OUTPUTS_ROOT", tmp_path)
    monkeypatch.setattr(main, "store", store)
    monkeypatch.setattr(
        main,
        "recover_incomplete_operations",
        lambda outputs_root, current_store: calls.append((outputs_root, current_store)),
    )

    with TestClient(app) as client:
        response = client.get("/api/ready")

    assert response.status_code == 200
    assert calls == [(tmp_path, store)]
