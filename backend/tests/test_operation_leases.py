from __future__ import annotations

from multiprocessing import get_context
from pathlib import Path
import sqlite3
from threading import Event

import pytest

from backend.app.atomic_io import atomic_replace_directory, atomic_write_text
from backend.app.job_store import JobStore
from backend.app.operation_leases import (
    LeaseHeartbeat,
    OperationLeaseLostError,
    OperationLeaseStore,
    bind_current_operation_lease,
)


def _hold_lease_in_child(
    outputs_root: str,
    ready,
    release,
    result_queue,
) -> None:
    store = OperationLeaseStore(
        Path(outputs_root),
        lease_ttl_seconds=5,
    )
    lease = store.acquire(
        "multiprocess-job",
        operation_id="child-operation",
        owner_id="child-process",
    )
    result_queue.put(lease is not None)
    ready.set()
    if lease is not None:
        release.wait(timeout=5)
        store.release(lease)


def test_second_store_cannot_acquire_an_active_job_lease(tmp_path) -> None:
    first_store = OperationLeaseStore(tmp_path)
    second_store = OperationLeaseStore(tmp_path)

    first = first_store.acquire(
        "shared-job",
        operation_id="operation-1",
        owner_id="process-a",
    )
    blocked = second_store.acquire(
        "shared-job",
        operation_id="operation-2",
        owner_id="process-b",
    )

    assert first is not None
    assert blocked is None
    assert second_store.load("shared-job") == first


def test_active_lease_blocks_a_real_second_process(tmp_path) -> None:
    context = get_context("spawn")
    ready = context.Event()
    release = context.Event()
    result_queue = context.Queue()
    child = context.Process(
        target=_hold_lease_in_child,
        args=(str(tmp_path), ready, release, result_queue),
    )
    child.start()
    try:
        assert ready.wait(timeout=5)
        assert result_queue.get(timeout=2) is True

        blocked = OperationLeaseStore(tmp_path).acquire(
            "multiprocess-job",
            operation_id="parent-operation",
            owner_id="parent-process",
        )

        assert blocked is None
    finally:
        release.set()
        child.join(timeout=5)
        if child.is_alive():
            child.terminate()
            child.join(timeout=2)
    assert child.exitcode == 0


def test_coordination_database_is_hidden_from_job_history_and_has_no_credential_fields(tmp_path) -> None:
    lease = OperationLeaseStore(tmp_path).acquire(
        "schema-job",
        operation_id="operation-id",
        owner_id="process-owner",
    )
    assert lease is not None

    assert JobStore(tmp_path).list_history() == []
    database_path = tmp_path / ".runtime" / "coordination.sqlite3"
    with sqlite3.connect(database_path) as connection:
        columns = {
            row[1]
            for row in connection.execute("PRAGMA table_info(operation_leases)")
        }
        row = connection.execute(
            "SELECT job_id, operation_id, owner_id, revision FROM operation_leases"
        ).fetchone()

    assert columns == {
        "job_id",
        "operation_id",
        "owner_id",
        "acquired_at",
        "heartbeat_at",
        "lease_expires_at",
        "revision",
    }
    assert row == ("schema-job", "operation-id", "process-owner", 1)
    assert not {
        "api_key",
        "authorization",
        "token",
        "credential",
        "request_body",
    } & columns


def test_expired_lease_can_be_taken_over_with_a_higher_fencing_revision(tmp_path) -> None:
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
    first = first_store.acquire(
        "takeover-job",
        operation_id="operation-1",
        owner_id="process-a",
    )
    assert first is not None

    clock[0] = 111.0
    second = second_store.acquire(
        "takeover-job",
        operation_id="operation-2",
        owner_id="process-b",
    )

    assert second is not None
    assert second.revision == first.revision + 1
    assert second.owner_id == "process-b"
    assert not first_store.is_current(first)
    assert first_store.heartbeat(first) is None
    assert first_store.release(first) is False
    assert second_store.load("takeover-job") == second


def test_release_preserves_fencing_revision_for_the_next_owner(tmp_path) -> None:
    clock = [200.0]
    store = OperationLeaseStore(
        tmp_path,
        lease_ttl_seconds=10,
        clock=lambda: clock[0],
    )
    first = store.acquire(
        "released-job",
        operation_id="operation-1",
        owner_id="process-a",
    )
    assert first is not None
    assert store.release(first) is True

    clock[0] = 201.0
    second = store.acquire(
        "released-job",
        operation_id="operation-2",
        owner_id="process-b",
    )

    assert second is not None
    assert second.revision == first.revision + 1
    assert second.owner_id == "process-b"


def test_heartbeat_extends_lease_and_stops_after_ownership_is_lost(tmp_path) -> None:
    clock = [300.0]
    store = OperationLeaseStore(
        tmp_path,
        lease_ttl_seconds=10,
        clock=lambda: clock[0],
    )
    lease = store.acquire(
        "heartbeat-job",
        operation_id="operation-1",
        owner_id="process-a",
    )
    assert lease is not None

    clock[0] = 305.0
    refreshed = store.heartbeat(lease)
    assert refreshed is not None
    assert refreshed.lease_expires_at == 315.0
    assert refreshed.revision == lease.revision

    clock[0] = 316.0
    replacement = store.acquire(
        "heartbeat-job",
        operation_id="operation-2",
        owner_id="process-b",
    )
    assert replacement is not None
    assert store.heartbeat(refreshed) is None


def test_lease_heartbeat_releases_the_current_lease_on_close(tmp_path) -> None:
    store = OperationLeaseStore(tmp_path, lease_ttl_seconds=2)
    lease = store.acquire(
        "heartbeat-close",
        operation_id="operation-1",
        owner_id="process-a",
    )
    assert lease is not None
    heartbeat = LeaseHeartbeat(store, lease, interval_seconds=0.05)

    assert heartbeat.start() is True
    heartbeat.close()

    current = store.load("heartbeat-close")
    assert current is not None
    assert current.lease_expires_at == 0


def test_heartbeat_reports_loss_after_an_expired_lease_is_replaced(tmp_path) -> None:
    clock = [400.0]
    first_store = OperationLeaseStore(
        tmp_path,
        lease_ttl_seconds=0.1,
        clock=lambda: clock[0],
    )
    second_store = OperationLeaseStore(
        tmp_path,
        lease_ttl_seconds=0.1,
        clock=lambda: clock[0],
    )
    lease = first_store.acquire(
        "lost-heartbeat",
        operation_id="operation-1",
        owner_id="process-a",
    )
    assert lease is not None
    heartbeat = LeaseHeartbeat(first_store, lease, interval_seconds=0.05)
    assert heartbeat.start() is True

    clock[0] = 401.0
    replacement = second_store.acquire(
        "lost-heartbeat",
        operation_id="operation-2",
        owner_id="process-b",
    )
    assert replacement is not None
    assert heartbeat.lost.wait(timeout=1)

    heartbeat.close()
    assert second_store.is_current(replacement)


def test_heartbeat_close_does_not_mask_cleanup_database_errors(tmp_path, monkeypatch) -> None:
    store = OperationLeaseStore(tmp_path)
    lease = store.acquire(
        "cleanup-error",
        operation_id="operation-1",
        owner_id="process-a",
    )
    assert lease is not None
    heartbeat = LeaseHeartbeat(store, lease, interval_seconds=1)
    monkeypatch.setattr(
        store,
        "release",
        lambda _lease: (_ for _ in ()).throw(sqlite3.OperationalError("database unavailable")),
    )

    heartbeat.close()

    assert heartbeat.lost.is_set()


def test_stale_lease_owner_cannot_publish_an_atomic_file_write(tmp_path) -> None:
    clock = [500.0]
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
    first = first_store.acquire(
        "fenced-file-job",
        operation_id="operation-1",
        owner_id="process-a",
    )
    assert first is not None
    heartbeat = LeaseHeartbeat(first_store, first, interval_seconds=5)
    target = tmp_path / "fenced-file-job" / "note.md"

    with bind_current_operation_lease(heartbeat):
        atomic_write_text(target, "first owner")
        clock[0] = 511.0
        replacement = second_store.acquire(
            "fenced-file-job",
            operation_id="operation-2",
            owner_id="process-b",
        )
        assert replacement is not None

        with pytest.raises(OperationLeaseLostError, match="replaced"):
            atomic_write_text(target, "stale owner")

    assert target.read_text(encoding="utf-8") == "first owner"
    assert heartbeat.lost.is_set()
    assert second_store.is_current(replacement)


def test_stale_lease_owner_cannot_replace_a_published_directory(tmp_path) -> None:
    clock = [600.0]
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
    first = first_store.acquire(
        "fenced-directory-job",
        operation_id="operation-1",
        owner_id="process-a",
    )
    assert first is not None
    heartbeat = LeaseHeartbeat(first_store, first, interval_seconds=5)
    source = tmp_path / "frames.new"
    target = tmp_path / "frames"
    source.mkdir()
    target.mkdir()
    (source / "frame.jpg").write_bytes(b"new")
    (target / "frame.jpg").write_bytes(b"old")

    clock[0] = 611.0
    replacement = second_store.acquire(
        "fenced-directory-job",
        operation_id="operation-2",
        owner_id="process-b",
    )
    assert replacement is not None

    with bind_current_operation_lease(heartbeat):
        with pytest.raises(OperationLeaseLostError, match="replaced"):
            atomic_replace_directory(source, target)

    assert (target / "frame.jpg").read_bytes() == b"old"
    assert (source / "frame.jpg").read_bytes() == b"new"
    assert second_store.is_current(replacement)


def test_job_cancellation_poll_detects_a_replaced_lease_without_waiting_for_heartbeat(tmp_path) -> None:
    clock = [700.0]
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
    first = first_store.acquire(
        "poll-fenced-job",
        operation_id="operation-1",
        owner_id="process-a",
    )
    assert first is not None
    heartbeat = LeaseHeartbeat(first_store, first, interval_seconds=5)

    clock[0] = 711.0
    replacement = second_store.acquire(
        "poll-fenced-job",
        operation_id="operation-2",
        owner_id="process-b",
    )
    assert replacement is not None

    with bind_current_operation_lease(heartbeat):
        assert JobStore(tmp_path).is_cancel_requested("poll-fenced-job") is True

    assert heartbeat.lost.is_set()
