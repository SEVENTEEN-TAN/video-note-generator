from __future__ import annotations

from threading import Event, Thread

import pytest

from backend.app.atomic_io import atomic_write_text
from backend.app.job_executor import JobBusyError, LocalJobExecutor
from backend.app.job_store import JobStore
from backend.app.models import JobStatus
from backend.app.operation_leases import OperationLeaseStore


def test_local_job_executor_allows_non_conflicting_tasks_to_overlap() -> None:
    executor = LocalJobExecutor()
    first_started = Event()
    release_first = Event()
    second_finished = Event()
    order: list[str] = []

    def first_task() -> None:
        order.append("first-start")
        first_started.set()
        assert release_first.wait(timeout=2)
        order.append("first-end")

    def second_task() -> None:
        order.append("second")
        second_finished.set()

    first = Thread(target=lambda: executor.run(first_task))
    second = Thread(target=lambda: executor.run(second_task))
    first.start()
    assert first_started.wait(timeout=1)
    second.start()
    assert second_finished.wait(timeout=1)

    release_first.set()
    first.join(timeout=2)
    second.join(timeout=2)

    assert not first.is_alive()
    assert not second.is_alive()
    assert order == ["first-start", "second", "first-end"]


def test_cancelled_job_exits_before_its_task_starts(tmp_path) -> None:
    executor = LocalJobExecutor()
    store = JobStore(tmp_path)
    running_started = Event()
    release_running = Event()
    queued_executed = Event()

    store.create("running-job")
    store.update("running-job", status=JobStatus.running, step="字幕生成", progress=35)
    store.create("queued-job")

    def running_task(*, job_id: str, store: JobStore) -> None:
        running_started.set()
        assert release_running.wait(timeout=2)

    def queued_task(*, job_id: str, store: JobStore) -> None:
        queued_executed.set()

    running = Thread(
        target=lambda: executor.run(running_task, job_id="running-job", store=store)
    )
    queued = Thread(
        target=lambda: executor.run(queued_task, job_id="queued-job", store=store)
    )
    running.start()
    assert running_started.wait(timeout=1)
    cancellation = store.request_cancel("queued-job")
    assert cancellation is not None
    assert cancellation.status == JobStatus.cancelling
    queued.start()
    queued.join(timeout=1)

    assert not queued.is_alive()
    assert not queued_executed.is_set()
    cancelled = store.get("queued-job")
    assert cancelled is not None
    assert cancelled.status == JobStatus.cancelled

    release_running.set()
    running.join(timeout=2)
    assert not running.is_alive()


def test_job_write_lock_is_shared_with_background_execution() -> None:
    executor = LocalJobExecutor()
    task_started = Event()
    release_task = Event()

    def task(*, job_id: str) -> None:
        task_started.set()
        assert release_task.wait(timeout=2)

    worker = Thread(target=lambda: executor.run(task, job_id="shared-job"))
    worker.start()
    assert task_started.wait(timeout=1)

    with pytest.raises(JobBusyError):
        with executor.acquire("shared-job", blocking=False):
            raise AssertionError("busy job lock must not be acquired")

    with executor.acquire("different-job", blocking=False):
        pass

    release_task.set()
    worker.join(timeout=2)
    assert not worker.is_alive()


def test_separate_executors_share_the_sqlite_job_lease(tmp_path) -> None:
    first_executor = LocalJobExecutor(
        lease_ttl_seconds=2,
        heartbeat_interval_seconds=0.05,
    )
    second_executor = LocalJobExecutor(
        lease_ttl_seconds=2,
        heartbeat_interval_seconds=0.05,
    )
    first_started = Event()
    release_first = Event()

    def first_task(*, job_id: str) -> None:
        first_started.set()
        assert release_first.wait(timeout=2)

    worker = Thread(
        target=lambda: first_executor.run(
            first_task,
            job_id="cross-process-job",
            outputs_root=tmp_path,
            operation_id="operation-1",
        )
    )
    worker.start()
    assert first_started.wait(timeout=1)

    with pytest.raises(JobBusyError):
        with second_executor.acquire(
            "cross-process-job",
            blocking=False,
            outputs_root=tmp_path,
            operation_id="operation-2",
        ):
            raise AssertionError("active SQLite lease must reject a second executor")

    release_first.set()
    worker.join(timeout=2)
    assert not worker.is_alive()

    with second_executor.acquire(
        "cross-process-job",
        blocking=False,
        outputs_root=tmp_path,
        operation_id="operation-2",
    ):
        current = OperationLeaseStore(tmp_path).load("cross-process-job")
        assert current is not None
        assert current.operation_id == "operation-2"


def test_executor_binds_fencing_guard_into_task_writes(tmp_path, monkeypatch) -> None:
    clock = [100.0]
    first_store = OperationLeaseStore(
        tmp_path,
        lease_ttl_seconds=10,
        clock=lambda: clock[0],
    )
    second_store = OperationLeaseStore(
        tmp_path,
        lease_ttl_seconds=10,
        clock=lambda: clock[0],
    )
    executor = LocalJobExecutor(
        lease_ttl_seconds=10,
        heartbeat_interval_seconds=5,
    )
    monkeypatch.setattr(executor, "_lease_store", lambda _outputs_root: first_store)
    target = tmp_path / "executor-fenced-job" / "note.md"
    replacement = None

    def task(*, job_id: str) -> None:
        nonlocal replacement
        atomic_write_text(target, "current owner")
        clock[0] = 111.0
        replacement = second_store.acquire(
            job_id,
            operation_id="operation-2",
            owner_id="process-b",
        )
        assert replacement is not None
        atomic_write_text(target, "stale owner")

    with pytest.raises(JobBusyError, match="lease was lost"):
        executor.run(
            task,
            job_id="executor-fenced-job",
            outputs_root=tmp_path,
            operation_id="operation-1",
        )

    assert target.read_text(encoding="utf-8") == "current owner"
    assert replacement is not None
    assert second_store.is_current(replacement)
