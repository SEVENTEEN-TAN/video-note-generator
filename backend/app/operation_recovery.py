from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .job_executor import start_recovered_job
from .job_store import JobStore
from .models import JobInputConfig, JobStage, JobStatus, PerformanceMode, TranscriptionConfig, TranscriptionMode
from .note_versions import find_source_video, load_note_version_index
from .operation_leases import (
    LeaseHeartbeat,
    OperationLeaseLostError,
    OperationLeaseStore,
    bind_current_operation_lease,
)
from .operation_store import (
    JobOperation,
    OperationStatus,
    claim_job_operation_for_recovery,
    load_job_operation,
    sync_operation_with_job_state,
    update_job_operation,
)
from .processor import (
    process_transcription_job,
    process_uploaded_subtitle_job,
    regenerate_subtitles_job,
    resume_note_review_artifacts_job,
)


@dataclass(frozen=True)
class RecoveryDecision:
    job_id: str
    operation_id: str
    action: str
    reason: str = ""


RecoveryStarter = Callable[..., Any]
RECOVERY_CANDIDATE_STATUSES = {
    OperationStatus.queued,
    OperationStatus.recovering,
    OperationStatus.running,
    OperationStatus.interrupted,
}
NOTE_OPERATION_TYPES = {
    "continue_job_to_notes",
    "regenerate_note_job",
    "_regenerate_chunk_job",
}
DETERMINISTIC_REVIEW_STAGES = {
    JobStage.generating_frames.value,
    JobStage.preparing_review.value,
}


def recover_incomplete_operations(
    outputs_root: Path,
    store: JobStore,
    *,
    starter: RecoveryStarter = start_recovered_job,
) -> list[RecoveryDecision]:
    decisions: list[RecoveryDecision] = []
    if not outputs_root.exists():
        return decisions

    store.outputs_root = outputs_root
    for job_dir in sorted(
        path for path in outputs_root.iterdir() if path.is_dir() and not path.name.startswith(".")
    ):
        operation = load_job_operation(job_dir)
        if operation is None or operation.status not in RECOVERY_CANDIDATE_STATUSES:
            continue
        decision = _recover_operation(job_dir, operation, store, starter)
        decisions.append(decision)
    return decisions


def _recover_operation(
    job_dir: Path,
    operation: JobOperation,
    store: JobStore,
    starter: RecoveryStarter,
) -> RecoveryDecision:
    lease_store = OperationLeaseStore(job_dir.parent)
    lease = lease_store.acquire(operation.job_id, operation_id=operation.id)
    if lease is None:
        return RecoveryDecision(operation.job_id, operation.id, "skipped", "already_claimed")
    lease_transferred = False
    try:
        recovery_guard = LeaseHeartbeat(lease_store, lease)
        with bind_current_operation_lease(recovery_guard):
            state = store.get(operation.job_id) or store.load_from_disk(operation.job_id)
            if state is None:
                update_job_operation(
                    job_dir,
                    operation_id=operation.id,
                    status=OperationStatus.failed,
                    error="Job directory could not be loaded during recovery.",
                )
                return RecoveryDecision(operation.job_id, operation.id, "failed", "job_not_loadable")

            if state.status in {
                JobStatus.awaiting_subtitle_confirmation,
                JobStatus.awaiting_note_review,
                JobStatus.cancelled,
            }:
                sync_operation_with_job_state(
                    job_dir,
                    job_status=state.status.value,
                    stage=state.stage.value,
                    step=state.step,
                    progress=state.progress,
                    error=state.error or "",
                )
                return RecoveryDecision(operation.job_id, operation.id, "reconciled", state.status.value)

            metadata = _read_metadata(job_dir)
            task_spec = _recoverable_task_spec(job_dir, operation, metadata, store)
            if task_spec is None:
                return _mark_waiting_for_retry(job_dir, operation, store)

            task, kwargs, progress = task_spec
            claimed = claim_job_operation_for_recovery(job_dir, operation.id)
            if claimed is None:
                return RecoveryDecision(operation.job_id, operation.id, "skipped", "already_claimed")
            store.clear_cancel_request(operation.job_id)
            store.update(
                operation.job_id,
                status=JobStatus.pending,
                stage=JobStage.queued,
                step="程序重启后恢复任务",
                progress=progress,
                error="",
            )
            update_job_operation(
                job_dir,
                operation_id=operation.id,
                status=OperationStatus.recovering,
                stage=operation.stage,
                progress=operation.progress,
            )
            try:
                recovery_guard.assert_current()
                starter(task, operation_id=operation.id, _lease=lease, **kwargs)
                lease_transferred = True
            except OperationLeaseLostError:
                return RecoveryDecision(operation.job_id, operation.id, "skipped", "lease_lost")
            except Exception as exc:
                update_job_operation(
                    job_dir,
                    operation_id=operation.id,
                    status=OperationStatus.interrupted,
                    error=str(exc),
                )
                store.update(
                    operation.job_id,
                    status=JobStatus.failed,
                    stage=JobStage.failed,
                    step="恢复任务启动失败",
                    progress=100,
                    error=str(exc),
                )
                return RecoveryDecision(operation.job_id, operation.id, "failed", "starter_failed")
            return RecoveryDecision(operation.job_id, operation.id, "started", task.__name__)
    except OperationLeaseLostError:
        return RecoveryDecision(operation.job_id, operation.id, "skipped", "lease_lost")
    finally:
        if not lease_transferred:
            lease_store.release(lease)


def _recoverable_task_spec(
    job_dir: Path,
    operation: JobOperation,
    metadata: dict,
    store: JobStore,
) -> tuple[Callable[..., Any], dict[str, Any], int] | None:
    video_path = find_source_video(job_dir)
    if video_path is None or not video_path.exists():
        return None

    if operation.type == "process_uploaded_subtitle_job":
        subtitle_paths = sorted((job_dir / "source_subtitles").glob("input.*"))
        if not subtitle_paths:
            return None
        config = JobInputConfig(
            original_filename=str(metadata.get("original_filename") or video_path.name),
        )
        return (
            process_uploaded_subtitle_job,
            {
                "job_id": operation.job_id,
                "job_dir": job_dir,
                "video_path": video_path,
                "subtitle_path": subtitle_paths[0],
                "uploaded_subtitle_filename": str(
                    operation.parameters.get("uploaded_subtitle_filename")
                    or metadata.get("uploaded_subtitle_filename")
                    or subtitle_paths[0].name
                ),
                "config": config,
                "store": store,
            },
            5,
        )

    if operation.type in {"process_transcription_job", "regenerate_subtitles_job"}:
        if str(metadata.get("transcription_mode") or "") != TranscriptionMode.local_faster_whisper.value:
            return None
        config = _transcription_config_from_metadata(metadata)
        task = process_transcription_job if operation.type == "process_transcription_job" else regenerate_subtitles_job
        return (
            task,
            {
                "job_id": operation.job_id,
                "job_dir": job_dir,
                "video_path": video_path,
                "config": config,
                "store": store,
            },
            20 if operation.type == "regenerate_subtitles_job" else 5,
        )

    if (
        operation.type in NOTE_OPERATION_TYPES
        and operation.stage in DETERMINISTIC_REVIEW_STAGES
        and _has_complete_note_version(job_dir)
    ):
        return (
            resume_note_review_artifacts_job,
            {
                "job_id": operation.job_id,
                "job_dir": job_dir,
                "video_path": video_path,
                "store": store,
            },
            78,
        )
    return None


def _mark_waiting_for_retry(
    job_dir: Path,
    operation: JobOperation,
    store: JobStore,
) -> RecoveryDecision:
    if operation.required_credentials:
        credentials = ", ".join(_credential_label(item) for item in operation.required_credentials)
        message = f"Task was interrupted and is waiting for credentials before retry: {credentials}."
        operation_status = OperationStatus.waiting_for_credentials
        reason = "credentials_required"
    else:
        message = "Task was interrupted before a safe automatic recovery point. Retry the operation."
        operation_status = OperationStatus.interrupted
        reason = "manual_retry_required"

    update_job_operation(
        job_dir,
        operation_id=operation.id,
        status=operation_status,
        stage=JobStage.failed.value,
        step="等待重试",
        progress=100,
        error=message,
    )
    store.update(
        operation.job_id,
        status=JobStatus.failed,
        stage=JobStage.failed,
        step="等待重试",
        progress=100,
        error=message,
    )
    return RecoveryDecision(operation.job_id, operation.id, "waiting_for_retry", reason)


def _transcription_config_from_metadata(metadata: dict) -> TranscriptionConfig:
    return TranscriptionConfig(
        transcription_mode=metadata.get("transcription_mode") or TranscriptionMode.local_faster_whisper.value,
        transcription_api_key="",
        transcription_base_url=str(metadata.get("transcription_base_url") or "https://api.openai.com/v1"),
        transcription_model=str(metadata.get("transcription_model") or "small"),
        local_whisper_device=str(metadata.get("local_whisper_device") or ""),
        local_whisper_compute_type=str(metadata.get("local_whisper_compute_type") or ""),
        performance_mode=metadata.get("performance_mode") or PerformanceMode.balanced.value,
        transcription_language=metadata.get("transcription_language") or "auto",
        original_filename=str(metadata.get("original_filename") or "video"),
    )


def _credential_label(value: str) -> str:
    return {
        "transcription_service": "transcription service credential",
        "note_service": "note service credential",
    }.get(value, value)


def _has_complete_note_version(job_dir: Path) -> bool:
    if not (job_dir / "note.md").is_file():
        return False
    index = load_note_version_index(job_dir)
    if not index.active_version_id:
        return False
    active = next((version for version in index.versions if version.id == index.active_version_id), None)
    if active is None:
        return False
    return (job_dir / active.note_path).is_file()


def _read_metadata(job_dir: Path) -> dict:
    path = job_dir / "metadata.json"
    if not path.exists():
        return {}
    try:
        import json

        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return payload if isinstance(payload, dict) else {}
