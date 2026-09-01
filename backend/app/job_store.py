from __future__ import annotations

import hashlib
import json
import re
import time
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock

from .atomic_io import atomic_write_json, atomic_write_text
from .filenames import ZIP_DIRTY_MARKER, normalize_uploaded_filename
from .job_migrations import migrate_job_directory
from .job_state import JobStateSnapshot, load_job_state, write_job_state
from .models import (
    Artifact,
    FailureContext,
    JobPublicState,
    JobStage,
    JobStatus,
    JobSummary,
    TranscriptPayload,
    TranscriptionWorkProgress,
)
from .note_versions import ensure_root_note_has_version, load_note_version_index, resolve_job_relative_path
from .operation_leases import assert_current_operation_lease, current_operation_lease_lost
from .operation_store import OperationStatus, load_job_operation, sync_operation_with_job_state


STEP_STAGE_HINTS: tuple[tuple[tuple[str, ...], JobStage], ...] = (
    (("等待", "排队"), JobStage.queued),
    (("分析视频", "视频探测"), JobStage.analyzing_video),
    (("音频", "提取"), JobStage.extracting_audio),
    (("字幕", "转写"), JobStage.transcribing),
    (("确认字幕",), JobStage.awaiting_subtitle_review),
    (("关键帧", "配图"), JobStage.generating_frames),
    (("复核资料", "质量报告"), JobStage.preparing_review),
    (("复核笔记", "人工复核"), JobStage.awaiting_note_review),
    (("定稿", "打包", "ZIP"), JobStage.finalizing),
    (("完成", "历史记录载入"), JobStage.completed),
    (("失败", "中断"), JobStage.failed),
)

CANCELLED_MARKER = ".cancelled"
ARTIFACT_SIGNATURE_NAMES = (
    "audio.mp3",
    "subtitles.srt",
    "subtitles.vtt",
    "subtitles.md",
    "transcript.json",
    "note.md",
    "metadata.json",
    "debug.log",
    "download.zip",
    "frames",
    "debug",
    "review",
    "note_versions/versions.json",
    "review/quality_report.json",
    "review/quality_report.md",
    "review/frame_candidates.json",
    "subtitles.pending",
    ".note-review.pending",
    ZIP_DIRTY_MARKER,
)
RESOURCE_REVISION_NAMES = (
    "subtitles.md",
    "transcript.json",
    "note.md",
    "note_versions/versions.json",
    "note_chunks/index.json",
    "review/quality_report.json",
    "review/frame_candidates.json",
    "review/review_draft.json",
    "frames",
    "subtitles.pending",
    ".note-review.pending",
    ZIP_DIRTY_MARKER,
)
RESOURCE_REVISION_GLOBS = (
    "note_versions/*/review/review_draft.json",
)
_STATE_FIELD_UNSET = object()
DEFAULT_STATE_PERSIST_INTERVAL_SECONDS = 0.75


def infer_job_stage(status: JobStatus, step: str) -> JobStage:
    if status == JobStatus.cancelling:
        return JobStage.cancelling
    if status == JobStatus.awaiting_subtitle_confirmation:
        return JobStage.awaiting_subtitle_review
    if status == JobStatus.awaiting_note_review:
        return JobStage.awaiting_note_review
    if status == JobStatus.succeeded:
        return JobStage.completed
    if status == JobStatus.failed:
        return JobStage.failed
    if status == JobStatus.cancelled:
        return JobStage.cancelled
    normalized = step.strip()
    for hints, stage in STEP_STAGE_HINTS:
        if any(hint in normalized for hint in hints):
            return stage
    if status == JobStatus.running:
        return JobStage.generating_note
    return JobStage.queued


TERMINAL_DEBUG_STAGES = {
    "process_transcription_job",
    "continue_job_to_notes",
    "regenerate_subtitles_job",
    "regenerate_note_job",
    "regenerate_note_chunk",
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_cancel_marker(job_dir: Path) -> dict:
    marker = job_dir / CANCELLED_MARKER
    if not marker.exists():
        return {}
    try:
        raw = marker.read_text(encoding="utf-8").strip()
    except OSError:
        return {}
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        # Older builds persisted the cancellation timestamp as plain text.
        return {"requested_at": raw} if raw else {}
    return payload if isinstance(payload, dict) else {}


def _write_cancel_marker(job_dir: Path, payload: dict) -> None:
    marker = job_dir / CANCELLED_MARKER
    atomic_write_json(marker, payload)


def _cancelled_progress(payload: dict) -> int:
    try:
        progress = int(payload.get("progress", 0))
    except (TypeError, ValueError):
        return 0
    return max(0, min(100, progress))


def _work_progress_from_payload(payload: object) -> TranscriptionWorkProgress | None:
    try:
        return TranscriptionWorkProgress.model_validate(payload)
    except (TypeError, ValueError):
        return None


def _artifact_signature(job_dir: Path) -> tuple:
    signature = []
    for name in ARTIFACT_SIGNATURE_NAMES:
        path = job_dir / name
        try:
            stat = path.stat()
            signature.append((name, stat.st_mtime_ns, stat.st_size, path.is_dir()))
        except OSError:
            signature.append((name, None, None, None))
    return tuple(signature)


def _artifact_revision(job_dir: Path) -> str:
    digest = hashlib.sha256()
    for name in RESOURCE_REVISION_NAMES:
        path = job_dir / name
        try:
            stat = path.stat()
            item = (name, stat.st_mtime_ns, stat.st_size, path.is_dir())
        except OSError:
            item = (name, None, None, None)
        digest.update(repr(item).encode("utf-8"))
        digest.update(b"\0")
    for pattern in RESOURCE_REVISION_GLOBS:
        for path in sorted(job_dir.glob(pattern)):
            try:
                stat = path.stat()
                relative_path = path.relative_to(job_dir).as_posix()
                item = (relative_path, stat.st_mtime_ns, stat.st_size, path.is_dir())
            except OSError:
                continue
            digest.update(repr(item).encode("utf-8"))
            digest.update(b"\0")
    return digest.hexdigest()[:16]


def _snapshot_status(
    job_dir: Path,
    snapshot: JobStateSnapshot,
    operation,
    legacy_status: JobStatus,
    *,
    repair_markers: bool = False,
) -> JobStatus:
    if (job_dir / CANCELLED_MARKER).exists():
        return JobStatus.cancelled
    if (job_dir / ".note-review.pending").exists():
        return JobStatus.awaiting_note_review
    if (job_dir / "subtitles.pending").exists():
        return JobStatus.awaiting_subtitle_confirmation
    if snapshot.status == JobStatus.awaiting_subtitle_confirmation:
        return legacy_status
    if snapshot.status == JobStatus.awaiting_note_review:
        if _finalization_completed(job_dir):
            return JobStatus.succeeded
        if repair_markers:
            atomic_write_text(job_dir / ".note-review.pending", "1", encoding="utf-8")
        return JobStatus.awaiting_note_review
    if (
        snapshot.status in {JobStatus.pending, JobStatus.running, JobStatus.cancelling}
        and operation is not None
        and operation.status
        in {
            OperationStatus.waiting_for_credentials,
            OperationStatus.failed,
            OperationStatus.interrupted,
        }
    ):
        return JobStatus.failed
    return snapshot.status


def _finalization_completed(job_dir: Path) -> bool:
    path = job_dir / "review" / "finalization.json"
    if not path.exists() or not (job_dir / "download.zip").is_file():
        return False
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return isinstance(payload, dict) and payload.get("status") == "completed"


def _recovered_step_and_progress(
    status: JobStatus,
    *,
    cancel_marker: dict,
    operation,
    interrupted_event: dict | None,
    failure_error: str | None,
) -> tuple[str, int]:
    if status == JobStatus.succeeded:
        return "已从历史记录载入", 100
    if status == JobStatus.cancelled:
        return "已取消", _cancelled_progress(cancel_marker)
    if status == JobStatus.awaiting_subtitle_confirmation:
        return "等待确认字幕", 40
    if status == JobStatus.awaiting_note_review:
        return "等待复核笔记", 92
    if operation is not None and operation.status in {
        OperationStatus.waiting_for_credentials,
        OperationStatus.interrupted,
    }:
        return "等待重试", max(0, min(100, operation.progress))
    if interrupted_event:
        return "最近一次处理中断", 100
    if failure_error:
        return "最近一次处理失败", 100
    return "历史任务不完整", 100


def _infer_resumable_work_progress(
    job_dir: Path,
    metadata: dict,
    status: JobStatus,
) -> TranscriptionWorkProgress | None:
    if status not in {JobStatus.cancelled, JobStatus.failed}:
        return None
    if metadata.get("transcription_mode") != "local_faster_whisper":
        return None
    source_dir = job_dir / "source_video"
    if not source_dir.exists() or not any(path.is_file() for path in source_dir.iterdir()):
        return None

    manifest_path = job_dir / "work" / "asr" / "transcription_checkpoints" / "manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        chunks = manifest.get("chunks") if isinstance(manifest, dict) else []
        chunks = chunks if isinstance(chunks, list) else []
    except (OSError, TypeError, ValueError):
        chunks = []

    completed_indexes: set[int] = set()
    completed_seconds = 0.0
    results_dir = manifest_path.parent / "results"
    for chunk in chunks:
        if not isinstance(chunk, dict) or not isinstance(chunk.get("index"), int):
            continue
        index = chunk["index"]
        result_path = results_dir / f"chunk_{index:04d}.json"
        try:
            TranscriptPayload.model_validate_json(result_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, ValueError):
            continue
        completed_indexes.add(index)
        try:
            completed_seconds = max(completed_seconds, float(chunk.get("end") or 0.0))
        except (TypeError, ValueError):
            pass

    try:
        metadata_duration = float(metadata.get("duration_seconds") or 0.0)
    except (TypeError, ValueError):
        metadata_duration = 0.0
    chunk_duration = 0.0
    for chunk in chunks:
        if not isinstance(chunk, dict):
            continue
        try:
            chunk_duration = max(chunk_duration, float(chunk.get("end") or 0.0))
        except (TypeError, ValueError):
            continue
    return TranscriptionWorkProgress(
        completed_seconds=completed_seconds,
        total_seconds=max(metadata_duration, chunk_duration),
        completed_chunks=len(completed_indexes),
        total_chunks=len(chunks),
        current_chunk=None,
        realtime_factor=None,
        eta_seconds=None,
        resumable=True,
        cache_hits=len(completed_indexes),
        device=str(metadata.get("local_whisper_device") or "auto"),
        compute_type=str(metadata.get("local_whisper_compute_type") or "default"),
    )


class JobStore:
    def __init__(
        self,
        outputs_root: Path,
        *,
        state_persist_interval_seconds: float = DEFAULT_STATE_PERSIST_INTERVAL_SECONDS,
        monotonic_clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.outputs_root = outputs_root
        self._state_persist_interval_seconds = max(0.0, state_persist_interval_seconds)
        self._monotonic_clock = monotonic_clock
        self._lock = Lock()
        self._jobs: dict[str, JobPublicState] = {}
        self._cancel_requested: set[str] = set()
        self._artifact_cache: dict[str, tuple[tuple, list[Artifact], str | None]] = {}
        self._last_state_persisted_at: dict[str, float] = {}

    def create(self, job_id: str) -> JobPublicState:
        now = _now_iso()
        artifact_revision = _artifact_revision(self.outputs_root / job_id)
        state = JobPublicState(
            job_id=job_id,
            status=JobStatus.pending,
            step="等待处理",
            progress=0,
            artifacts=[],
            artifact_revision=artifact_revision,
            state_revision=1,
            step_started_at=now,
            updated_at=now,
            stage_elapsed_seconds=0,
        )
        self._persist_state(job_id, state)
        with self._lock:
            self._jobs[job_id] = state
        return _copy_public_state(state)

    def request_cancel(self, job_id: str) -> JobPublicState | None:
        with self._lock:
            state = self._jobs.get(job_id)
            if state is None:
                return None
            if state.status in {JobStatus.cancelling, JobStatus.cancelled}:
                return _copy_public_state(state)
            if state.status not in {JobStatus.pending, JobStatus.running}:
                return _copy_public_state(state)
            now = _now_iso()
            previous_step = state.step
            self._cancel_requested.add(job_id)
            state.status = JobStatus.cancelling
            state.stage = JobStage.cancelling
            state.step = "正在取消"
            state.error = None
            state.updated_at = now
            state.state_revision += 1
            try:
                _write_cancel_marker(
                    self.outputs_root / job_id,
                    {
                        "requested_at": now,
                        "progress": state.progress,
                        "step": previous_step,
                        "work_progress": (
                            state.work_progress.model_dump(mode="json") if state.work_progress is not None else None
                        ),
                    },
                )
            except OSError:
                pass
            self._persist_state(job_id, state)
            self._sync_operation_state(job_id, state)
            return _copy_public_state(state)

    def mark_cancelled(self, job_id: str) -> JobPublicState | None:
        snapshot = load_job_state(self.outputs_root / job_id)
        with self._lock:
            state = self._jobs.get(job_id)
            if state is None:
                return None
            _merge_newer_snapshot(state, snapshot)
            now = _now_iso()
            marker_payload = _read_cancel_marker(self.outputs_root / job_id)
            marker_payload["cancelled_at"] = now
            marker_payload.setdefault("progress", state.progress)
            marker_payload.setdefault("step", state.step)
            try:
                _write_cancel_marker(self.outputs_root / job_id, marker_payload)
            except OSError:
                pass
            state.status = JobStatus.cancelled
            state.stage = JobStage.cancelled
            state.step = "已取消"
            state.error = None
            if state.work_progress is not None:
                state.work_progress = state.work_progress.model_copy(
                    update={"resumable": True},
                    deep=True,
                )
                marker_payload["work_progress"] = state.work_progress.model_dump(mode="json")
                try:
                    _write_cancel_marker(self.outputs_root / job_id, marker_payload)
                except OSError:
                    pass
            state.updated_at = now
            state.state_revision += 1
            self._persist_state(job_id, state)
            self._sync_operation_state(job_id, state)
            return _copy_public_state(state)

    def is_cancel_requested(self, job_id: str) -> bool:
        if current_operation_lease_lost():
            return True
        with self._lock:
            if job_id in self._cancel_requested:
                return True
        return (self.outputs_root / job_id / CANCELLED_MARKER).exists()

    def clear_cancel_request(self, job_id: str) -> None:
        with self._lock:
            self._cancel_requested.discard(job_id)
            try:
                assert_current_operation_lease()
                (self.outputs_root / job_id / CANCELLED_MARKER).unlink(missing_ok=True)
            except OSError:
                pass

    def get(self, job_id: str) -> JobPublicState | None:
        snapshot = load_job_state(self.outputs_root / job_id)
        with self._lock:
            state = self._jobs.get(job_id)
            if state is not None:
                _merge_newer_snapshot(state, snapshot)
            return _copy_public_state(state) if state is not None else None

    def update(
        self,
        job_id: str,
        *,
        status: JobStatus | None = None,
        step: str | None = None,
        progress: int | None = None,
        error: str | None = None,
        stage: JobStage | None = None,
        work_progress: TranscriptionWorkProgress | None | object = _STATE_FIELD_UNSET,
        failure_context: FailureContext | None | object = _STATE_FIELD_UNSET,
        throttle_persistence: bool = False,
    ) -> None:
        with self._lock:
            state = self._jobs[job_id]
            if (
                job_id in self._cancel_requested
                or (self.outputs_root / job_id / CANCELLED_MARKER).exists()
            ):
                return
            previous_status = state.status
            previous_stage = state.stage
            previous_work_progress = state.work_progress
            now = _now_iso()
            old_step = state.step
            new_step = step if step is not None else old_step
            if new_step != old_step:
                state.step_started_at = now
            state.updated_at = now
            if state.step_started_at:
                started = datetime.fromisoformat(state.step_started_at)
                current = datetime.fromisoformat(now)
                state.stage_elapsed_seconds = max(0, (current - started).total_seconds())
            if status is not None:
                state.status = status
                if status != JobStatus.failed and failure_context is _STATE_FIELD_UNSET:
                    state.failure_context = None
            if step is not None:
                state.step = step
            state.stage = stage if stage is not None else infer_job_stage(state.status, state.step)
            if progress is not None:
                state.progress = max(0, min(100, progress))
            if work_progress is not _STATE_FIELD_UNSET:
                state.work_progress = (
                    work_progress.model_copy(deep=True)
                    if isinstance(work_progress, TranscriptionWorkProgress)
                    else None
                )
            if failure_context is not _STATE_FIELD_UNSET:
                state.failure_context = (
                    failure_context.model_copy(deep=True)
                    if isinstance(failure_context, FailureContext)
                    else None
                )
            if error is not None:
                state.error = error
            should_persist = (
                not throttle_persistence
                or state.status != previous_status
                or state.stage != previous_stage
                or _work_progress_crossed_durable_boundary(
                    previous_work_progress,
                    state.work_progress,
                    supplied=work_progress is not _STATE_FIELD_UNSET,
                )
                or self._state_persist_interval_elapsed(job_id)
            )
            if should_persist:
                state.state_revision += 1
                self._persist_state(job_id, state)
            if state.status != previous_status or state.stage != previous_stage:
                self._sync_operation_state(job_id, state)

    def _persist_state(self, job_id: str, state: JobPublicState) -> None:
        write_job_state(self.outputs_root / job_id, state)
        self._last_state_persisted_at[job_id] = self._monotonic_clock()

    def _state_persist_interval_elapsed(self, job_id: str) -> bool:
        last_persisted_at = self._last_state_persisted_at.get(job_id)
        if last_persisted_at is None:
            return True
        return (
            self._monotonic_clock() - last_persisted_at
            >= self._state_persist_interval_seconds
        )

    def _sync_operation_state(self, job_id: str, state: JobPublicState) -> None:
        try:
            sync_operation_with_job_state(
                self.outputs_root / job_id,
                job_status=state.status.value,
                stage=state.stage.value,
                step=state.step,
                progress=state.progress,
                error=state.error or "",
            )
        except (OSError, ValueError):
            # Operation journaling must not turn a completed processing stage
            # into a user-visible job failure.
            pass

    def refresh_artifacts(self, job_id: str) -> list[Artifact]:
        job_dir = self.outputs_root / job_id
        signature = _artifact_signature(job_dir)
        artifact_revision = _artifact_revision(job_dir)
        with self._lock:
            cached = self._artifact_cache.get(job_id)
            if cached is not None and cached[0] == signature:
                artifacts = list(cached[1])
                state = self._jobs.get(job_id)
                if state:
                    state.artifacts = artifacts
                    state.artifact_revision = artifact_revision
                    state.download_filename = cached[2]
                    self._persist_failure_context_if_missing(job_id, job_dir, state)
                return artifacts
        artifacts: list[Artifact] = []
        candidates = [
            ("audio.mp3", "原视频音频 MP3", "audio"),
            ("subtitles.srt", "字幕 SRT", "subtitle"),
            ("subtitles.vtt", "字幕 VTT", "subtitle"),
            ("subtitles.md", "字幕 Markdown", "markdown"),
            ("transcript.json", "转写 JSON", "json"),
            ("note.md", "视频笔记 Markdown", "markdown"),
            ("metadata.json", "任务元数据", "json"),
            ("debug.log", "调试日志", "log"),
            ("download.zip", "完整结果 ZIP", "zip"),
        ]
        for path, label, kind in candidates:
            if (job_dir / path).exists():
                artifacts.append(
                    Artifact(label=label, path=path, kind=kind, asset_url=f"/api/jobs/{job_id}/assets/{path}")
                )
        frames_dir = job_dir / "frames"
        if frames_dir.exists():
            for frame_path in sorted(frames_dir.glob("*.jpg")):
                rel = frame_path.relative_to(job_dir).as_posix()
                artifacts.append(
                    Artifact(label=frame_path.stem, path=rel, kind="image", asset_url=f"/api/jobs/{job_id}/assets/{rel}")
                )
        debug_dir = job_dir / "debug"
        if debug_dir.exists():
            for debug_path in sorted(path for path in debug_dir.rglob("*") if path.is_file()):
                rel = debug_path.relative_to(job_dir).as_posix()
                artifacts.append(
                    Artifact(label=debug_path.name, path=rel, kind="log", asset_url=f"/api/jobs/{job_id}/assets/{rel}")
                )
        review_dir = job_dir / "review"
        if review_dir.exists():
            review_candidates = [
                ("quality_report.json", "质量报告 JSON", "json"),
                ("quality_report.md", "质量报告 Markdown", "markdown"),
                ("frame_candidates.json", "配图候选 JSON", "json"),
            ]
            for filename, label, kind in review_candidates:
                review_path = review_dir / filename
                if review_path.exists():
                    rel = review_path.relative_to(job_dir).as_posix()
                    artifacts.append(
                        Artifact(label=label, path=rel, kind=kind, asset_url=f"/api/jobs/{job_id}/assets/{rel}")
                    )
        with self._lock:
            download_filename = _zip_download_filename(job_dir) if (job_dir / "download.zip").exists() else None
            self._artifact_cache[job_id] = (signature, list(artifacts), download_filename)
            state = self._jobs.get(job_id)
            if state:
                state.artifacts = artifacts
                state.artifact_revision = artifact_revision
                state.download_filename = download_filename
                self._persist_failure_context_if_missing(job_id, job_dir, state)
        return artifacts

    def _persist_failure_context_if_missing(
        self,
        job_id: str,
        job_dir: Path,
        state: JobPublicState,
    ) -> None:
        if state.status != JobStatus.failed or state.failure_context is not None:
            return
        failure_context = _latest_disk_failure_context(job_dir)
        if failure_context is None:
            return
        state.failure_context = failure_context
        state.state_revision += 1
        self._persist_state(job_id, state)

    def load_from_disk(self, job_id: str) -> JobPublicState | None:
        job_dir = self.outputs_root / job_id
        if not job_dir.exists() or not job_dir.is_dir():
            return None

        metadata = migrate_job_directory(job_dir)
        artifacts = self.refresh_artifacts(job_id)
        if (job_dir / "note.md").exists():
            ensure_root_note_has_version(job_dir)
            artifacts = self.refresh_artifacts(job_id)
        version_index = load_note_version_index(job_dir)
        cancel_marker = _read_cancel_marker(job_dir)
        fallback_timestamp = str(
            cancel_marker.get("cancelled_at")
            or cancel_marker.get("requested_at")
            or _job_history_activity_timestamp(job_dir)
            or metadata.get("created_at")
            or _mtime_iso(job_dir)
        )
        snapshot = load_job_state(job_dir)
        legacy_status = _infer_disk_job_status(job_dir, artifacts, version_index)
        operation = load_job_operation(job_dir)
        interrupted_event = _latest_interrupted_processing_event(job_dir)
        failure_error = _latest_disk_failure_error(job_dir)
        if snapshot is not None:
            status = _snapshot_status(
                job_dir,
                snapshot,
                operation,
                legacy_status,
                repair_markers=True,
            )
            snapshot_status_changed = status != snapshot.status
            if snapshot_status_changed:
                step, progress = _recovered_step_and_progress(
                    status,
                    cancel_marker=cancel_marker,
                    operation=operation,
                    interrupted_event=interrupted_event,
                    failure_error=failure_error,
                )
                stage = infer_job_stage(status, "")
            else:
                step = snapshot.step
                progress = snapshot.progress
                stage = snapshot.stage
            marker_work_progress = _work_progress_from_payload(cancel_marker.get("work_progress"))
            work_progress = snapshot.work_progress or marker_work_progress
            if work_progress is None:
                work_progress = _infer_resumable_work_progress(job_dir, metadata, status)
            if status == JobStatus.failed:
                error = snapshot.error or failure_error or "最近一次处理未完成，正在等待重试。"
                failure_context = snapshot.failure_context or _latest_disk_failure_context(job_dir)
            elif status in {
                JobStatus.succeeded,
                JobStatus.cancelled,
                JobStatus.awaiting_subtitle_confirmation,
                JobStatus.awaiting_note_review,
            }:
                error = None
                failure_context = None
            else:
                error = snapshot.error
                failure_context = snapshot.failure_context
            timestamp = snapshot.updated_at or fallback_timestamp
            step_started_at = snapshot.step_started_at or timestamp
            stage_elapsed_seconds = snapshot.stage_elapsed_seconds
            state_revision = snapshot.state_revision + (1 if snapshot_status_changed else 0)
        else:
            status = legacy_status
            step, progress = _recovered_step_and_progress(
                status,
                cancel_marker=cancel_marker,
                operation=operation,
                interrupted_event=interrupted_event,
                failure_error=failure_error,
            )
            stage = infer_job_stage(status, "")
            work_progress = _work_progress_from_payload(cancel_marker.get("work_progress"))
            if work_progress is None:
                work_progress = _infer_resumable_work_progress(job_dir, metadata, status)
            error = (
                None
                if status
                in {
                    JobStatus.succeeded,
                    JobStatus.cancelled,
                    JobStatus.awaiting_subtitle_confirmation,
                    JobStatus.awaiting_note_review,
                }
                else failure_error or "历史任务缺少完整笔记输出，可能在上次生成中断。"
            )
            failure_context = _latest_disk_failure_context(job_dir) if status == JobStatus.failed else None
            timestamp = fallback_timestamp
            step_started_at = timestamp
            stage_elapsed_seconds = 0
            state_revision = 1

        state = JobPublicState(
            job_id=job_id,
            status=status,
            step=step,
            stage=stage,
            progress=progress,
            work_progress=work_progress,
            error=error,
            failure_context=failure_context,
            artifacts=artifacts,
            artifact_revision=_artifact_revision(job_dir),
            state_revision=state_revision,
            step_started_at=step_started_at,
            updated_at=timestamp,
            stage_elapsed_seconds=stage_elapsed_seconds,
            download_filename=_zip_download_filename(job_dir) if (job_dir / "download.zip").exists() else None,
        )
        self._persist_state(job_id, state)
        with self._lock:
            self._jobs[job_id] = state
        return _copy_public_state(state)

    def list_history(self) -> list[JobSummary]:
        if not self.outputs_root.exists():
            return []

        summaries = [
            (self._summarize_job_dir(path), _job_history_activity_timestamp(path))
            for path in self._iter_job_dirs()
        ]
        return [
            summary
            for summary, _activity_timestamp in sorted(
                summaries,
                key=lambda item: (item[1] or item[0].created_at or "", item[0].created_at or ""),
                reverse=True,
            )
        ]

    def remove(self, job_id: str) -> None:
        with self._lock:
            self._jobs.pop(job_id, None)
            self._cancel_requested.discard(job_id)
            self._artifact_cache.pop(job_id, None)
            self._last_state_persisted_at.pop(job_id, None)

    def _iter_job_dirs(self) -> list[Path]:
        return [
            path
            for path in self.outputs_root.iterdir()
            if path.is_dir() and not path.name.startswith(".")
        ]

    def _summarize_job_dir(self, job_dir: Path) -> JobSummary:
        metadata = migrate_job_directory(job_dir)
        version_index = load_note_version_index(job_dir)
        artifacts = self.refresh_artifacts(job_dir.name)
        with self._lock:
            memory_state = self._jobs.get(job_dir.name)
        created_at = str(metadata.get("created_at") or _mtime_iso(job_dir))
        updated_at = str(_job_history_activity_timestamp(job_dir) or created_at)
        original_filename = normalize_uploaded_filename(str(metadata.get("original_filename") or job_dir.name))
        title = normalize_uploaded_filename(str(metadata.get("title") or original_filename), fallback=original_filename)
        snapshot = load_job_state(job_dir)
        legacy_status = _infer_disk_job_status(job_dir, artifacts, version_index)
        operation = load_job_operation(job_dir)
        if memory_state is not None:
            status = memory_state.status
        elif snapshot is not None:
            status = _snapshot_status(
                job_dir,
                snapshot,
                operation,
                legacy_status,
                repair_markers=False,
            )
        else:
            status = legacy_status
        error = None
        failure_context = None
        if status == JobStatus.failed:
            error = (
                memory_state.error
                if memory_state and memory_state.error
                else snapshot.error
                if snapshot and snapshot.error
                else _latest_disk_failure_error(job_dir)
            )
            failure_context = (
                memory_state.failure_context
                if memory_state and memory_state.failure_context
                else snapshot.failure_context
                if snapshot and snapshot.failure_context
                else _latest_disk_failure_context(job_dir)
            )
        return JobSummary(
            job_id=job_dir.name,
            title=title,
            original_filename=original_filename,
            created_at=created_at,
            updated_at=(
                memory_state.updated_at
                if memory_state and memory_state.updated_at
                else snapshot.updated_at
                if snapshot and snapshot.updated_at
                else updated_at
            ),
            status=status,
            error=error,
            failure_context=failure_context,
            duration_seconds=metadata.get("duration_seconds"),
            artifact_count=len(artifacts),
            note_version_count=len(version_index.versions),
            active_version_id=version_index.active_version_id,
        )

    def _read_metadata(self, job_dir: Path) -> dict:
        metadata_path = job_dir / "metadata.json"
        if not metadata_path.exists():
            return {}
        try:
            return json.loads(metadata_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}


def _mtime_iso(path: Path) -> str:
    return datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat()


def _copy_public_state(state: JobPublicState) -> JobPublicState:
    return state.model_copy(deep=True)


def _merge_newer_snapshot(
    state: JobPublicState,
    snapshot: JobStateSnapshot | None,
) -> None:
    if snapshot is None or snapshot.state_revision <= state.state_revision:
        return
    state.status = snapshot.status
    state.stage = snapshot.stage
    state.step = snapshot.step
    state.progress = snapshot.progress
    state.work_progress = (
        snapshot.work_progress.model_copy(deep=True)
        if snapshot.work_progress is not None
        else None
    )
    state.error = snapshot.error
    state.failure_context = (
        snapshot.failure_context.model_copy(deep=True)
        if snapshot.failure_context is not None
        else None
    )
    state.step_started_at = snapshot.step_started_at
    state.updated_at = snapshot.updated_at
    state.stage_elapsed_seconds = snapshot.stage_elapsed_seconds
    state.state_revision = snapshot.state_revision


def _work_progress_crossed_durable_boundary(
    previous: TranscriptionWorkProgress | None,
    current: TranscriptionWorkProgress | None,
    *,
    supplied: bool,
) -> bool:
    if not supplied:
        return False
    if previous is None or current is None:
        return previous != current
    return (
        previous.total_seconds != current.total_seconds
        or previous.completed_chunks != current.completed_chunks
        or previous.total_chunks != current.total_chunks
        or previous.current_chunk != current.current_chunk
        or previous.resumable != current.resumable
        or previous.cache_hits != current.cache_hits
        or previous.device != current.device
        or previous.compute_type != current.compute_type
    )


def _zip_download_filename(job_dir: Path) -> str:
    metadata_path = job_dir / "metadata.json"
    metadata: dict = {}
    if metadata_path.exists():
        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            metadata = {}
    title = str(metadata.get("title") or metadata.get("original_filename") or job_dir.name).strip() or job_dir.name
    stem = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", title).strip(" ._") or job_dir.name
    if stem.lower().endswith(".zip"):
        return stem
    return f"{stem}.zip"


def _job_history_activity_timestamp(job_dir: Path) -> str | None:
    timestamps: list[str] = []
    snapshot = load_job_state(job_dir)
    if snapshot and snapshot.updated_at:
        timestamps.append(snapshot.updated_at)
    timestamps.extend(
        record.get("ts")
        for record in _debug_log_events(job_dir)
        if isinstance(record.get("ts"), str) and record.get("ts")
    )
    operation = load_job_operation(job_dir)
    if operation and operation.updated_at:
        timestamps.append(operation.updated_at)
    if timestamps:
        return max(timestamps)
    debug_log = job_dir / "debug.log"
    if debug_log.exists():
        return _mtime_iso(debug_log)
    return None


def _infer_disk_job_status(job_dir: Path, artifacts: list[Artifact], version_index) -> JobStatus:
    if (job_dir / CANCELLED_MARKER).exists():
        return JobStatus.cancelled
    # A review marker is an authoritative recovery point. A previous attempt
    # may have been interrupted while preparing optional review assets, but
    # once the note is explicitly marked for review it must remain reachable.
    if (job_dir / ".note-review.pending").exists():
        return JobStatus.awaiting_note_review
    operation = load_job_operation(job_dir)
    if operation and operation.status in {
        OperationStatus.queued,
        OperationStatus.recovering,
        OperationStatus.running,
        OperationStatus.waiting_for_credentials,
        OperationStatus.failed,
        OperationStatus.interrupted,
    }:
        return JobStatus.failed
    if _latest_interrupted_processing_event(job_dir):
        return JobStatus.failed

    latest_terminal_event = _latest_terminal_debug_event(job_dir)
    if latest_terminal_event and latest_terminal_event.get("message") == "failed":
        return JobStatus.failed

    artifact_paths = {artifact.path for artifact in artifacts}
    if "note.md" in artifact_paths:
        return JobStatus.succeeded
    if "subtitles.md" in artifact_paths and (job_dir / "subtitles.pending").exists():
        return JobStatus.awaiting_subtitle_confirmation
    for version in version_index.versions:
        try:
            note_path = resolve_job_relative_path(job_dir, version.note_path)
        except ValueError:
            continue
        if note_path.exists():
            return JobStatus.succeeded
    return JobStatus.failed


def _latest_disk_failure_error(job_dir: Path) -> str | None:
    operation = load_job_operation(job_dir)
    if operation and operation.status in {
        OperationStatus.waiting_for_credentials,
        OperationStatus.failed,
        OperationStatus.interrupted,
    }:
        return operation.error or "最近一次处理未完成，正在等待重试。"

    interrupted_event = _latest_interrupted_processing_event(job_dir)
    if interrupted_event:
        return _summarize_interrupted_processing_event(interrupted_event)

    latest_terminal_event = _latest_terminal_debug_event(job_dir)
    if not latest_terminal_event or latest_terminal_event.get("message") != "failed":
        return None

    details = latest_terminal_event.get("details")
    if not isinstance(details, dict):
        return "最近一次处理失败。"
    message = str(details.get("exception_message") or details.get("error") or "").strip()
    if _is_invalid_note_json_message(message):
        finish_reason_summary = _latest_note_response_finish_reason_summary(job_dir, "content_filter")
        if finish_reason_summary:
            return _append_failure_location(
                "笔记模型输出被内容过滤（finish_reason=content_filter），导致返回的 JSON 为空或不完整。可重试生成，或减少单次内容、调整补充要求、或更换模型。",
                finish_reason_summary,
            )
    if _is_invalid_note_json_message(message):
        finish_reason_summary = _latest_note_response_finish_reason_summary(job_dir, "length")
        if finish_reason_summary:
            return _append_failure_location(
                "笔记模型输出被截断（finish_reason=length），导致返回的 JSON 不完整。可重试生成，或减少单次内容长度、提高 max_tokens、或更换模型。",
                finish_reason_summary,
            )
    summary = _summarize_failure_message(details, message)
    request_context = _latest_note_api_error_request_context(job_dir)
    if request_context:
        return _append_failure_location(summary, request_context)
    return summary


def _latest_disk_failure_context(job_dir: Path) -> FailureContext | None:
    interrupted_event = _latest_interrupted_processing_event(job_dir)
    if interrupted_event:
        return _failure_context_from_event(interrupted_event)

    relevant_events = _latest_failed_run_events(job_dir)
    for event in reversed(relevant_events):
        if event.get("stage") != "note_model_call" or event.get("message") != "api_error":
            continue
        details = event.get("details")
        if not isinstance(details, dict):
            continue
        request_details = _matching_note_request_details(relevant_events, details) or details
        return _failure_context_from_event(event, request_details)

    for event in reversed(relevant_events):
        if event.get("stage") != "note_model_call" or event.get("message") not in {
            "failed",
            "invalid_json",
            "response_received",
        }:
            continue
        details = event.get("details")
        context_details = _matching_note_model_context_details(relevant_events, details) if isinstance(details, dict) else None
        return _failure_context_from_event(event, context_details)

    latest_terminal_event = _latest_terminal_debug_event(job_dir)
    if latest_terminal_event and latest_terminal_event.get("message") == "failed":
        return _failure_context_from_event(latest_terminal_event)
    return None


def _failure_context_from_event(event: dict, request_details: dict | None = None) -> FailureContext | None:
    details = event.get("details")
    merged_details: dict[str, object] = dict(details) if isinstance(details, dict) else {}
    if isinstance(request_details, dict):
        merged_details.update(request_details)

    payload: dict[str, object] = {}
    for field in ("ts", "stage", "message"):
        value = event.get(field)
        if isinstance(value, str) and value:
            payload[field] = value
    for field in ("context", "note_base_url", "note_model", "response_file", "finish_reason"):
        value = merged_details.get(field)
        if isinstance(value, str) and value:
            payload[field] = value
    for field in ("attempt", "message_chars", "max_tokens", "response_length", "status_code"):
        value = merged_details.get(field)
        if isinstance(value, int | float):
            payload[field] = value
    payload.update(_extract_provider_error_details(merged_details))

    summary = _summarize_failure_context_payload(payload)
    if summary:
        payload["summary"] = summary

    if not payload.get("stage") and not payload.get("message"):
        return None
    return FailureContext(**payload)


def _extract_provider_error_details(details: dict[str, object]) -> dict[str, object]:
    body = details.get("body")
    if not isinstance(body, dict):
        return {}

    error = body.get("error")
    source = error if isinstance(error, dict) else body
    extracted: dict[str, object] = {}
    code = source.get("code")
    if isinstance(code, str) and code:
        extracted["error_code"] = code
    categories = source.get("flagged_categories")
    if isinstance(categories, list):
        extracted["flagged_categories"] = [str(category) for category in categories if category]
    elif isinstance(categories, dict):
        extracted["flagged_categories"] = [str(category) for category, flagged in categories.items() if flagged]
    return extracted


def _summarize_failure_context_payload(payload: dict[str, object]) -> str:
    parts: list[str] = []
    if payload.get("context"):
        parts.append(str(payload["context"]))
    if payload.get("attempt") not in (None, ""):
        parts.append(f"第 {payload['attempt']} 次请求")
    if payload.get("note_model"):
        parts.append(f"模型 {payload['note_model']}")
    if payload.get("note_base_url"):
        parts.append(f"接口 {payload['note_base_url']}")
    if payload.get("message_chars") not in (None, ""):
        parts.append(f"{payload['message_chars']} 字符")
    if payload.get("max_tokens") not in (None, ""):
        parts.append(f"max_tokens={payload['max_tokens']}")
    if payload.get("response_length") not in (None, ""):
        parts.append(f"response_length={payload['response_length']}")
    if payload.get("finish_reason"):
        parts.append(f"finish_reason={payload['finish_reason']}")
    if payload.get("response_file"):
        parts.append(f"response_file={payload['response_file']}")
    if payload.get("status_code") not in (None, ""):
        parts.append(f"HTTP {payload['status_code']}")
    if payload.get("error_code"):
        parts.append(str(payload["error_code"]))
    flagged_categories = payload.get("flagged_categories")
    if isinstance(flagged_categories, list) and flagged_categories:
        parts.append(f"分类 {', '.join(str(category) for category in flagged_categories)}")
    if parts:
        return "，".join(parts)
    stage = payload.get("stage")
    message = payload.get("message")
    if stage and message:
        return f"{stage}/{message}"
    return ""


def _append_failure_location(summary: str, location: str) -> str:
    if not location:
        return summary
    return f"{summary} 失败位置：{location}。"


def _summarize_failure_message(details: dict, message: str) -> str:
    exception_type = str(details.get("exception_type") or "").strip()
    normalized = message.casefold()
    if "content_policy_violation" in normalized:
        return "笔记模型请求被内容安全策略拦截（content_policy_violation）。可尝试重新生成、减少单次内容或更换模型。"
    if "finish_reason=content_filter" in normalized or "content filter" in normalized:
        return "笔记模型输出被内容过滤（finish_reason=content_filter）。可重试生成，或减少单次内容、调整补充要求、或更换模型。"
    if exception_type == "AuthenticationError" or "invalid token" in normalized:
        return "API 认证失败（401 invalid token）。请检查 API Key 或接口地址。"
    if (
        exception_type == "NotFoundError"
        or "model not found" in normalized
        or ("not found" in normalized and " 404 " in f" {normalized} ")
    ):
        return "模型或接口地址不存在（404/model not found）。请检查模型名称、Base URL 和供应商接口路径。"
    if exception_type == "RateLimitError" or "rate limit" in normalized or "quota" in normalized or " 429 " in f" {normalized} ":
        return "API 请求被限流或额度不足（429/rate limit）。请稍后重试，或检查账号额度、模型并发限制。"
    if exception_type == "APIConnectionError" or "connection error" in normalized or "could not connect" in normalized:
        return "无法连接到模型接口。请检查网络、代理、防火墙或接口地址后重试。"
    if exception_type == "APITimeoutError" or "timed out" in normalized or "timeout" in normalized:
        return "笔记模型请求超时。可重试生成，或减少单次内容、更换模型/接口后再试。"
    if (
        exception_type == "InternalServerError"
        or re.search(r"\b5\d\d\b", normalized)
        or "server error" in normalized
        or "service unavailable" in normalized
        or "bad gateway" in normalized
        or "gateway timeout" in normalized
    ):
        return "模型服务暂时不可用（5xx/server error）。请稍后重试，或临时更换模型/接口。"
    if _is_invalid_note_json_message(message):
        return "笔记模型返回了空内容或非 JSON，无法解析为结构化笔记。可重试生成，或更换模型、减少单次内容长度。"
    return message or "最近一次处理失败。"


def _latest_note_api_error_request_context(job_dir: Path) -> str:
    events = _debug_log_events(job_dir)
    latest_failed_index: int | None = None
    for index, event in enumerate(events):
        if event.get("stage") in TERMINAL_DEBUG_STAGES and event.get("message") == "failed":
            latest_failed_index = index
    if latest_failed_index is None:
        return ""

    latest_started_index = 0
    for index in range(latest_failed_index, -1, -1):
        event = events[index]
        if event.get("stage") in TERMINAL_DEBUG_STAGES and event.get("message") in {"started", "starting"}:
            latest_started_index = index
            break

    relevant_events = events[latest_started_index : latest_failed_index + 1]
    for event in reversed(relevant_events):
        if event.get("stage") != "note_model_call" or event.get("message") != "api_error":
            continue
        details = event.get("details")
        if not isinstance(details, dict):
            continue
        failure_context = _failure_context_from_event(
            event,
            _matching_note_request_details(relevant_events, details),
        )
        if failure_context and failure_context.summary:
            return failure_context.summary
        return _summarize_note_request_details(details)
    return ""


def _matching_note_request_details(events: list[dict], api_error_details: dict) -> dict | None:
    context = api_error_details.get("context")
    attempt = api_error_details.get("attempt")
    for event in reversed(events):
        if event.get("stage") != "note_model_call" or event.get("message") != "requesting":
            continue
        details = event.get("details")
        if not isinstance(details, dict):
            continue
        if context not in (None, "") and details.get("context") != context:
            continue
        if attempt not in (None, "") and details.get("attempt") != attempt:
            continue
        return details
    return None


def _matching_note_model_context_details(events: list[dict], details: dict) -> dict:
    merged: dict = {}
    request_details = _matching_note_request_details(events, details)
    if request_details:
        merged.update(request_details)
    response_details = _matching_note_response_details(events, details)
    if response_details:
        merged.update(response_details)
    merged.update(details)
    return merged


def _matching_note_response_details(events: list[dict], details: dict) -> dict | None:
    context = details.get("context")
    attempt = details.get("attempt")
    for event in reversed(events):
        if event.get("stage") != "note_model_call" or event.get("message") != "response_received":
            continue
        response_details = event.get("details")
        if not isinstance(response_details, dict):
            continue
        if context not in (None, "") and response_details.get("context") != context:
            continue
        if attempt not in (None, "") and response_details.get("attempt") != attempt:
            continue
        return response_details
    return None


def _summarize_note_request_details(details: dict) -> str:
    parts: list[str] = []
    if details.get("context"):
        parts.append(str(details["context"]))
    if details.get("attempt") not in (None, ""):
        parts.append(f"第 {details['attempt']} 次请求")
    if details.get("note_model"):
        parts.append(f"模型 {details['note_model']}")
    if details.get("note_base_url"):
        parts.append(f"接口 {details['note_base_url']}")
    if details.get("response_length") not in (None, ""):
        parts.append(f"response_length={details['response_length']}")
    if details.get("finish_reason"):
        parts.append(f"finish_reason={details['finish_reason']}")
    if details.get("response_file"):
        parts.append(f"response_file={details['response_file']}")
    if not parts:
        return ""
    return "，".join(parts)


def _is_invalid_note_json_message(message: str) -> bool:
    normalized = message.casefold()
    return "invalid note json" in normalized or "expecting value: line 1 column 1" in normalized


def _latest_note_response_finish_reason_summary(job_dir: Path, finish_reason: str) -> str:
    event = _latest_note_response_finish_reason_event(job_dir, finish_reason)
    if not event:
        return ""
    details = event.get("details")
    if not isinstance(details, dict):
        return ""
    events = _latest_failed_run_events(job_dir)
    return _summarize_note_request_details(_matching_note_model_context_details(events, details))


def _latest_note_response_finish_reason_event(job_dir: Path, finish_reason: str) -> dict | None:
    relevant_events = _latest_failed_run_events(job_dir)
    if not relevant_events:
        return None
    invalid_context = _latest_note_model_error_context(relevant_events)
    for event in reversed(relevant_events):
        if event.get("stage") != "note_model_call" or event.get("message") != "response_received":
            continue
        details = event.get("details")
        if not isinstance(details, dict):
            continue
        if str(details.get("finish_reason") or "").casefold() != finish_reason.casefold():
            continue
        if invalid_context and details.get("context") != invalid_context:
            continue
        return event
    return None


def _latest_failed_run_events(job_dir: Path) -> list[dict]:
    events = _debug_log_events(job_dir)
    latest_failed_index: int | None = None
    for index, event in enumerate(events):
        if event.get("stage") in TERMINAL_DEBUG_STAGES and event.get("message") == "failed":
            latest_failed_index = index
    if latest_failed_index is None:
        return []

    latest_started_index = 0
    for index in range(latest_failed_index, -1, -1):
        event = events[index]
        if event.get("stage") in TERMINAL_DEBUG_STAGES and event.get("message") in {"started", "starting"}:
            latest_started_index = index
            break
    return events[latest_started_index : latest_failed_index + 1]


def _latest_note_model_error_context(events: list[dict]) -> str | None:
    for event in reversed(events):
        if event.get("stage") != "note_model_call" or event.get("message") not in {"invalid_json", "failed"}:
            continue
        details = event.get("details")
        if isinstance(details, dict) and details.get("context"):
            return str(details["context"])
    return None


def _summarize_interrupted_processing_event(event: dict) -> str:
    stage = str(event.get("stage") or "unknown")
    message = str(event.get("message") or "unknown")
    details = event.get("details")
    context = ""
    if isinstance(details, dict) and details.get("context"):
        context = f"（{details['context']}）"
    request_details = ""
    if stage == "note_model_call" and message == "requesting" and isinstance(details, dict):
        request_details = _summarize_interrupted_model_request_details(details)
    detail_sentence = f"；{request_details}" if request_details else ""
    return f"最近一次处理在 {stage}/{message}{context} 后中断{detail_sentence}，可能是应用关闭、进程退出或模型请求长时间无响应。请查看调试日志后重试。"


def _summarize_interrupted_model_request_details(details: dict) -> str:
    parts: list[str] = []
    if details.get("attempt") not in (None, ""):
        parts.append(f"第 {details['attempt']} 次请求")
    if details.get("note_model"):
        parts.append(f"模型 {details['note_model']}")
    if details.get("note_base_url"):
        parts.append(f"接口 {details['note_base_url']}")
    if details.get("message_chars") not in (None, ""):
        parts.append(f"{details['message_chars']} 字符")
    if details.get("max_tokens") not in (None, ""):
        parts.append(f"max_tokens={details['max_tokens']}")
    if not parts:
        return ""
    return f"请求详情：{'，'.join(parts)}"


def _latest_interrupted_processing_event(job_dir: Path) -> dict | None:
    events = _debug_log_events(job_dir)
    latest_started_index: int | None = None
    latest_terminal_index: int | None = None
    latest_event: dict | None = None

    for index, record in enumerate(events):
        latest_event = record
        if record.get("stage") not in TERMINAL_DEBUG_STAGES:
            continue
        message = record.get("message")
        if message in {"started", "starting"}:
            latest_started_index = index
        elif message in {"failed", "succeeded", "awaiting_confirmation", "awaiting_review"}:
            latest_terminal_index = index

    if latest_started_index is None:
        return None
    if latest_terminal_index is not None and latest_terminal_index > latest_started_index:
        return None
    return latest_event


def _latest_terminal_debug_event(job_dir: Path) -> dict | None:
    latest: dict | None = None
    for record in _debug_log_events(job_dir):
        if (
            isinstance(record, dict)
            and record.get("stage") in TERMINAL_DEBUG_STAGES
            and record.get("message") in {"failed", "succeeded", "awaiting_confirmation", "awaiting_review"}
        ):
            latest = record
    return latest


def _debug_log_events(job_dir: Path) -> list[dict]:
    debug_log = job_dir / "debug.log"
    if not debug_log.exists():
        return []

    try:
        lines = debug_log.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []

    events: list[dict] = []
    for line in lines:
        record = _parse_debug_log_record(line)
        if isinstance(record, dict):
            events.append(record)
    return events


def _parse_debug_log_record(line: str) -> dict | None:
    try:
        record = json.loads(line)
    except json.JSONDecodeError:
        return _parse_malformed_debug_log_record(line)
    return record if isinstance(record, dict) else None


def _parse_malformed_debug_log_record(line: str) -> dict | None:
    stage = _extract_json_string_field(line, "stage")
    message = _extract_json_string_field(line, "message")
    if not stage or not message:
        return None
    record = {"stage": stage, "message": message}
    ts = _extract_json_string_field(line, "ts")
    if ts:
        record["ts"] = ts
    level = _extract_json_string_field(line, "level")
    if level:
        record["level"] = level
    details: dict[str, object] = {}
    for field in (
        "context",
        "exception_type",
        "exception_message",
        "error",
        "note_base_url",
        "note_model",
        "response_file",
        "finish_reason",
    ):
        value = _extract_json_string_field(line, field)
        if value:
            details[field] = value
    for field in ("attempt", "message_count", "message_chars", "max_tokens", "response_length"):
        value = _extract_json_number_field(line, field)
        if value is not None:
            details[field] = value
    record["details"] = details
    return record


def _extract_json_string_field(line: str, field: str) -> str | None:
    match = re.search(rf'"{re.escape(field)}"\s*:\s*"((?:\\.|[^"\\])*)"', line)
    if not match:
        return None
    raw_value = match.group(1)
    try:
        return json.loads(f'"{raw_value}"')
    except json.JSONDecodeError:
        return raw_value


def _extract_json_number_field(line: str, field: str) -> int | float | None:
    match = re.search(rf'"{re.escape(field)}"\s*:\s*(-?\d+(?:\.\d+)?)', line)
    if not match:
        return None
    raw_value = match.group(1)
    if "." in raw_value:
        return float(raw_value)
    return int(raw_value)
