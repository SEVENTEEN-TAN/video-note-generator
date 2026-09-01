from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from threading import Lock
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field

from .atomic_io import atomic_write_text


OPERATION_FILENAME = ".operation.json"
_PROCESS_SESSION_ID = uuid4().hex
_OPERATION_LOCKS_GUARD = Lock()
_OPERATION_LOCKS: dict[str, Lock] = {}


class OperationStatus(str, Enum):
    queued = "queued"
    recovering = "recovering"
    running = "running"
    waiting_for_credentials = "waiting_for_credentials"
    completed = "completed"
    failed = "failed"
    cancelled = "cancelled"
    interrupted = "interrupted"


TERMINAL_OPERATION_STATUSES = {
    OperationStatus.waiting_for_credentials,
    OperationStatus.completed,
    OperationStatus.failed,
    OperationStatus.cancelled,
}


class JobOperation(BaseModel):
    schema_version: int = 1
    id: str
    job_id: str
    type: str
    status: OperationStatus
    stage: str = "queued"
    step: str = ""
    progress: int = Field(default=0, ge=0, le=100)
    attempt: int = Field(default=0, ge=0)
    recovery_count: int = Field(default=0, ge=0)
    recovery_owner: str = ""
    required_credentials: list[str] = Field(default_factory=list)
    parameters: dict[str, str | int | float | bool | None] = Field(default_factory=dict)
    error: str = ""
    created_at: str
    updated_at: str


def operation_path(job_dir: Path) -> Path:
    return job_dir / OPERATION_FILENAME


def load_job_operation(job_dir: Path) -> JobOperation | None:
    path = operation_path(job_dir)
    if not path.exists():
        return None
    try:
        return JobOperation.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def create_job_operation(
    *,
    job_dir: Path,
    job_id: str,
    operation_type: str,
    required_credentials: list[str] | None = None,
    parameters: dict[str, str | int | float | bool | None] | None = None,
) -> JobOperation:
    now = _now_iso()
    operation = JobOperation(
        id=uuid4().hex,
        job_id=job_id,
        type=operation_type,
        status=OperationStatus.queued,
        required_credentials=sorted(set(required_credentials or [])),
        parameters=dict(parameters or {}),
        created_at=now,
        updated_at=now,
    )
    with _operation_lock(job_dir):
        _write_operation(job_dir, operation)
    return operation


def update_job_operation(
    job_dir: Path,
    *,
    operation_id: str | None = None,
    status: OperationStatus | None = None,
    stage: str | None = None,
    step: str | None = None,
    progress: int | None = None,
    error: str | None = None,
    increment_attempt: bool = False,
    increment_recovery: bool = False,
    allow_terminal_restart: bool = False,
) -> JobOperation | None:
    with _operation_lock(job_dir):
        current = load_job_operation(job_dir)
        if current is None or (operation_id is not None and current.id != operation_id):
            return current
        if (
            current.status in TERMINAL_OPERATION_STATUSES
            and status not in {None, current.status}
            and not allow_terminal_restart
        ):
            return current

        update: dict[str, Any] = {"updated_at": _now_iso()}
        if status is not None:
            update["status"] = status
        if stage is not None:
            update["stage"] = stage
        if step is not None:
            update["step"] = step
        if progress is not None:
            update["progress"] = max(0, min(100, progress))
        if error is not None:
            update["error"] = error
        if increment_attempt:
            update["attempt"] = current.attempt + 1
        if increment_recovery:
            update["recovery_count"] = current.recovery_count + 1

        updated = current.model_copy(update=update)
        if updated == current:
            return current
        _write_operation(job_dir, updated)
        return updated


def claim_job_operation_for_recovery(job_dir: Path, operation_id: str) -> JobOperation | None:
    with _operation_lock(job_dir):
        current = load_job_operation(job_dir)
        if current is None or current.id != operation_id:
            return None
        recoverable_statuses = {
            OperationStatus.queued,
            OperationStatus.running,
            OperationStatus.interrupted,
        }
        owned_by_another_process = (
            current.status == OperationStatus.recovering
            and current.recovery_owner
            and current.recovery_owner != _PROCESS_SESSION_ID
        )
        if current.status not in recoverable_statuses and not owned_by_another_process:
            return None
        claimed = current.model_copy(
            update={
                "status": OperationStatus.recovering,
                "recovery_count": current.recovery_count + 1,
                "recovery_owner": _PROCESS_SESSION_ID,
                "updated_at": _now_iso(),
                "error": "",
            }
        )
        _write_operation(job_dir, claimed)
        return claimed


def sync_operation_with_job_state(
    job_dir: Path,
    *,
    job_status: str,
    stage: str,
    step: str,
    progress: int,
    error: str = "",
) -> JobOperation | None:
    operation = load_job_operation(job_dir)
    if operation is None:
        return None

    if job_status in {"awaiting_subtitle_confirmation", "awaiting_note_review", "succeeded"}:
        operation_status = OperationStatus.completed
    elif job_status == "cancelled":
        operation_status = OperationStatus.cancelled
    elif job_status == "failed":
        operation_status = OperationStatus.failed
    elif job_status in {"running", "cancelling"}:
        operation_status = OperationStatus.running
    else:
        operation_status = (
            OperationStatus.recovering
            if operation.status == OperationStatus.recovering
            else OperationStatus.queued
        )

    return update_job_operation(
        job_dir,
        operation_id=operation.id,
        status=operation_status,
        stage=stage,
        step=step,
        progress=progress,
        error=error,
    )


def describe_task_operation(task_name: str, kwargs: dict[str, Any]) -> tuple[list[str], dict[str, str | int | float | bool | None]]:
    config = kwargs.get("config")
    transcription_mode = _enum_value(getattr(config, "transcription_mode", ""))
    required_credentials: list[str] = []
    if task_name in {"process_transcription_job", "regenerate_subtitles_job"}:
        if transcription_mode and transcription_mode != "local_faster_whisper":
            required_credentials.append("transcription_service")
    elif task_name in {"continue_job_to_notes", "regenerate_note_job", "_regenerate_chunk_job"}:
        required_credentials.append("note_service")

    parameters: dict[str, str | int | float | bool | None] = {}
    for key in ("chunk_id", "uploaded_subtitle_filename"):
        value = kwargs.get(key)
        if isinstance(value, (str, int, float, bool)) or value is None:
            if value not in (None, ""):
                parameters[key] = value
    if transcription_mode:
        parameters["transcription_mode"] = transcription_mode
    return required_credentials, parameters


def _enum_value(value: Any) -> str:
    return str(getattr(value, "value", value) or "")


def _operation_lock(job_dir: Path) -> Lock:
    key = str(operation_path(job_dir).resolve()).casefold()
    with _OPERATION_LOCKS_GUARD:
        return _OPERATION_LOCKS.setdefault(key, Lock())


def _write_operation(job_dir: Path, operation: JobOperation) -> None:
    atomic_write_text(
        operation_path(job_dir),
        operation.model_dump_json(indent=2),
        encoding="utf-8",
    )


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
