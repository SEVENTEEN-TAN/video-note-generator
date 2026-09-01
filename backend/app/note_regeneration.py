from __future__ import annotations

import json
from pathlib import Path

from .job_store import JobStore
from .models import JobStage, JobStatus, NoteGenerationConfig
from .note_chunks import regenerate_chunk_and_reduce
from .note_versions import create_note_version_from_draft, find_source_video
from .operation_leases import assert_current_operation_lease
from .processor import prepare_note_review_artifacts, write_job_metadata
from .subtitles import transcript_segments_from_payload
from .task_debug_log import TaskDebugLog


def _regenerate_chunk_job(
    job_id: str,
    job_dir: Path,
    config: NoteGenerationConfig,
    chunk_id: str,
    store: JobStore,
) -> None:
    """Regenerate one note chunk and rebuild the active review artifacts."""

    debug_log = TaskDebugLog(job_dir)
    try:
        if store.is_cancel_requested(job_id):
            store.mark_cancelled(job_id)
            return
        store.update(
            job_id,
            status=JobStatus.running,
            stage=JobStage.generating_note,
            step="重新生成笔记块",
            progress=70,
            error="",
        )
        metadata = json.loads((job_dir / "metadata.json").read_text(encoding="utf-8"))
        duration = metadata.get("duration_seconds")
        transcript_payload = json.loads((job_dir / "transcript.json").read_text(encoding="utf-8"))
        segments = transcript_segments_from_payload(transcript_payload)
        system_prompt = (
            "You are a professional video content editor, course note writer, and knowledge management expert. "
            "You must write only from the transcript. Do not invent facts. "
            "Return strict JSON only. Preserve timestamps for chapter navigation and frame extraction."
        )
        debug_log.event("regenerate_note_chunk", "starting", chunk_id=chunk_id)
        draft = regenerate_chunk_and_reduce(job_dir, config, duration, segments, chunk_id, system_prompt)
        debug_log.event("regenerate_note_chunk", "draft_succeeded", chunk_id=chunk_id)
        if store.is_cancel_requested(job_id):
            store.mark_cancelled(job_id)
            return
        write_job_metadata(
            job_id=job_id,
            job_dir=job_dir,
            input_config=config,
            note_config=config,
            title=draft.title,
            duration=duration,
        )
        stale_zip = job_dir / "download.zip"
        if stale_zip.exists():
            assert_current_operation_lease()
            stale_zip.unlink()
        video_path = find_source_video(job_dir)
        duration_value = float(duration) if duration is not None else None
        store.update(job_id, stage=JobStage.generating_frames, step="关键帧抽取", progress=78)
        create_note_version_from_draft(
            job_dir=job_dir,
            video_path=video_path,
            draft=draft,
            duration=duration_value,
            config=config,
            is_cancelled=lambda: store.is_cancel_requested(job_id),
        )
        if store.is_cancel_requested(job_id):
            store.mark_cancelled(job_id)
            return
        if not prepare_note_review_artifacts(
            job_id=job_id,
            job_dir=job_dir,
            video_path=video_path,
            duration=duration_value,
            store=store,
            debug_log=debug_log,
        ):
            return
        debug_log.event("regenerate_note_chunk", "awaiting_review", chunk_id=chunk_id)
    except Exception as exc:
        if store.is_cancel_requested(job_id):
            debug_log.event("regenerate_note_chunk", "cancelled", reason=str(exc))
            store.refresh_artifacts(job_id)
            store.mark_cancelled(job_id)
            return
        debug_log.exception("regenerate_note_chunk", "failed", exc)
        store.refresh_artifacts(job_id)
        store.update(
            job_id,
            status=JobStatus.failed,
            stage=JobStage.failed,
            step="失败",
            error=str(exc),
            progress=100,
        )
        if store.is_cancel_requested(job_id):
            store.mark_cancelled(job_id)
