from __future__ import annotations

from collections.abc import Callable
from typing import Any


class LocalJobExecutor:
    """Launch jobs independently; heavy stages coordinate through resource_scheduler."""

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

    def run(self, task: Callable[..., Any], **kwargs: Any) -> Any:
        if self._finish_cancelled_before_start(kwargs):
            return None
        return task(**kwargs)


job_executor = LocalJobExecutor()


def run_serialized_job(task: Callable[..., Any], **kwargs: Any) -> Any:
    return job_executor.run(task, **kwargs)


def enqueue_serialized(background_tasks: Any, task: Callable[..., Any], **kwargs: Any) -> None:
    background_tasks.add_task(run_serialized_job, task, **kwargs)
