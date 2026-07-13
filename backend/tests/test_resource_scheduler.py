from __future__ import annotations

from threading import Event, Thread

import pytest

from backend.app.resource_scheduler import ProcessingResource, ResourceScheduler, ResourceWaitCancelled


def test_same_heavy_resource_is_serialized() -> None:
    scheduler = ResourceScheduler()
    first_entered = Event()
    release_first = Event()
    second_entered = Event()

    def first() -> None:
        with scheduler.acquire(ProcessingResource.ffmpeg):
            first_entered.set()
            release_first.wait(timeout=2)

    def second() -> None:
        with scheduler.acquire(ProcessingResource.ffmpeg):
            second_entered.set()

    first_thread = Thread(target=first)
    second_thread = Thread(target=second)
    first_thread.start()
    assert first_entered.wait(timeout=1)
    second_thread.start()
    assert second_entered.wait(timeout=0.05) is False
    release_first.set()
    assert second_entered.wait(timeout=1)
    first_thread.join(timeout=1)
    second_thread.join(timeout=1)


def test_different_stage_resources_do_not_block_each_other() -> None:
    scheduler = ResourceScheduler()
    asr_entered = Event()

    def run_asr() -> None:
        with scheduler.acquire(ProcessingResource.gpu_asr):
            asr_entered.set()

    with scheduler.acquire(ProcessingResource.ffmpeg):
        thread = Thread(target=run_asr)
        thread.start()
        assert asr_entered.wait(timeout=1)
        thread.join(timeout=1)


def test_waiting_for_resource_honors_cancellation() -> None:
    scheduler = ResourceScheduler()
    cancelled = Event()

    with scheduler.acquire(ProcessingResource.cpu_asr):
        with pytest.raises(ResourceWaitCancelled):
            with scheduler.acquire(
                ProcessingResource.cpu_asr,
                is_cancelled=lambda: cancelled.is_set(),
                poll_seconds=0.01,
                on_wait=lambda: cancelled.set(),
            ):
                raise AssertionError("cancelled waiter must not enter")
