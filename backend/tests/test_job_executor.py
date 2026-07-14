from __future__ import annotations

from threading import Event, Thread

from backend.app.job_executor import LocalJobExecutor
from backend.app.job_store import JobStore
from backend.app.models import JobStatus


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
