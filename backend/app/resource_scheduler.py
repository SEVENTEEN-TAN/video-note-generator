from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from enum import Enum
from threading import BoundedSemaphore


class ProcessingResource(str, Enum):
    ffmpeg = "ffmpeg"
    cpu_asr = "cpu_asr"
    gpu_asr = "gpu_asr"


class ResourceWaitCancelled(RuntimeError):
    pass


class ResourceScheduler:
    """Small stage-level scheduler for resource-heavy local operations."""

    def __init__(self) -> None:
        self._semaphores = {
            resource: BoundedSemaphore(1)
            for resource in ProcessingResource
        }

    @contextmanager
    def acquire(
        self,
        resource: ProcessingResource,
        *,
        is_cancelled: Callable[[], bool] | None = None,
        poll_seconds: float = 0.1,
        on_wait: Callable[[], None] | None = None,
    ) -> Iterator[None]:
        semaphore = self._semaphores[resource]
        acquired = False
        try:
            while not acquired:
                if is_cancelled and is_cancelled():
                    raise ResourceWaitCancelled(f"Waiting for {resource.value} was cancelled.")
                if on_wait:
                    on_wait()
                acquired = semaphore.acquire(timeout=max(0.001, poll_seconds))
            yield
        finally:
            if acquired:
                semaphore.release()


processing_resources = ResourceScheduler()
