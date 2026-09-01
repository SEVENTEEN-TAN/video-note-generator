from __future__ import annotations

from threading import Event, Thread

from backend.app.job_executor import LocalJobExecutor, enqueue_serialized
from backend.app.job_store import JobStore
from backend.app.models import JobStatus
from backend.app.operation_store import (
    OperationStatus,
    create_job_operation,
    load_job_operation,
    operation_path,
    update_job_operation,
)
from backend.app.operation_leases import OperationLeaseStore


class CapturedBackgroundTasks:
    def __init__(self) -> None:
        self.calls: list[tuple] = []

    def add_task(self, function, *args, **kwargs) -> None:
        self.calls.append((function, args, kwargs))


def test_enqueue_persists_sanitized_operation_and_tracks_completion(tmp_path) -> None:
    job_id = "operation-job"
    job_dir = tmp_path / job_id
    job_dir.mkdir()
    store = JobStore(tmp_path)
    store.create(job_id)
    background = CapturedBackgroundTasks()

    class Config:
        transcription_mode = "local_faster_whisper"
        note_api_key = "secret-note-key"
        transcription_api_key = "secret-transcription-key"

    def process_transcription_job(*, job_id, job_dir, config, store) -> None:
        store.update(
            job_id,
            status=JobStatus.awaiting_subtitle_confirmation,
            step="等待确认字幕",
            progress=40,
        )

    enqueue_serialized(
        background,
        process_transcription_job,
        job_id=job_id,
        job_dir=job_dir,
        config=Config(),
        store=store,
    )

    queued = load_job_operation(job_dir)
    assert queued is not None
    assert queued.status == OperationStatus.queued
    operation_text = operation_path(job_dir).read_text(encoding="utf-8")
    assert "secret-note-key" not in operation_text
    assert "secret-transcription-key" not in operation_text

    function, args, kwargs = background.calls[0]
    function(*args, **kwargs)

    completed = load_job_operation(job_dir)
    assert completed is not None
    assert completed.id == queued.id
    assert completed.status == OperationStatus.completed
    assert completed.stage == "awaiting_subtitle_review"
    assert completed.attempt == 1
    released = OperationLeaseStore(tmp_path).load(job_id)
    assert released is not None
    assert released.operation_id == queued.id
    assert released.lease_expires_at == 0

    next_lease = OperationLeaseStore(tmp_path).acquire(
        job_id,
        operation_id="next-operation",
        owner_id="next-owner",
    )
    assert next_lease is not None
    assert next_lease.revision == released.revision + 1


def test_remote_transcription_operation_records_credential_requirement_not_value(tmp_path) -> None:
    job_dir = tmp_path / "remote-job"
    job_dir.mkdir()
    background = CapturedBackgroundTasks()

    class Config:
        transcription_mode = "audio_transcriptions"
        transcription_api_key = "actual-secret"

    def process_transcription_job(**_kwargs) -> None:
        return None

    enqueue_serialized(
        background,
        process_transcription_job,
        job_id="remote-job",
        job_dir=job_dir,
        config=Config(),
    )

    operation = load_job_operation(job_dir)
    assert operation is not None
    assert operation.required_credentials == ["transcription_service"]
    assert "actual-secret" not in operation_path(job_dir).read_text(encoding="utf-8")
    assert "api_key" not in operation_path(job_dir).read_text(encoding="utf-8")


def test_stale_operation_update_does_not_overwrite_newer_operation(tmp_path) -> None:
    job_dir = tmp_path / "job"
    job_dir.mkdir()
    first = create_job_operation(job_dir=job_dir, job_id="job", operation_type="first")
    second = create_job_operation(job_dir=job_dir, job_id="job", operation_type="second")

    update_job_operation(
        job_dir,
        operation_id=first.id,
        status=OperationStatus.failed,
        error="stale failure",
    )

    current = load_job_operation(job_dir)
    assert current is not None
    assert current.id == second.id
    assert current.status == OperationStatus.queued
    assert current.error == ""


def test_local_job_executor_serializes_tasks_for_the_same_job() -> None:
    executor = LocalJobExecutor()
    first_started = Event()
    release_first = Event()
    second_started = Event()

    def first_task(*, job_id: str) -> None:
        first_started.set()
        assert release_first.wait(timeout=2)

    def second_task(*, job_id: str) -> None:
        second_started.set()

    first = Thread(target=lambda: executor.run(first_task, job_id="same-job"))
    second = Thread(target=lambda: executor.run(second_task, job_id="same-job"))
    first.start()
    assert first_started.wait(timeout=1)
    second.start()

    assert not second_started.wait(timeout=0.1)
    release_first.set()
    first.join(timeout=2)
    second.join(timeout=2)

    assert second_started.is_set()
    assert not first.is_alive()
    assert not second.is_alive()
