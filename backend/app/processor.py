from __future__ import annotations

import json
import inspect
import shutil
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from zipfile import ZIP_DEFLATED, ZipFile

from .ffmpeg_tools import (
    FFmpegError,
    PreparedAudio,
    extract_mp3,
    load_prepared_audio_artifacts,
    prepare_audio_artifacts,
    probe_duration,
)
from .frame_candidates import build_frame_candidate_index, write_frame_candidate_index
from .job_store import JobStore
from .llm import LLMError, generate_chunked_note_draft_with_chunks, generate_note_draft
from .models import JobConfig, JobStage, JobStatus, TranscriptionMode
from .note_chunks import save_note_chunks
from .note_versions import (
    create_note_version_from_draft,
    load_note_version_index,
    note_version_index_path,
    regenerate_note_version,
    resolve_job_relative_path,
    safe_note_version_id,
)
from .review_finalization import NOTE_REVIEW_PENDING_MARKER, mark_note_review_pending
from .review_quality import build_quality_report, write_quality_report
from .subtitles import SubtitleParseError, parse_srt_file, transcript_segments_from_payload, write_subtitle_files
from .storage_policy import available_storage_bytes, estimate_local_job_storage
from .task_debug_log import TaskDebugLog
from .transcription import (
    TranscriptionCancelled,
    TranscriptionError,
    resolve_local_transcription_plan,
    transcribe_audio,
)
from .transcription_checkpoints import atomic_write_json


class ProcessingError(RuntimeError):
    pass


SUBTITLES_PENDING_MARKER = "subtitles.pending"
ZIP_DIRTY_MARKER = ".download.zip.dirty"
_ZIP_LOCKS_GUARD = Lock()
_ZIP_LOCKS: dict[str, Lock] = {}


def _config_debug_summary(config: JobConfig) -> dict:
    return {
        "original_filename": config.original_filename,
        "transcription_mode": config.transcription_mode.value,
        "transcription_base_url": config.transcription_base_url,
        "transcription_model": config.transcription_model,
        "local_whisper_device": config.local_whisper_device,
        "local_whisper_compute_type": config.local_whisper_compute_type,
        "performance_mode": config.performance_mode.value,
        "transcription_language": str(config.transcription_language),
        "note_base_url": config.note_base_url,
        "note_model": config.note_model,
        "note_language": config.note_language.value,
        "note_style": config.note_style.value,
        "extras_present": bool(config.extras),
        "extras_length": len(config.extras),
        "frame_limit": config.frame_limit,
    }


def _file_size(path: Path) -> int | None:
    try:
        return path.stat().st_size
    except OSError:
        return None


def _extract_mp3_with_cancellation(video_path: Path, audio_path: Path, is_cancelled) -> None:
    if "is_cancelled" in inspect.signature(extract_mp3).parameters:
        extract_mp3(video_path, audio_path, is_cancelled=is_cancelled)
    else:
        extract_mp3(video_path, audio_path)


def write_job_metadata(
    *,
    job_id: str,
    job_dir: Path,
    config: JobConfig,
    title: str,
    duration: float | None,
    subtitle_source: str | None = None,
    uploaded_subtitle_filename: str | None = None,
) -> dict:
    existing = _read_metadata(job_dir)
    resolved_subtitle_source = subtitle_source or str(existing.get("subtitle_source") or "transcribed")
    resolved_uploaded_subtitle_filename = (
        uploaded_subtitle_filename
        if uploaded_subtitle_filename is not None
        else str(existing.get("uploaded_subtitle_filename") or "")
    )
    metadata = {
        "schema_version": 1,
        "job_id": job_id,
        "created_at": str(existing.get("created_at") or datetime.now(timezone.utc).isoformat()),
        "original_filename": config.original_filename,
        "transcription_mode": config.transcription_mode.value,
        "transcription_base_url": config.transcription_base_url,
        "transcription_model": config.transcription_model,
        "local_whisper_device": config.local_whisper_device,
        "local_whisper_compute_type": config.local_whisper_compute_type,
        "performance_mode": config.performance_mode.value,
        "transcription_language": str(config.transcription_language),
        "note_base_url": config.note_base_url,
        "note_model": config.note_model,
        "note_language": config.note_language.value,
        "note_style": config.note_style.value,
        "extras_present": bool(config.extras),
        "extras_length": len(config.extras),
        "frame_limit": config.frame_limit,
        "subtitle_source": resolved_subtitle_source,
        "uploaded_subtitle_filename": resolved_uploaded_subtitle_filename,
        "duration_seconds": duration,
        "title": title.strip() or config.original_filename,
    }
    atomic_write_json(job_dir / "metadata.json", metadata)
    return metadata


def mark_zip_dirty(job_dir: Path) -> Path:
    marker = job_dir / ZIP_DIRTY_MARKER
    with _zip_lock(job_dir):
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text("1", encoding="utf-8")
    return marker


def _zip_lock(job_dir: Path) -> Lock:
    key = str(job_dir.resolve()).casefold()
    with _ZIP_LOCKS_GUARD:
        return _ZIP_LOCKS.setdefault(key, Lock())


def create_zip(job_dir: Path, *, force: bool = False) -> Path:
    zip_path = job_dir / "download.zip"
    dirty_marker = job_dir / ZIP_DIRTY_MARKER
    if zip_path.exists() and not force and not dirty_marker.exists():
        return zip_path
    with _zip_lock(job_dir):
        if zip_path.exists() and not force and not dirty_marker.exists():
            return zip_path
        return _build_zip(job_dir, zip_path, dirty_marker)


def _build_zip(job_dir: Path, zip_path: Path, dirty_marker: Path) -> Path:
    tmp_path = job_dir / "download.zip.tmp"
    include_names = [
        "note.md",
        "audio.mp3",
        "subtitles.srt",
        "subtitles.vtt",
        "subtitles.md",
        "transcript.json",
        "metadata.json",
        "debug.log",
    ]
    try:
        with ZipFile(tmp_path, "w", compression=ZIP_DEFLATED) as archive:
            for name in include_names:
                file_path = job_dir / name
                if file_path.exists():
                    archive.write(file_path, arcname=name)
            frames_dir = job_dir / "frames"
            if frames_dir.exists():
                for frame_path in sorted(frames_dir.glob("*.jpg")):
                    archive.write(frame_path, arcname=frame_path.relative_to(job_dir).as_posix())
            version_index_path = note_version_index_path(job_dir)
            version_index = load_note_version_index(job_dir)
            if version_index_path.exists() or version_index.versions:
                archive.writestr("notes/versions.json", version_index.model_dump_json(indent=2))
            debug_dir = job_dir / "debug"
            if debug_dir.exists():
                for debug_path in sorted(path for path in debug_dir.rglob("*") if path.is_file()):
                    archive.write(debug_path, arcname=debug_path.relative_to(job_dir).as_posix())
            review_dir = job_dir / "review"
            for review_name in ("quality_report.json", "quality_report.md", "frame_candidates.json"):
                review_path = review_dir / review_name
                if review_path.exists():
                    archive.write(review_path, arcname=review_path.relative_to(job_dir).as_posix())
            selected_ids = set(version_index.selected_version_ids)
            for version in version_index.versions:
                if version.id not in selected_ids:
                    continue
                try:
                    archive_version_id = safe_note_version_id(version.id)
                    note_path = resolve_job_relative_path(job_dir, version.note_path)
                    frame_dir = resolve_job_relative_path(job_dir, version.frame_dir)
                except ValueError:
                    continue
                if note_path.exists():
                    archive.write(note_path, arcname=f"notes/{archive_version_id}/note.md")
                if frame_dir.exists():
                    for frame_path in sorted(frame_dir.glob("*.jpg")):
                        archive.write(frame_path, arcname=f"notes/{archive_version_id}/frames/{frame_path.name}")
        tmp_path.replace(zip_path)
        dirty_marker.unlink(missing_ok=True)
    finally:
        if tmp_path.exists():
            tmp_path.unlink()
    return zip_path



def _stop_if_cancelled(job_id: str, store: JobStore) -> bool:
    if not store.is_cancel_requested(job_id):
        return False
    store.refresh_artifacts(job_id)
    store.mark_cancelled(job_id)
    return True


def _fail_or_cancel(
    *,
    job_id: str,
    store: JobStore,
    debug_log: TaskDebugLog,
    debug_stage: str,
    exc: Exception,
) -> None:
    if store.is_cancel_requested(job_id):
        debug_log.event(debug_stage, "cancelled", reason=str(exc))
        store.refresh_artifacts(job_id)
        store.mark_cancelled(job_id)
        return
    debug_log.exception(debug_stage, "failed", exc)
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


def process_transcription_job(
    *,
    job_id: str,
    job_dir: Path,
    video_path: Path,
    config: JobConfig,
    store: JobStore,
) -> None:
    debug_log = TaskDebugLog(job_dir)
    debug_log.event(
        "process_transcription_job",
        "started",
        job_id=job_id,
        job_dir=str(job_dir),
        video_path=str(video_path),
        video_size_bytes=_file_size(video_path),
        config=_config_debug_summary(config),
    )
    try:
        debug_log.event("probe_duration", "starting", video_path=str(video_path))
        if _stop_if_cancelled(job_id, store):
            return
        store.update(
            job_id,
            status=JobStatus.running,
            stage=JobStage.analyzing_video,
            step="分析视频",
            progress=5,
        )
        duration = probe_duration(video_path)
        debug_log.event("probe_duration", "succeeded", duration_seconds=duration)

        if _stop_if_cancelled(job_id, store):
            return
        store.update(job_id, stage=JobStage.extracting_audio, step="音频准备", progress=15)
        audio_path = job_dir / "audio.mp3"
        prepared_audio: PreparedAudio | None = None
        if config.transcription_mode == TranscriptionMode.local_faster_whisper:
            plan = resolve_local_transcription_plan(config, float(duration or 0.0))
            asr_dir = job_dir / "work" / "asr"
            storage_estimate = estimate_local_job_storage(
                source_bytes=_file_size(video_path) or 0,
                duration_seconds=float(duration or 0.0),
                frame_limit=config.frame_limit,
            )
            available_bytes = available_storage_bytes(job_dir)
            debug_log.event(
                "storage_preflight",
                "succeeded",
                required_free_bytes=storage_estimate.required_free_bytes,
                available_bytes=available_bytes,
            )
            if available_bytes < storage_estimate.required_free_bytes:
                shortfall = storage_estimate.required_free_bytes - available_bytes
                raise ProcessingError(
                    f"Insufficient disk space for local transcription. Free at least {shortfall} more bytes "
                    "or clean an existing transcription cache."
                )
            try:
                prepared_audio = load_prepared_audio_artifacts(
                    audio_path,
                    asr_dir,
                    plan.chunk_seconds,
                    duration_seconds=float(duration or 0.0),
                )
                debug_log.event(
                    "prepare_audio_artifacts",
                    "reused",
                    audio_path=str(audio_path),
                    chunk_count=len(prepared_audio.chunks),
                )
            except FFmpegError:
                debug_log.event("prepare_audio_artifacts", "starting", audio_path=str(audio_path))
                prepared_audio = prepare_audio_artifacts(
                    video_path,
                    audio_path,
                    asr_dir,
                    plan.chunk_seconds,
                    duration_seconds=float(duration or 0.0),
                    is_cancelled=lambda: store.is_cancel_requested(job_id),
                )
                debug_log.event(
                    "prepare_audio_artifacts",
                    "succeeded",
                    audio_size_bytes=_file_size(audio_path),
                    chunk_count=len(prepared_audio.chunks),
                )
        else:
            debug_log.event("extract_mp3", "starting", audio_path=str(audio_path))
            _extract_mp3_with_cancellation(
                video_path,
                audio_path,
                lambda: store.is_cancel_requested(job_id),
            )
            debug_log.event("extract_mp3", "succeeded", audio_size_bytes=_file_size(audio_path))
        store.refresh_artifacts(job_id)

        if _stop_if_cancelled(job_id, store):
            return
        store.update(job_id, stage=JobStage.transcribing, step="字幕生成", progress=35)
        debug_log.event("transcribe_audio", "starting", audio_path=str(audio_path))
        transcript_payload = transcribe_audio(
            audio_path,
            config,
            job_dir,
            progress_callback=lambda step, progress: store.update(
                job_id,
                stage=JobStage.transcribing,
                step=step,
                progress=progress,
            ),
            prepared_audio=prepared_audio,
            is_cancelled=lambda: store.is_cancel_requested(job_id),
            work_progress_callback=lambda work_progress: store.update(
                job_id,
                stage=JobStage.transcribing,
                work_progress=work_progress,
            ),
        )
        if _stop_if_cancelled(job_id, store):
            return
        transcript_path = job_dir / "transcript.json"
        debug_log.event(
            "transcribe_audio",
            "succeeded",
            text_length=len(str(transcript_payload.get("text") or "")),
            raw_segment_count=len(transcript_payload.get("segments") or []),
        )
        debug_log.event("write_transcript", "starting", transcript_path=str(transcript_path))
        atomic_write_json(transcript_path, transcript_payload)
        debug_log.event("write_transcript", "succeeded", transcript_size_bytes=_file_size(transcript_path))
        segments = transcript_segments_from_payload(transcript_payload)
        if not segments:
            raise ProcessingError("Transcription returned no usable text segments.")
        debug_log.event("write_subtitles", "starting", segment_count=len(segments))
        write_subtitle_files(segments, job_dir)
        debug_log.event("write_subtitles", "succeeded", segment_count=len(segments))
        # Persist duration so the note phase can resume without re-probing the video.
        write_job_metadata(
            job_id=job_id,
            job_dir=job_dir,
            config=config,
            title=config.original_filename,
            duration=duration,
            subtitle_source="transcribed",
            uploaded_subtitle_filename="",
        )
        (job_dir / SUBTITLES_PENDING_MARKER).write_text("1", encoding="utf-8")
        store.refresh_artifacts(job_id)
        store.update(
            job_id,
            status=JobStatus.awaiting_subtitle_confirmation,
            stage=JobStage.awaiting_subtitle_review,
            step="等待确认字幕",
            progress=40,
        )
        if store.is_cancel_requested(job_id):
            store.mark_cancelled(job_id)
            return
        debug_log.event("process_transcription_job", "awaiting_confirmation")
    except TranscriptionCancelled as exc:
        debug_log.event("process_transcription_job", "cancelled", reason=str(exc))
        store.mark_cancelled(job_id)
    except (FFmpegError, LLMError, TranscriptionError, ProcessingError, Exception) as exc:
        _fail_or_cancel(
            job_id=job_id,
            store=store,
            debug_log=debug_log,
            debug_stage="process_transcription_job",
            exc=exc,
        )


def process_uploaded_subtitle_job(
    *,
    job_id: str,
    job_dir: Path,
    video_path: Path,
    subtitle_path: Path,
    uploaded_subtitle_filename: str,
    config: JobConfig,
    store: JobStore,
) -> None:
    debug_log = TaskDebugLog(job_dir)
    debug_log.event(
        "process_uploaded_subtitle_job",
        "started",
        job_id=job_id,
        job_dir=str(job_dir),
        video_path=str(video_path),
        video_size_bytes=_file_size(video_path),
        subtitle_path=str(subtitle_path),
        subtitle_size_bytes=_file_size(subtitle_path),
        uploaded_subtitle_filename=uploaded_subtitle_filename,
        config=_config_debug_summary(config),
    )
    try:
        debug_log.event("probe_duration", "starting", video_path=str(video_path))
        if _stop_if_cancelled(job_id, store):
            return
        store.update(
            job_id,
            status=JobStatus.running,
            stage=JobStage.analyzing_video,
            step="分析视频",
            progress=10,
        )
        duration = probe_duration(video_path)
        debug_log.event("probe_duration", "succeeded", duration_seconds=duration)

        if _stop_if_cancelled(job_id, store):
            return
        store.update(job_id, stage=JobStage.transcribing, step="解析字幕", progress=30)
        debug_log.event("parse_uploaded_subtitle", "starting", subtitle_path=str(subtitle_path))
        segments = parse_srt_file(subtitle_path)
        if _stop_if_cancelled(job_id, store):
            return
        transcript_payload = {
            "text": "\n".join(segment.text for segment in segments),
            "segments": [segment.model_dump() for segment in segments],
        }
        transcript_path = job_dir / "transcript.json"
        atomic_write_json(transcript_path, transcript_payload)
        debug_log.event(
            "parse_uploaded_subtitle",
            "succeeded",
            segment_count=len(segments),
            transcript_size_bytes=_file_size(transcript_path),
        )

        debug_log.event("write_subtitles", "starting", segment_count=len(segments))
        write_subtitle_files(segments, job_dir)
        debug_log.event("write_subtitles", "succeeded", segment_count=len(segments))
        write_job_metadata(
            job_id=job_id,
            job_dir=job_dir,
            config=config,
            title=config.original_filename,
            duration=duration,
            subtitle_source="uploaded",
            uploaded_subtitle_filename=uploaded_subtitle_filename,
        )
        (job_dir / SUBTITLES_PENDING_MARKER).write_text("1", encoding="utf-8")
        store.refresh_artifacts(job_id)
        store.update(
            job_id,
            status=JobStatus.awaiting_subtitle_confirmation,
            stage=JobStage.awaiting_subtitle_review,
            step="等待确认字幕",
            progress=40,
        )
        if store.is_cancel_requested(job_id):
            store.mark_cancelled(job_id)
            return
        debug_log.event("process_uploaded_subtitle_job", "awaiting_confirmation")
    except (FFmpegError, SubtitleParseError, ProcessingError, OSError, Exception) as exc:
        _fail_or_cancel(
            job_id=job_id,
            store=store,
            debug_log=debug_log,
            debug_stage="process_uploaded_subtitle_job",
            exc=exc,
        )


def continue_job_to_notes(
    *,
    job_id: str,
    job_dir: Path,
    video_path: Path,
    config: JobConfig,
    store: JobStore,
) -> None:
    debug_log = TaskDebugLog(job_dir)
    debug_log.event(
        "continue_job_to_notes",
        "started",
        job_id=job_id,
        job_dir=str(job_dir),
        config=_config_debug_summary(config),
    )
    try:
        if _stop_if_cancelled(job_id, store):
            return
        if (job_dir / SUBTITLES_PENDING_MARKER).exists():
            (job_dir / SUBTITLES_PENDING_MARKER).unlink()
        metadata = _read_metadata(job_dir)
        duration = metadata.get("duration_seconds")
        transcript_payload = json.loads((job_dir / "transcript.json").read_text(encoding="utf-8"))
        segments = transcript_segments_from_payload(transcript_payload)
        if not segments:
            raise ProcessingError("Transcript has no usable text segments.")

        store.update(
            job_id,
            status=JobStatus.running,
            stage=JobStage.generating_note,
            step="笔记生成",
            progress=60,
            error="",
        )
        debug_log.event("generate_note_draft", "starting", segment_count=len(segments))
        system_prompt = (
            "You are a professional video content editor, course note writer, and knowledge management expert. "
            "You must write only from the transcript. Do not invent facts. "
            "Return strict JSON only. Preserve timestamps for chapter navigation and frame extraction."
        )
        draft, chunk_segs, chunk_drafts = generate_chunked_note_draft_with_chunks(
            config, duration, segments, system_prompt, debug_log=debug_log
        )
        if _stop_if_cancelled(job_id, store):
            return
        save_note_chunks(job_dir, segments, chunk_segs, chunk_drafts)
        debug_log.event("save_note_chunks", "succeeded", chunk_count=len(chunk_segs))
        debug_log.event(
            "generate_note_draft",
            "succeeded",
            title=draft.title,
            chapter_count=len(draft.chapters),
            key_moment_count=len(draft.key_moments),
            recommended_frame_count=draft.recommended_frame_count,
        )
        debug_log.event("write_metadata", "starting", title=draft.title, duration_seconds=duration)
        write_job_metadata(
            job_id=job_id,
            job_dir=job_dir,
            config=config,
            title=draft.title,
            duration=duration,
        )
        debug_log.event("write_metadata", "succeeded", metadata_size_bytes=_file_size(job_dir / "metadata.json"))

        if _stop_if_cancelled(job_id, store):
            return
        store.update(job_id, stage=JobStage.generating_frames, step="关键帧抽取", progress=78)
        debug_log.event("create_note_version", "starting", version_id="note_001")
        create_note_version_from_draft(
            job_dir=job_dir,
            video_path=video_path,
            draft=draft,
            duration=duration,
            config=config,
            is_cancelled=lambda: store.is_cancel_requested(job_id),
            version_id="note_001",
        )
        frame_dir = job_dir / "note_versions" / "note_001" / "frames"
        frame_count = len(list(frame_dir.glob("*.jpg"))) if frame_dir.exists() else 0
        debug_log.event("create_note_version", "succeeded", version_id="note_001", frame_count=frame_count)
        store.refresh_artifacts(job_id)

        if _stop_if_cancelled(job_id, store):
            return
        store.update(job_id, stage=JobStage.preparing_review, step="生成复核资料", progress=88)
        debug_log.event("build_frame_candidates", "starting")
        duration_value = float(duration) if duration is not None else None
        frame_candidates = build_frame_candidate_index(
            job_dir,
            video_path,
            duration=duration_value,
            is_cancelled=lambda: store.is_cancel_requested(job_id),
        )
        write_frame_candidate_index(job_dir, frame_candidates)
        debug_log.event("build_frame_candidates", "succeeded", candidate_count=len(frame_candidates.candidates))

        if _stop_if_cancelled(job_id, store):
            return
        debug_log.event("build_quality_report", "starting")
        quality_report = build_quality_report(job_dir)
        write_quality_report(job_dir, quality_report)
        debug_log.event("build_quality_report", "succeeded", status=quality_report.status)

        if _stop_if_cancelled(job_id, store):
            return
        mark_note_review_pending(job_dir)
        store.refresh_artifacts(job_id)
        store.update(
            job_id,
            status=JobStatus.awaiting_note_review,
            stage=JobStage.awaiting_note_review,
            step="等待复核笔记",
            progress=92,
        )
        if store.is_cancel_requested(job_id):
            store.mark_cancelled(job_id)
            return
        debug_log.event("await_note_review", "pending")
    except (FFmpegError, LLMError, TranscriptionError, ProcessingError, Exception) as exc:
        _fail_or_cancel(
            job_id=job_id,
            store=store,
            debug_log=debug_log,
            debug_stage="continue_job_to_notes",
            exc=exc,
        )


def regenerate_subtitles_job(
    *,
    job_id: str,
    job_dir: Path,
    video_path: Path,
    config: JobConfig,
    store: JobStore,
) -> None:
    debug_log = TaskDebugLog(job_dir)
    debug_log.event(
        "regenerate_subtitles_job",
        "started",
        job_id=job_id,
        job_dir=str(job_dir),
        config=_config_debug_summary(config),
    )
    try:
        if _stop_if_cancelled(job_id, store):
            return
        store.update(
            job_id,
            status=JobStatus.running,
            stage=JobStage.extracting_audio,
            step="音频分离",
            progress=20,
            error="",
        )
        debug_log.event("extract_mp3", "starting", audio_path=str(job_dir / "audio.mp3"))
        audio_path = job_dir / "audio.mp3"
        _extract_mp3_with_cancellation(
            video_path,
            audio_path,
            lambda: store.is_cancel_requested(job_id),
        )
        debug_log.event("extract_mp3", "succeeded", audio_size_bytes=_file_size(audio_path))
        store.refresh_artifacts(job_id)

        if _stop_if_cancelled(job_id, store):
            return
        store.update(job_id, stage=JobStage.transcribing, step="字幕生成", progress=30)
        debug_log.event("transcribe_audio", "starting", audio_path=str(audio_path))
        transcript_payload = transcribe_audio(
            audio_path,
            config,
            job_dir,
            progress_callback=lambda step, progress: store.update(
                job_id,
                stage=JobStage.transcribing,
                step=step,
                progress=progress,
            ),
        )
        if _stop_if_cancelled(job_id, store):
            return
        segments = transcript_segments_from_payload(transcript_payload)
        if not segments:
            raise ProcessingError("Transcription returned no usable text segments.")
        duration = probe_duration(video_path)
        if _stop_if_cancelled(job_id, store):
            return

        # Only replace the existing reviewed output after the new transcript is ready.
        for stale in ("note.md", "download.zip", SUBTITLES_PENDING_MARKER, NOTE_REVIEW_PENDING_MARKER):
            stale_path = job_dir / stale
            if stale_path.exists():
                stale_path.unlink()
        for stale_dir_name in ("note_versions", "frames", "review"):
            stale_dir = job_dir / stale_dir_name
            if stale_dir.exists():
                shutil.rmtree(stale_dir, ignore_errors=True)

        transcript_path = job_dir / "transcript.json"
        atomic_write_json(transcript_path, transcript_payload)
        write_subtitle_files(segments, job_dir)
        write_job_metadata(
            job_id=job_id,
            job_dir=job_dir,
            config=config,
            title=config.original_filename,
            duration=duration,
            subtitle_source="transcribed",
            uploaded_subtitle_filename="",
        )
        (job_dir / SUBTITLES_PENDING_MARKER).write_text("1", encoding="utf-8")
        store.refresh_artifacts(job_id)
        store.update(
            job_id,
            status=JobStatus.awaiting_subtitle_confirmation,
            stage=JobStage.awaiting_subtitle_review,
            step="等待确认字幕",
            progress=40,
        )
        if store.is_cancel_requested(job_id):
            store.mark_cancelled(job_id)
            return
        debug_log.event("regenerate_subtitles_job", "awaiting_confirmation")
    except (FFmpegError, LLMError, TranscriptionError, ProcessingError, Exception) as exc:
        _fail_or_cancel(
            job_id=job_id,
            store=store,
            debug_log=debug_log,
            debug_stage="regenerate_subtitles_job",
            exc=exc,
        )


def regenerate_note_job(
    *,
    job_id: str,
    job_dir: Path,
    config: JobConfig,
    store: JobStore,
) -> None:
    debug_log = TaskDebugLog(job_dir)
    debug_log.event(
        "regenerate_note_job",
        "started",
        job_id=job_id,
        job_dir=str(job_dir),
        config=_config_debug_summary(config),
    )
    try:
        if _stop_if_cancelled(job_id, store):
            return
        store.update(
            job_id,
            status=JobStatus.running,
            stage=JobStage.generating_note,
            step="重新生成笔记",
            progress=62,
            error="",
        )
        debug_log.event("regenerate_note_version", "starting")
        regenerate_note_version(
            job_dir,
            config,
            debug_log=debug_log,
            is_cancelled=lambda: store.is_cancel_requested(job_id),
        )
        debug_log.event("regenerate_note_version", "succeeded")
        store.refresh_artifacts(job_id)
        if _stop_if_cancelled(job_id, store):
            return
        store.update(job_id, stage=JobStage.finalizing, step="更新 ZIP", progress=92)
        mark_zip_dirty(job_dir)
        debug_log.event("create_zip", "deferred")
        store.refresh_artifacts(job_id)
        if _stop_if_cancelled(job_id, store):
            return
        store.update(
            job_id,
            status=JobStatus.succeeded,
            stage=JobStage.completed,
            step="完成",
            progress=100,
        )
        if store.is_cancel_requested(job_id):
            store.mark_cancelled(job_id)
            return
        debug_log.event("regenerate_note_job", "succeeded")
    except (FFmpegError, LLMError, ProcessingError, Exception) as exc:
        _fail_or_cancel(
            job_id=job_id,
            store=store,
            debug_log=debug_log,
            debug_stage="regenerate_note_job",
            exc=exc,
        )


def _read_metadata(job_dir: Path) -> dict:
    metadata_path = job_dir / "metadata.json"
    if not metadata_path.exists():
        return {}
    try:
        return json.loads(metadata_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
