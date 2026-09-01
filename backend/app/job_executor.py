from __future__ import annotations

from collections.abc import Callable
from contextlib import contextmanager
from pathlib import Path
from threading import Lock, Thread
from typing import Any, Iterator

from .operation_leases import (
    DEFAULT_HEARTBEAT_INTERVAL_SECONDS,
    DEFAULT_LEASE_TTL_SECONDS,
    JobOperationLease,
    LeaseHeartbeat,
    OperationLeaseLostError,
    OperationLeaseStore,
    bind_current_operation_lease,
)
from .operation_store import (
    OperationStatus,
    create_job_operation,
    describe_task_operation,
    sync_operation_with_job_state,
    update_job_operation,
)


class JobBusyError(RuntimeError):
    pass


class LocalJobExecutor:
    """Serialize one job locally and, when a root is supplied, across processes."""

    def __init__(
        self,
        *,
        lease_ttl_seconds: float = DEFAULT_LEASE_TTL_SECONDS,
        heartbeat_interval_seconds: float = DEFAULT_HEARTBEAT_INTERVAL_SECONDS,
    ) -> None:
        self._lease_ttl_seconds = lease_ttl_seconds
        self._heartbeat_interval_seconds = heartbeat_interval_seconds
        self._job_locks_guard = Lock()
        self._job_locks: dict[str, Lock] = {}
        self._lease_stores: dict[str, OperationLeaseStore] = {}

    @staticmethod
    def _finish_cancelled_before_start(kwargs: dict[str, Any]) -> bool:
        job_id = kwargs.get("job_id")
        store = kwargs.get("store")
        if not isinstance(job_id, str) or store is None:
            return False
        is_cancel_requested = getattr(store, "is_cancel_requested", None)
        mark_cancelled = getattr(store, "mark_cancelled", None)
        if not callable(is_cancel_requested) or not callable(mark_cancelled):
            return False
        if not is_cancel_requested(job_id):
            return False
        mark_cancelled(job_id)
        return True

    def run(
        self,
        task: Callable[..., Any],
        *,
        outputs_root: Path | None = None,
        operation_id: str = "",
        existing_lease: JobOperationLease | None = None,
        **kwargs: Any,
    ) -> Any:
        job_id = kwargs.get("job_id")
        if not isinstance(job_id, str):
            if self._finish_cancelled_before_start(kwargs):
                return None
            return task(**kwargs)
        with self.acquire(
            job_id,
            outputs_root=outputs_root,
            operation_id=operation_id,
            existing_lease=existing_lease,
        ) as heartbeat:
            if self._finish_cancelled_before_start(kwargs):
                return None
            try:
                result = task(**kwargs)
                _assert_heartbeat_current(heartbeat, job_id)
                return result
            except OperationLeaseLostError as exc:
                raise JobBusyError(
                    f"Cross-process lease was lost while modifying job: {job_id}"
                ) from exc

    @contextmanager
    def acquire(
        self,
        job_id: str,
        *,
        blocking: bool = True,
        outputs_root: Path | None = None,
        operation_id: str = "",
        existing_lease: JobOperationLease | None = None,
    ) -> Iterator[LeaseHeartbeat | None]:
        lock = self._job_lock(job_id)
        acquired = lock.acquire(blocking=blocking)
        if not acquired:
            raise JobBusyError(f"Job is already being modified: {job_id}")
        heartbeat: LeaseHeartbeat | None = None
        try:
            if outputs_root is not None:
                lease_store = self._lease_store(outputs_root)
                lease = existing_lease or lease_store.acquire(
                    job_id,
                    operation_id=operation_id,
                )
                if lease is None:
                    raise JobBusyError(f"Job is owned by another process: {job_id}")
                heartbeat = LeaseHeartbeat(
                    lease_store,
                    lease,
                    interval_seconds=self._heartbeat_interval_seconds,
                )
                if not heartbeat.start():
                    heartbeat.close()
                    heartbeat = None
                    raise JobBusyError(f"Job lease is no longer current: {job_id}")
            with bind_current_operation_lease(heartbeat):
                yield heartbeat
        finally:
            if heartbeat is not None:
                heartbeat.close()
            lock.release()

    def _job_lock(self, job_id: str) -> Lock:
        with self._job_locks_guard:
            return self._job_locks.setdefault(job_id, Lock())

    def _lease_store(self, outputs_root: Path) -> OperationLeaseStore:
        key = str(outputs_root.resolve()).casefold()
        with self._job_locks_guard:
            return self._lease_stores.setdefault(
                key,
                OperationLeaseStore(
                    outputs_root,
                    lease_ttl_seconds=self._lease_ttl_seconds,
                ),
            )


job_executor = LocalJobExecutor()


def run_serialized_job(
    task: Callable[..., Any],
    *,
    _operation_id: str | None = None,
    _recovery: bool = False,
    _lease: JobOperationLease | None = None,
    **kwargs: Any,
) -> Any:
    job_dir = kwargs.get("job_dir")
    if isinstance(job_dir, str):
        job_dir = Path(job_dir)
    job_id = kwargs.get("job_id")
    outputs_root = job_dir.parent if isinstance(job_dir, Path) else None
    if not isinstance(job_id, str):
        return job_executor.run(task, **kwargs)
    try:
        with job_executor.acquire(
            job_id,
            outputs_root=outputs_root,
            operation_id=_operation_id or "",
            existing_lease=_lease,
        ) as heartbeat:
            if job_executor._finish_cancelled_before_start(kwargs):
                return None
            if job_dir is not None and _operation_id:
                update_job_operation(
                    job_dir,
                    operation_id=_operation_id,
                    status=OperationStatus.running,
                    increment_attempt=True,
                    increment_recovery=_recovery,
                    allow_terminal_restart=_recovery,
                    error="",
                )
            try:
                result = task(**kwargs)
                _assert_heartbeat_current(heartbeat, job_id)
                return result
            except Exception as exc:
                if (
                    job_dir is not None
                    and _operation_id
                    and (heartbeat is None or not heartbeat.lost.is_set())
                ):
                    update_job_operation(
                        job_dir,
                        operation_id=_operation_id,
                        status=OperationStatus.failed,
                        error=str(exc),
                    )
                raise
            finally:
                if (
                    job_dir is not None
                    and _operation_id
                    and (heartbeat is None or not heartbeat.lost.is_set())
                ):
                    _sync_operation_from_store(job_dir, kwargs)
    except (JobBusyError, OperationLeaseLostError):
        # A different process owns the authoritative execution. Do not let a
        # duplicate background callback overwrite its operation or job state.
        return None


def enqueue_serialized(background_tasks: Any, task: Callable[..., Any], **kwargs: Any) -> None:
    job_id = kwargs.get("job_id")
    job_dir = kwargs.get("job_dir")
    operation_id: str | None = None
    if isinstance(job_id, str) and job_dir is not None:
        required_credentials, parameters = describe_task_operation(task.__name__, kwargs)
        operation = create_job_operation(
            job_dir=job_dir,
            job_id=job_id,
            operation_type=task.__name__,
            required_credentials=required_credentials,
            parameters=parameters,
        )
        operation_id = operation.id
    background_tasks.add_task(
        run_serialized_job,
        task,
        _operation_id=operation_id,
        **kwargs,
    )


def start_recovered_job(
    task: Callable[..., Any],
    *,
    operation_id: str,
    _lease: JobOperationLease | None = None,
    **kwargs: Any,
) -> Thread:
    thread = Thread(
        target=run_serialized_job,
        kwargs={
            "task": task,
            "_operation_id": operation_id,
            "_lease": _lease,
            **kwargs,
        },
        name=f"video-note-recovery-{kwargs.get('job_id', 'job')}",
        daemon=True,
    )
    thread.start()
    return thread


def _sync_operation_from_store(job_dir: Any, kwargs: dict[str, Any]) -> None:
    store = kwargs.get("store")
    job_id = kwargs.get("job_id")
    if store is None or not isinstance(job_id, str):
        return
    state = store.get(job_id)
    if state is None:
        return
    sync_operation_with_job_state(
        job_dir,
        job_status=str(getattr(state.status, "value", state.status)),
        stage=str(getattr(state.stage, "value", state.stage)),
        step=state.step,
        progress=state.progress,
        error=state.error or "",
    )


def _assert_heartbeat_current(
    heartbeat: LeaseHeartbeat | None,
    job_id: str,
) -> None:
    if heartbeat is None:
        return
    try:
        heartbeat.assert_current()
    except OperationLeaseLostError as exc:
        raise JobBusyError(
            f"Cross-process lease was lost while modifying job: {job_id}"
        ) from exc
