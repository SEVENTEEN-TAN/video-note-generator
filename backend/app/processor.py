from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

from .ffmpeg_tools import FFmpegError, extract_mp3, probe_duration
from .frame_candidates import build_frame_candidate_index, write_frame_candidate_index
from .job_store import JobStore
from .llm import LLMError, generate_chunked_note_draft_with_chunks, generate_note_draft
from .models import JobConfig, JobStatus
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
from .subtitles import transcript_segments_from_payload, write_subtitle_files
from .task_debug_log import TaskDebugLog
from .transcription import TranscriptionError, transcribe_audio


class ProcessingError(RuntimeError):
    pass


SUBTITLES_PENDING_MARKER = "subtitles.pending"


def _config_debug_summary(config: JobConfig) -> dict:
    return {
        "original_filename": config.original_filename,
        "transcription_mode": config.transcription_mode.value,
        "transcription_base_url": config.transcription_base_url,
        "transcription_model": config.transcription_model,
        "local_whisper_device": config.local_whisper_device,
        "local_whisper_compute_type": config.local_whisper_compute_type,
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


def write_job_metadata(
    *,
    job_id: str,
    job_dir: Path,
    config: JobConfig,
    title: str,
    duration: float | None,
) -> dict:
    existing = _read_metadata(job_dir)
    metadata = {
        "job_id": job_id,
        "created_at": str(existing.get("created_at") or datetime.now(timezone.utc).isoformat()),
        "original_filename": config.original_filename,
        "transcription_mode": config.transcription_mode.value,
        "transcription_base_url": config.transcription_base_url,
        "transcription_model": config.transcription_model,
        "local_whisper_device": config.local_whisper_device,
        "local_whisper_compute_type": config.local_whisper_compute_type,
        "note_base_url": config.note_base_url,
        "note_model": config.note_model,
        "note_language": config.note_language.value,
        "note_style": config.note_style.value,
        "extras_present": bool(config.extras),
        "extras_length": len(config.extras),
        "frame_limit": config.frame_limit,
        "duration_seconds": duration,
        "title": title.strip() or config.original_filename,
    }
    (job_dir / "metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return metadata


def create_zip(job_dir: Path) -> Path:
    zip_path = job_dir / "download.zip"
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
    finally:
        if tmp_path.exists():
            tmp_path.unlink()
    return zip_path


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
        store.update(job_id, status=JobStatus.running, step="分析视频", progress=5)
        duration = probe_duration(video_path)
        debug_log.event("probe_duration", "succeeded", duration_seconds=duration)

        store.update(job_id, step="音频分离", progress=15)
        audio_path = job_dir / "audio.mp3"
        debug_log.event("extract_mp3", "starting", audio_path=str(audio_path))
        extract_mp3(video_path, audio_path)
        debug_log.event("extract_mp3", "succeeded", audio_size_bytes=_file_size(audio_path))
        store.refresh_artifacts(job_id)

        store.update(job_id, step="字幕生成", progress=35)
        debug_log.event("transcribe_audio", "starting", audio_path=str(audio_path))
        transcript_payload = transcribe_audio(
            audio_path,
            config,
            job_dir,
            progress_callback=lambda step, progress: store.update(job_id, step=step, progress=progress),
        )
        transcript_path = job_dir / "transcript.json"
        debug_log.event(
            "transcribe_audio",
            "succeeded",
            text_length=len(str(transcript_payload.get("text") or "")),
            raw_segment_count=len(transcript_payload.get("segments") or []),
        )
        debug_log.event("write_transcript", "starting", transcript_path=str(transcript_path))
        transcript_path.write_text(
            json.dumps(transcript_payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
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
        )
        (job_dir / SUBTITLES_PENDING_MARKER).write_text("1", encoding="utf-8")
        store.refresh_artifacts(job_id)
        store.update(
            job_id,
            status=JobStatus.awaiting_subtitle_confirmation,
            step="等待确认字幕",
            progress=40,
        )
        debug_log.event("process_transcription_job", "awaiting_confirmation")
    except (FFmpegError, LLMError, TranscriptionError, ProcessingError, Exception) as exc:
        debug_log.exception("process_transcription_job", "failed", exc)
        store.refresh_artifacts(job_id)
        store.update(job_id, status=JobStatus.failed, step="失败", error=str(exc), progress=100)


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
        if (job_dir / SUBTITLES_PENDING_MARKER).exists():
            (job_dir / SUBTITLES_PENDING_MARKER).unlink()
        metadata = _read_metadata(job_dir)
        duration = metadata.get("duration_seconds")
        transcript_payload = json.loads((job_dir / "transcript.json").read_text(encoding="utf-8"))
        segments = transcript_segments_from_payload(transcript_payload)
        if not segments:
            raise ProcessingError("Transcript has no usable text segments.")

        store.update(job_id, status=JobStatus.running, step="笔记生成", progress=60, error="")
        debug_log.event("generate_note_draft", "starting", segment_count=len(segments))
        system_prompt = (
            "You are a professional video content editor, course note writer, and knowledge management expert. "
            "You must write only from the transcript. Do not invent facts. "
            "Return strict JSON only. Preserve timestamps for chapter navigation and frame extraction."
        )
        draft, chunk_segs, chunk_drafts = generate_chunked_note_draft_with_chunks(
            config, duration, segments, system_prompt, debug_log=debug_log
        )
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

        store.update(job_id, step="关键帧抽取", progress=78)
        debug_log.event("create_note_version", "starting", version_id="note_001")
        create_note_version_from_draft(
            job_dir=job_dir,
            video_path=video_path,
            draft=draft,
            duration=duration,
            config=config,
            version_id="note_001",
        )
        frame_dir = job_dir / "note_versions" / "note_001" / "frames"
        frame_count = len(list(frame_dir.glob("*.jpg"))) if frame_dir.exists() else 0
        debug_log.event("create_note_version", "succeeded", version_id="note_001", frame_count=frame_count)
        store.refresh_artifacts(job_id)

        store.update(job_id, step="生成复核资料", progress=88)
        debug_log.event("build_frame_candidates", "starting")
        duration_value = float(duration) if duration is not None else None
        frame_candidates = build_frame_candidate_index(job_dir, video_path, duration=duration_value)
        write_frame_candidate_index(job_dir, frame_candidates)
        debug_log.event("build_frame_candidates", "succeeded", candidate_count=len(frame_candidates.candidates))

        debug_log.event("build_quality_report", "starting")
        quality_report = build_quality_report(job_dir)
        write_quality_report(job_dir, quality_report)
        debug_log.event("build_quality_report", "succeeded", status=quality_report.status)

        mark_note_review_pending(job_dir)
        store.refresh_artifacts(job_id)
        store.update(job_id, status=JobStatus.awaiting_note_review, step="等待复核笔记", progress=92)
        debug_log.event("await_note_review", "pending")
    except (FFmpegError, LLMError, TranscriptionError, ProcessingError, Exception) as exc:
        debug_log.exception("continue_job_to_notes", "failed", exc)
        store.refresh_artifacts(job_id)
        store.update(job_id, status=JobStatus.failed, step="失败", error=str(exc), progress=100)


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
        # Drop any note artifacts so the job cleanly returns to the subtitle gate.
        for stale in ("note.md", "download.zip", SUBTITLES_PENDING_MARKER, NOTE_REVIEW_PENDING_MARKER):
            stale_path = job_dir / stale
            if stale_path.exists():
                stale_path.unlink()
        note_versions_dir = job_dir / "note_versions"
        if note_versions_dir.exists():
            shutil.rmtree(note_versions_dir, ignore_errors=True)
        frames_dir = job_dir / "frames"
        if frames_dir.exists():
            shutil.rmtree(frames_dir, ignore_errors=True)
        review_dir = job_dir / "review"
        if review_dir.exists():
            shutil.rmtree(review_dir, ignore_errors=True)

        store.update(job_id, status=JobStatus.running, step="字幕生成", progress=30, error="")
        debug_log.event("extract_mp3", "starting", audio_path=str(job_dir / "audio.mp3"))
        audio_path = job_dir / "audio.mp3"
        extract_mp3(video_path, audio_path)
        debug_log.event("extract_mp3", "succeeded", audio_size_bytes=_file_size(audio_path))
        store.refresh_artifacts(job_id)

        debug_log.event("transcribe_audio", "starting", audio_path=str(audio_path))
        transcript_payload = transcribe_audio(
            audio_path,
            config,
            job_dir,
            progress_callback=lambda step, progress: store.update(job_id, step=step, progress=progress),
        )
        transcript_path = job_dir / "transcript.json"
        transcript_path.write_text(
            json.dumps(transcript_payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        segments = transcript_segments_from_payload(transcript_payload)
        if not segments:
            raise ProcessingError("Transcription returned no usable text segments.")
        write_subtitle_files(segments, job_dir)
        duration = probe_duration(video_path)
        write_job_metadata(
            job_id=job_id,
            job_dir=job_dir,
            config=config,
            title=config.original_filename,
            duration=duration,
        )
        (job_dir / SUBTITLES_PENDING_MARKER).write_text("1", encoding="utf-8")
        store.refresh_artifacts(job_id)
        store.update(
            job_id,
            status=JobStatus.awaiting_subtitle_confirmation,
            step="等待确认字幕",
            progress=40,
        )
        debug_log.event("regenerate_subtitles_job", "awaiting_confirmation")
    except (FFmpegError, LLMError, TranscriptionError, ProcessingError, Exception) as exc:
        debug_log.exception("regenerate_subtitles_job", "failed", exc)
        store.refresh_artifacts(job_id)
        store.update(job_id, status=JobStatus.failed, step="失败", error=str(exc), progress=100)


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
        store.update(job_id, status=JobStatus.running, step="重新生成笔记", progress=62, error="")
        debug_log.event("regenerate_note_version", "starting")
        regenerate_note_version(job_dir, config, debug_log=debug_log)
        debug_log.event("regenerate_note_version", "succeeded")
        store.refresh_artifacts(job_id)
        store.update(job_id, step="更新 ZIP", progress=92)
        debug_log.event("create_zip", "starting")
        zip_path = create_zip(job_dir)
        debug_log.event("create_zip", "succeeded", zip_path=str(zip_path), zip_size_bytes=_file_size(zip_path))
        store.refresh_artifacts(job_id)
        store.update(job_id, status=JobStatus.succeeded, step="完成", progress=100)
        debug_log.event("regenerate_note_job", "succeeded")
    except (FFmpegError, LLMError, ProcessingError, Exception) as exc:
        debug_log.exception("regenerate_note_job", "failed", exc)
        store.refresh_artifacts(job_id)
        store.update(job_id, status=JobStatus.failed, step="失败", error=str(exc), progress=100)


def _read_metadata(job_dir: Path) -> dict:
    metadata_path = job_dir / "metadata.json"
    if not metadata_path.exists():
        return {}
    try:
        return json.loads(metadata_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
