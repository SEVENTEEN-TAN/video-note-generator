from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field

from .atomic_io import atomic_write_text
from .models import (
    FailureContext,
    JobPublicState,
    JobStage,
    JobStatus,
    TranscriptionWorkProgress,
)


JOB_STATE_FILENAME = ".job-state.json"


class JobStateSnapshot(BaseModel):
    schema_version: int = 1
    job_id: str
    status: JobStatus
    stage: JobStage
    step: str
    progress: int = Field(ge=0, le=100)
    work_progress: TranscriptionWorkProgress | None = None
    error: str | None = None
    failure_context: FailureContext | None = None
    step_started_at: str | None = None
    updated_at: str | None = None
    stage_elapsed_seconds: float = Field(default=0, ge=0)
    state_revision: int = Field(default=1, ge=1)


def job_state_path(job_dir: Path) -> Path:
    return job_dir / JOB_STATE_FILENAME


def load_job_state(job_dir: Path) -> JobStateSnapshot | None:
    path = job_state_path(job_dir)
    if not path.exists():
        return None
    try:
        snapshot = JobStateSnapshot.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if snapshot.job_id != job_dir.name:
        return None
    return snapshot


def write_job_state(job_dir: Path, state: JobPublicState) -> JobStateSnapshot:
    snapshot = JobStateSnapshot(
        job_id=state.job_id,
        status=state.status,
        stage=state.stage,
        step=state.step,
        progress=state.progress,
        work_progress=state.work_progress,
        error=state.error,
        failure_context=state.failure_context,
        step_started_at=state.step_started_at,
        updated_at=state.updated_at,
        stage_elapsed_seconds=state.stage_elapsed_seconds,
        state_revision=max(1, state.state_revision),
    )
    atomic_write_text(
        job_state_path(job_dir),
        snapshot.model_dump_json(indent=2),
        encoding="utf-8",
    )
    return snapshot
