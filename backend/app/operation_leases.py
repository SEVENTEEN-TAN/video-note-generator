from __future__ import annotations

import os
import sqlite3
import time
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from threading import Event, Lock, Thread
from typing import Callable, Iterator
from uuid import uuid4


LEASE_DATABASE_RELATIVE_PATH = Path(".runtime") / "coordination.sqlite3"
DEFAULT_LEASE_TTL_SECONDS = 30.0
DEFAULT_HEARTBEAT_INTERVAL_SECONDS = 5.0
_PROCESS_OWNER_PREFIX = f"{os.getpid()}-{uuid4().hex}"
_CURRENT_LEASE_HEARTBEAT: ContextVar[LeaseHeartbeat | None] = ContextVar(
    "video_note_current_lease_heartbeat",
    default=None,
)


class OperationLeaseLostError(RuntimeError):
    """Raised before a stale lease owner can publish another filesystem write."""


@dataclass(frozen=True)
class JobOperationLease:
    job_id: str
    operation_id: str
    owner_id: str
    lease_expires_at: float
    heartbeat_at: float
    revision: int


class OperationLeaseStore:
    """SQLite-backed, cross-process lease registry for per-job mutations."""

    def __init__(
        self,
        outputs_root: Path,
        *,
        lease_ttl_seconds: float = DEFAULT_LEASE_TTL_SECONDS,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.outputs_root = outputs_root
        self.database_path = outputs_root / LEASE_DATABASE_RELATIVE_PATH
        self.lease_ttl_seconds = max(0.1, lease_ttl_seconds)
        self._clock = clock
        self._schema_lock = Lock()
        self._schema_ready = False

    def acquire(
        self,
        job_id: str,
        *,
        operation_id: str = "",
        owner_id: str | None = None,
    ) -> JobOperationLease | None:
        owner = owner_id or f"{_PROCESS_OWNER_PREFIX}-{uuid4().hex}"
        now = self._clock()
        expires_at = now + self.lease_ttl_seconds
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """
                SELECT job_id, operation_id, owner_id, lease_expires_at, heartbeat_at, revision
                FROM operation_leases
                WHERE job_id = ?
                """,
                (job_id,),
            ).fetchone()
            if row is None:
                revision = 1
                connection.execute(
                    """
                    INSERT INTO operation_leases (
                        job_id,
                        operation_id,
                        owner_id,
                        acquired_at,
                        heartbeat_at,
                        lease_expires_at,
                        revision
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        job_id,
                        operation_id,
                        owner,
                        _now_iso(now),
                        now,
                        expires_at,
                        revision,
                    ),
                )
            elif row["owner_id"] == owner and float(row["lease_expires_at"]) > now:
                revision = int(row["revision"])
                connection.execute(
                    """
                    UPDATE operation_leases
                    SET operation_id = ?, heartbeat_at = ?, lease_expires_at = ?
                    WHERE job_id = ? AND owner_id = ? AND revision = ?
                    """,
                    (operation_id, now, expires_at, job_id, owner, revision),
                )
            elif float(row["lease_expires_at"]) <= now:
                revision = int(row["revision"]) + 1
                connection.execute(
                    """
                    UPDATE operation_leases
                    SET operation_id = ?,
                        owner_id = ?,
                        acquired_at = ?,
                        heartbeat_at = ?,
                        lease_expires_at = ?,
                        revision = ?
                    WHERE job_id = ? AND revision = ?
                    """,
                    (
                        operation_id,
                        owner,
                        _now_iso(now),
                        now,
                        expires_at,
                        revision,
                        job_id,
                        int(row["revision"]),
                    ),
                )
            else:
                connection.rollback()
                return None
            connection.commit()
        return JobOperationLease(
            job_id=job_id,
            operation_id=operation_id,
            owner_id=owner,
            lease_expires_at=expires_at,
            heartbeat_at=now,
            revision=revision,
        )

    def heartbeat(self, lease: JobOperationLease) -> JobOperationLease | None:
        now = self._clock()
        expires_at = now + self.lease_ttl_seconds
        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE operation_leases
                SET heartbeat_at = ?, lease_expires_at = ?
                WHERE job_id = ?
                  AND operation_id = ?
                  AND owner_id = ?
                  AND revision = ?
                  AND lease_expires_at > ?
                """,
                (
                    now,
                    expires_at,
                    lease.job_id,
                    lease.operation_id,
                    lease.owner_id,
                    lease.revision,
                    now,
                ),
            )
            if cursor.rowcount != 1:
                return None
        return JobOperationLease(
            job_id=lease.job_id,
            operation_id=lease.operation_id,
            owner_id=lease.owner_id,
            lease_expires_at=expires_at,
            heartbeat_at=now,
            revision=lease.revision,
        )

    def release(self, lease: JobOperationLease) -> bool:
        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE operation_leases
                SET heartbeat_at = ?, lease_expires_at = 0
                WHERE job_id = ?
                  AND operation_id = ?
                  AND owner_id = ?
                  AND revision = ?
                """,
                (
                    self._clock(),
                    lease.job_id,
                    lease.operation_id,
                    lease.owner_id,
                    lease.revision,
                ),
            )
            return cursor.rowcount == 1

    def load(self, job_id: str) -> JobOperationLease | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT job_id, operation_id, owner_id, lease_expires_at, heartbeat_at, revision
                FROM operation_leases
                WHERE job_id = ?
                """,
                (job_id,),
            ).fetchone()
        return _lease_from_row(row) if row is not None else None

    def is_current(self, lease: JobOperationLease) -> bool:
        current = self.load(lease.job_id)
        if current is None:
            return False
        return (
            current.operation_id == lease.operation_id
            and current.owner_id == lease.owner_id
            and current.revision == lease.revision
            and current.lease_expires_at > self._clock()
        )

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        self._ensure_schema()
        connection = sqlite3.connect(
            self.database_path,
            timeout=5.0,
            isolation_level=None,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout = 5000")
        try:
            yield connection
        finally:
            connection.close()

    def _ensure_schema(self) -> None:
        if self._schema_ready:
            return
        with self._schema_lock:
            if self._schema_ready:
                return
            self.database_path.parent.mkdir(parents=True, exist_ok=True)
            connection = sqlite3.connect(self.database_path, timeout=5.0)
            try:
                connection.execute("PRAGMA journal_mode = WAL")
                connection.execute("PRAGMA busy_timeout = 5000")
                connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS operation_leases (
                        job_id TEXT PRIMARY KEY,
                        operation_id TEXT NOT NULL,
                        owner_id TEXT NOT NULL,
                        acquired_at TEXT NOT NULL,
                        heartbeat_at REAL NOT NULL,
                        lease_expires_at REAL NOT NULL,
                        revision INTEGER NOT NULL CHECK (revision >= 1)
                    )
                    """
                )
                connection.execute(
                    """
                    CREATE INDEX IF NOT EXISTS operation_leases_expiry_idx
                    ON operation_leases (lease_expires_at)
                    """
                )
                connection.commit()
            finally:
                connection.close()
            self._schema_ready = True


class LeaseHeartbeat:
    """Keeps a lease alive and records ownership loss without blocking shutdown."""

    def __init__(
        self,
        store: OperationLeaseStore,
        lease: JobOperationLease,
        *,
        interval_seconds: float = DEFAULT_HEARTBEAT_INTERVAL_SECONDS,
    ) -> None:
        self.store = store
        self.lease = lease
        self.interval_seconds = max(
            0.05,
            min(interval_seconds, store.lease_ttl_seconds / 2),
        )
        self.lost = Event()
        self._stop = Event()
        self._thread: Thread | None = None
        self._verification_lock = Lock()
        self._last_verified_monotonic = 0.0

    def start(self) -> bool:
        try:
            refreshed = self.store.heartbeat(self.lease)
        except (OSError, sqlite3.Error):
            refreshed = None
        if refreshed is None:
            self.lost.set()
            return False
        self.lease = refreshed
        self._last_verified_monotonic = time.monotonic()
        self._thread = Thread(
            target=self._run,
            name=f"video-note-lease-{self.lease.job_id}",
            daemon=True,
        )
        self._thread.start()
        return True

    def close(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=max(1.0, self.interval_seconds * 2))
        try:
            self.store.release(self.lease)
        except (OSError, sqlite3.Error):
            self.lost.set()

    def assert_current(self) -> None:
        if self.lost.is_set():
            raise OperationLeaseLostError(
                f"Job operation lease is no longer current: {self.lease.job_id}"
            )
        try:
            current = self.store.is_current(self.lease)
        except (OSError, sqlite3.Error) as exc:
            self.lost.set()
            raise OperationLeaseLostError(
                f"Job operation lease could not be verified: {self.lease.job_id}"
            ) from exc
        if not current:
            self.lost.set()
            raise OperationLeaseLostError(
                f"Job operation lease was replaced: {self.lease.job_id}"
            )
        self._last_verified_monotonic = time.monotonic()

    def is_lost_or_stale(self, *, verify_interval_seconds: float = 0.75) -> bool:
        if self.lost.is_set():
            return True
        now = time.monotonic()
        if now - self._last_verified_monotonic < max(0.05, verify_interval_seconds):
            return False
        with self._verification_lock:
            now = time.monotonic()
            if now - self._last_verified_monotonic < max(0.05, verify_interval_seconds):
                return self.lost.is_set()
            try:
                current = self.store.is_current(self.lease)
            except (OSError, sqlite3.Error):
                current = False
            self._last_verified_monotonic = now
            if not current:
                self.lost.set()
            return not current

    def _run(self) -> None:
        while not self._stop.wait(self.interval_seconds):
            try:
                refreshed = self.store.heartbeat(self.lease)
            except (OSError, sqlite3.Error):
                refreshed = None
            if refreshed is None:
                self.lost.set()
                return
            self.lease = refreshed
            self._last_verified_monotonic = time.monotonic()


@contextmanager
def bind_current_operation_lease(
    heartbeat: LeaseHeartbeat | None,
) -> Iterator[None]:
    token = _CURRENT_LEASE_HEARTBEAT.set(heartbeat)
    try:
        yield
    finally:
        _CURRENT_LEASE_HEARTBEAT.reset(token)


def assert_current_operation_lease() -> None:
    heartbeat = _CURRENT_LEASE_HEARTBEAT.get()
    if heartbeat is not None:
        heartbeat.assert_current()


def current_operation_lease_lost() -> bool:
    heartbeat = _CURRENT_LEASE_HEARTBEAT.get()
    return heartbeat is not None and heartbeat.is_lost_or_stale()


def _lease_from_row(row: sqlite3.Row) -> JobOperationLease:
    return JobOperationLease(
        job_id=str(row["job_id"]),
        operation_id=str(row["operation_id"]),
        owner_id=str(row["owner_id"]),
        lease_expires_at=float(row["lease_expires_at"]),
        heartbeat_at=float(row["heartbeat_at"]),
        revision=int(row["revision"]),
    )


def _now_iso(timestamp: float) -> str:
    return datetime.fromtimestamp(timestamp, timezone.utc).isoformat()
