from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

from .ffmpeg_tools import FFmpegError, extract_mp3, probe_duration
from .job_store import JobStore
from .llm import LLMError, generate_note_draft
from .models import JobConfig, JobStatus
from .note_versions import (
    create_note_version_from_draft,
    load_note_version_index,
    note_version_index_path,
    regenerate_note_version,
)
from .subtitles import transcript_segments_from_payload, write_subtitle_files
from .transcription import TranscriptionError, transcribe_audio


class ProcessingError(RuntimeError):
    pass


def create_zip(job_dir: Path) -> Path:
    zip_path = job_dir / "download.zip"
    include_names = [
        "note.md",
        "audio.mp3",
        "subtitles.srt",
        "subtitles.vtt",
        "subtitles.md",
        "transcript.json",
        "metadata.json",
    ]
    with ZipFile(zip_path, "w", compression=ZIP_DEFLATED) as archive:
        for name in include_names:
            file_path = job_dir / name
            if file_path.exists():
                archive.write(file_path, arcname=name)
        frames_dir = job_dir / "frames"
        if frames_dir.exists():
            for frame_path in sorted(frames_dir.glob("*.jpg")):
                archive.write(frame_path, arcname=frame_path.relative_to(job_dir).as_posix())
        version_index_path = note_version_index_path(job_dir)
        if version_index_path.exists():
            archive.write(version_index_path, arcname="notes/versions.json")
        version_index = load_note_version_index(job_dir)
        selected_ids = set(version_index.selected_version_ids)
        for version in version_index.versions:
            if version.id not in selected_ids:
                continue
            note_path = job_dir / version.note_path
            if note_path.exists():
                archive.write(note_path, arcname=f"notes/{version.id}/note.md")
            frame_dir = job_dir / version.frame_dir
            if frame_dir.exists():
                for frame_path in sorted(frame_dir.glob("*.jpg")):
                    archive.write(frame_path, arcname=f"notes/{version.id}/frames/{frame_path.name}")
    return zip_path


def process_job(
    *,
    job_id: str,
    job_dir: Path,
    video_path: Path,
    config: JobConfig,
    store: JobStore,
) -> None:
    try:
        store.update(job_id, status=JobStatus.running, step="解析视频", progress=5)
        duration = probe_duration(video_path)

        store.update(job_id, step="音频分离", progress=15)
        audio_path = job_dir / "audio.mp3"
        extract_mp3(video_path, audio_path)
        store.refresh_artifacts(job_id)

        store.update(job_id, step="字幕生成", progress=35)
        transcript_payload = transcribe_audio(
            audio_path,
            config,
            job_dir,
            progress_callback=lambda step, progress: store.update(job_id, step=step, progress=progress),
        )
        (job_dir / "transcript.json").write_text(
            json.dumps(transcript_payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        segments = transcript_segments_from_payload(transcript_payload)
        if not segments:
            raise ProcessingError("Transcription returned no usable text segments.")
        write_subtitle_files(segments, job_dir)
        store.refresh_artifacts(job_id)

        store.update(job_id, step="笔记生成", progress=60)
        draft = generate_note_draft(config, duration, segments)

        store.update(job_id, step="关键帧抽取", progress=78)
        create_note_version_from_draft(
            job_dir=job_dir,
            video_path=video_path,
            draft=draft,
            duration=duration,
            config=config,
            version_id="note_001",
        )
        store.refresh_artifacts(job_id)

        store.update(job_id, step="Markdown 输出", progress=90)
        metadata = {
            "job_id": job_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
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
            "title": draft.title,
        }
        (job_dir / "metadata.json").write_text(
            json.dumps(metadata, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        create_zip(job_dir)
        store.refresh_artifacts(job_id)
        store.update(job_id, status=JobStatus.succeeded, step="完成", progress=100)
    except (FFmpegError, LLMError, TranscriptionError, ProcessingError, Exception) as exc:
        store.refresh_artifacts(job_id)
        store.update(job_id, status=JobStatus.failed, step="失败", error=str(exc), progress=100)


def regenerate_note_job(
    *,
    job_id: str,
    job_dir: Path,
    config: JobConfig,
    store: JobStore,
) -> None:
    try:
        store.update(job_id, status=JobStatus.running, step="重新生成笔记", progress=62, error="")
        regenerate_note_version(job_dir, config)
        store.refresh_artifacts(job_id)
        store.update(job_id, step="更新 ZIP", progress=92)
        create_zip(job_dir)
        store.refresh_artifacts(job_id)
        store.update(job_id, status=JobStatus.succeeded, step="完成", progress=100)
    except (FFmpegError, LLMError, ProcessingError, Exception) as exc:
        store.refresh_artifacts(job_id)
        store.update(job_id, status=JobStatus.failed, step="失败", error=str(exc), progress=100)
