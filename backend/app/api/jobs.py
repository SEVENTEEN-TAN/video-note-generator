from __future__ import annotations

import errno
import shutil
import uuid
from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import asdict
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, BackgroundTasks, File, Form, HTTPException, Query, UploadFile
from pydantic import ValidationError

from ..filenames import normalize_uploaded_filename
from ..job_paths import InvalidJobIdError, JobDirectoryNotFoundError, read_job_metadata, resolve_job_dir
from ..job_activity import load_job_activity
from ..job_store import JobStore
from ..models import (
    AIProtocol,
    FrameSuggestion,
    JobHistory,
    JobActivitySnapshot,
    JobInputConfig,
    JobPublicState,
    JobStatus,
    NoteGenerationConfig,
    NoteLanguage,
    NotePreferences,
    NoteStyle,
    PerformanceMode,
    TranscriptionConfig,
    TranscriptionLanguage,
    TranscriptionMode,
)
from ..note_versions import find_source_video
from ..operation_leases import assert_current_operation_lease
from ..processor import write_job_metadata
from ..storage_policy import available_storage_bytes, cleanup_transcription_cache, job_storage_usage
from ..subtitles import transcript_segments_from_payload
from ..task_debug_log import TaskDebugLog
from ..transcription import TranscriptionError, has_active_external_worker
from ..upload_limits import UploadLimits, UploadTooLargeError, copy_upload_stream


JobMutation = Callable[[str], AbstractContextManager[None]]
BuildTranscriptionConfig = Callable[..., TranscriptionConfig]
BuildNotePreferences = Callable[..., NotePreferences]
BuildNoteGenerationConfig = Callable[..., NoteGenerationConfig]
EnsureLocalTranscriptionReady = Callable[[TranscriptionConfig], None]
ValidateUploads = Callable[[UploadFile, UploadFile | None], UploadLimits]
BackgroundJob = Callable[..., Any]
CallableGetter = Callable[[], Callable[..., Any]]


def create_jobs_router(
    *,
    get_outputs_root: Callable[[], Path],
    get_store: Callable[[], JobStore],
    job_mutation: JobMutation,
    validate_video_extension: Callable[[str | None], str],
    validate_subtitle_extension: Callable[[str | None], str],
    build_transcription_config: BuildTranscriptionConfig,
    build_note_preferences: BuildNotePreferences,
    build_note_generation_config: BuildNoteGenerationConfig,
    validate_uploads: ValidateUploads,
    queue_job_state: Callable[..., JobPublicState],
    get_ensure_local_transcription_ready: Callable[[], EnsureLocalTranscriptionReady],
    get_enqueue_serialized: CallableGetter,
    get_process_uploaded_subtitle_job: CallableGetter,
    get_process_transcription_job: CallableGetter,
    get_probe_duration: CallableGetter,
    get_extract_mp3: CallableGetter,
    get_transcribe_audio: CallableGetter,
    get_generate_note_draft: CallableGetter,
) -> APIRouter:
    router = APIRouter(tags=["jobs"])

    def current_store() -> JobStore:
        store = get_store()
        store.outputs_root = get_outputs_root()
        return store

    @router.post("/api/jobs/frame-suggestion", response_model=FrameSuggestion)
    async def suggest_frame_count(
        video: Annotated[UploadFile, File()],
        note_language: Annotated[NoteLanguage, Form()],
        note_style: Annotated[NoteStyle, Form()] = NoteStyle.detailed,
        extras: Annotated[str, Form()] = "",
        transcription_mode: Annotated[TranscriptionMode, Form()] = TranscriptionMode.audio_transcriptions,
        transcription_api_key: Annotated[str, Form()] = "",
        transcription_base_url: Annotated[str, Form()] = "https://api.openai.com/v1",
        transcription_model: Annotated[str, Form()] = "whisper-1",
        local_whisper_device: Annotated[str, Form()] = "",
        local_whisper_compute_type: Annotated[str, Form()] = "",
        performance_mode: Annotated[PerformanceMode, Form()] = PerformanceMode.balanced,
        transcription_language: Annotated[TranscriptionLanguage, Form()] = TranscriptionLanguage.auto,
        note_api_key: Annotated[str, Form()] = "",
        note_api_protocol: Annotated[AIProtocol, Form()] = AIProtocol.openai_chat_completions,
        note_base_url: Annotated[str, Form()] = "https://api.openai.com/v1",
        note_model: Annotated[str, Form()] = "gpt-5.5",
    ) -> FrameSuggestion:
        suffix = validate_video_extension(video.filename)
        original_filename = normalize_uploaded_filename(video.filename or f"input{suffix}")
        transcription_config = build_transcription_config(
            transcription_mode=transcription_mode,
            transcription_api_key=transcription_api_key,
            transcription_base_url=transcription_base_url,
            transcription_model=transcription_model,
            local_whisper_device=local_whisper_device,
            local_whisper_compute_type=local_whisper_compute_type,
            performance_mode=performance_mode,
            transcription_language=transcription_language,
            original_filename=original_filename,
        )
        note_config = build_note_generation_config(
            note_api_key=note_api_key,
            note_api_protocol=note_api_protocol,
            note_base_url=note_base_url,
            note_model=note_model,
            note_language=note_language,
            note_style=note_style,
            extras=extras,
            frame_limit=24,
            original_filename=original_filename,
        )
        get_ensure_local_transcription_ready()(transcription_config)
        upload_limits = validate_uploads(video, None)

        temp_dir = get_outputs_root() / ".frame-suggestions" / uuid.uuid4().hex
        source_dir = temp_dir / "source_video"
        source_dir.mkdir(parents=True, exist_ok=True)
        video_path = source_dir / f"input{suffix}"
        try:
            with video_path.open("wb") as target:
                copy_upload_stream(
                    video.file,
                    target,
                    max_bytes=upload_limits.max_video_bytes,
                    label="Video",
                )
            duration = get_probe_duration()(video_path)
            audio_path = temp_dir / "audio.mp3"
            get_extract_mp3()(video_path, audio_path)
            transcript_payload = get_transcribe_audio()(audio_path, transcription_config, temp_dir)
            segments = transcript_segments_from_payload(transcript_payload)
            if not segments:
                raise HTTPException(status_code=400, detail="Transcription returned no usable text segments.")
            draft = get_generate_note_draft()(note_config, duration, segments)
            return FrameSuggestion(
                recommended_frame_count=draft.recommended_frame_count or min(max(len(draft.key_moments), 1), 24),
                candidate_count=len(draft.key_moments),
                reasons=[moment.reason for moment in draft.key_moments[:3]],
            )
        except HTTPException:
            raise
        except UploadTooLargeError as exc:
            raise HTTPException(status_code=413, detail=str(exc)) from exc
        except OSError as exc:
            status_code = 507 if exc.errno == errno.ENOSPC else 400
            detail = "Insufficient disk space while writing upload." if status_code == 507 else str(exc)
            raise HTTPException(status_code=status_code, detail=detail) from exc
        except (TranscriptionError, Exception) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    @router.post("/api/jobs")
    async def create_job(
        background_tasks: BackgroundTasks,
        video: Annotated[UploadFile, File()],
        note_language: Annotated[NoteLanguage, Form()],
        subtitle: Annotated[UploadFile | None, File()] = None,
        note_style: Annotated[NoteStyle, Form()] = NoteStyle.detailed,
        extras: Annotated[str, Form()] = "",
        transcription_mode: Annotated[TranscriptionMode, Form()] = TranscriptionMode.audio_transcriptions,
        transcription_api_key: Annotated[str, Form()] = "",
        transcription_base_url: Annotated[str, Form()] = "https://api.openai.com/v1",
        transcription_model: Annotated[str, Form()] = "whisper-1",
        local_whisper_device: Annotated[str, Form()] = "",
        local_whisper_compute_type: Annotated[str, Form()] = "",
        performance_mode: Annotated[PerformanceMode, Form()] = PerformanceMode.balanced,
        transcription_language: Annotated[TranscriptionLanguage, Form()] = TranscriptionLanguage.auto,
        note_api_protocol: Annotated[AIProtocol, Form()] = AIProtocol.openai_chat_completions,
        note_base_url: Annotated[str, Form()] = "https://api.openai.com/v1",
        note_model: Annotated[str, Form()] = "gpt-5.5",
        frame_limit: Annotated[int, Form()] = 6,
    ) -> dict:
        suffix = validate_video_extension(video.filename)
        has_uploaded_subtitle = bool(subtitle and subtitle.filename)
        subtitle_suffix = validate_subtitle_extension(subtitle.filename) if has_uploaded_subtitle and subtitle else ""
        uploaded_subtitle_filename = (
            normalize_uploaded_filename(subtitle.filename, fallback="subtitles.srt")
            if has_uploaded_subtitle and subtitle
            else ""
        )
        original_filename = normalize_uploaded_filename(video.filename or f"input{suffix}")
        input_config = JobInputConfig(original_filename=original_filename)
        note_preferences = build_note_preferences(
            note_api_protocol=note_api_protocol,
            note_base_url=note_base_url,
            note_model=note_model,
            note_language=note_language,
            note_style=note_style,
            extras=extras,
            frame_limit=frame_limit,
            original_filename=original_filename,
        )
        transcription_config = (
            None
            if has_uploaded_subtitle
            else build_transcription_config(
                transcription_mode=transcription_mode,
                transcription_api_key=transcription_api_key,
                transcription_base_url=transcription_base_url,
                transcription_model=transcription_model,
                local_whisper_device=local_whisper_device,
                local_whisper_compute_type=local_whisper_compute_type,
                performance_mode=performance_mode,
                transcription_language=transcription_language,
                original_filename=original_filename,
            )
        )
        if transcription_config is not None:
            get_ensure_local_transcription_ready()(transcription_config)
        upload_limits = validate_uploads(video, subtitle if has_uploaded_subtitle else None)

        job_id = uuid.uuid4().hex
        job_dir = get_outputs_root() / job_id
        source_dir = job_dir / "source_video"
        video_path = source_dir / f"input{suffix}"
        subtitle_path = job_dir / "source_subtitles" / f"input{subtitle_suffix}" if has_uploaded_subtitle else None
        try:
            source_dir.mkdir(parents=True, exist_ok=True)
            with video_path.open("wb") as target:
                copy_upload_stream(
                    video.file,
                    target,
                    max_bytes=upload_limits.max_video_bytes,
                    label="Video",
                )
            if has_uploaded_subtitle and subtitle and subtitle_path:
                subtitle_path.parent.mkdir(parents=True, exist_ok=True)
                with subtitle_path.open("wb") as target:
                    copy_upload_stream(
                        subtitle.file,
                        target,
                        max_bytes=upload_limits.max_subtitle_bytes,
                        label="Subtitle",
                    )
            write_job_metadata(
                job_id=job_id,
                job_dir=job_dir,
                input_config=input_config,
                transcription_config=transcription_config,
                note_config=note_preferences,
                title=input_config.original_filename,
                duration=None,
                subtitle_source="uploaded" if has_uploaded_subtitle else "transcribed",
                uploaded_subtitle_filename=uploaded_subtitle_filename,
            )
            TaskDebugLog(job_dir).event(
                "create_job",
                "job files created",
                job_id=job_id,
                original_filename=input_config.original_filename,
                video_path=str(video_path),
                video_size_bytes=video_path.stat().st_size,
                subtitle_path=str(subtitle_path) if subtitle_path else "",
                subtitle_size_bytes=subtitle_path.stat().st_size if subtitle_path and subtitle_path.exists() else None,
                uploaded_subtitle_filename=uploaded_subtitle_filename,
                transcription_mode=(
                    transcription_config.transcription_mode.value
                    if transcription_config is not None
                    else "uploaded_subtitle"
                ),
                transcription_model=transcription_config.transcription_model if transcription_config is not None else "",
                note_model=note_preferences.note_model,
                note_api_protocol=note_preferences.note_api_protocol.value,
                note_base_url=note_preferences.note_base_url,
                frame_limit=note_preferences.frame_limit,
            )
        except UploadTooLargeError as exc:
            shutil.rmtree(job_dir, ignore_errors=True)
            raise HTTPException(status_code=413, detail=str(exc)) from exc
        except OSError as exc:
            shutil.rmtree(job_dir, ignore_errors=True)
            status_code = 507 if exc.errno == errno.ENOSPC else 400
            detail = "Insufficient disk space while writing upload." if status_code == 507 else f"Cannot create job files: {exc}"
            raise HTTPException(status_code=status_code, detail=detail) from exc
        store = current_store()
        store.create(job_id)
        if has_uploaded_subtitle and subtitle_path:
            get_enqueue_serialized()(
                background_tasks,
                get_process_uploaded_subtitle_job(),
                job_id=job_id,
                job_dir=job_dir,
                video_path=video_path,
                subtitle_path=subtitle_path,
                uploaded_subtitle_filename=uploaded_subtitle_filename,
                config=input_config,
                store=store,
            )
        else:
            if transcription_config is None:
                raise HTTPException(status_code=500, detail="Transcription configuration was not created.")
            get_enqueue_serialized()(
                background_tasks,
                get_process_transcription_job(),
                job_id=job_id,
                job_dir=job_dir,
                video_path=video_path,
                config=transcription_config,
                store=store,
            )
        return {"job_id": job_id}

    @router.get("/api/jobs", response_model=JobHistory)
    def list_jobs() -> JobHistory:
        return JobHistory(jobs=current_store().list_history())

    @router.get("/api/jobs/{job_id}", response_model=JobPublicState)
    def get_job(job_id: str) -> JobPublicState:
        store = current_store()
        state = store.get(job_id)
        if not state:
            _resolve_job_dir_or_http(get_outputs_root(), job_id)
            state = store.load_from_disk(job_id)
        if not state:
            raise HTTPException(status_code=404, detail="Job not found.")
        store.refresh_artifacts(job_id)
        return state

    @router.get("/api/jobs/{job_id}/activity", response_model=JobActivitySnapshot)
    def get_job_activity(job_id: str, limit: int = Query(default=8, ge=1, le=20)) -> JobActivitySnapshot:
        job_dir = _resolve_job_dir_or_http(get_outputs_root(), job_id)
        return load_job_activity(job_dir, limit=limit)

    @router.post("/api/jobs/{job_id}/cancel", response_model=JobPublicState)
    def cancel_job(job_id: str) -> JobPublicState:
        store = current_store()
        state = store.get(job_id) or store.load_from_disk(job_id)
        if state is None:
            raise HTTPException(status_code=404, detail="Job not found.")
        if state.status in {JobStatus.cancelling, JobStatus.cancelled}:
            return state
        if state.status not in {JobStatus.pending, JobStatus.running}:
            raise HTTPException(status_code=409, detail="Only pending or running jobs can be cancelled.")
        cancellation = store.request_cancel(job_id)
        if cancellation is None:
            raise HTTPException(status_code=404, detail="Job not found.")
        TaskDebugLog(get_outputs_root() / job_id).event("cancel_job", "cancel_requested")
        store.refresh_artifacts(job_id)
        return store.get(job_id) or cancellation

    @router.post("/api/jobs/{job_id}/transcription/resume")
    def resume_transcription(job_id: str, background_tasks: BackgroundTasks) -> dict:
        store = current_store()
        state = store.get(job_id) or store.load_from_disk(job_id)
        if state is None:
            raise HTTPException(status_code=404, detail="Job not found.")
        if state.status in {JobStatus.pending, JobStatus.running, JobStatus.cancelling}:
            raise HTTPException(status_code=409, detail="Job is already queued or running.")
        if state.status not in {JobStatus.cancelled, JobStatus.failed}:
            raise HTTPException(status_code=409, detail="Only cancelled or interrupted transcriptions can resume.")
        job_dir = _resolve_job_dir_or_http(get_outputs_root(), job_id)
        metadata = read_job_metadata(job_dir)
        if metadata.get("transcription_mode") != TranscriptionMode.local_faster_whisper.value:
            raise HTTPException(status_code=409, detail="Only local Faster Whisper transcriptions can resume.")
        if has_active_external_worker(job_dir):
            raise HTTPException(status_code=409, detail="The previous local transcription worker is still shutting down.")
        video_path = find_source_video(job_dir)
        if video_path is None or not video_path.exists():
            raise HTTPException(status_code=400, detail="Source video is missing.")
        try:
            config = TranscriptionConfig(
                transcription_mode=TranscriptionMode.local_faster_whisper,
                transcription_api_key="",
                transcription_base_url=str(metadata.get("transcription_base_url") or "https://api.openai.com/v1"),
                transcription_model=str(metadata.get("transcription_model") or "small"),
                local_whisper_device=str(metadata.get("local_whisper_device") or ""),
                local_whisper_compute_type=str(metadata.get("local_whisper_compute_type") or ""),
                performance_mode=metadata.get("performance_mode") or PerformanceMode.balanced.value,
                transcription_language=metadata.get("transcription_language") or TranscriptionLanguage.auto.value,
                original_filename=str(metadata.get("original_filename") or video_path.name),
            )
        except (TypeError, ValueError, ValidationError) as exc:
            raise HTTPException(status_code=400, detail=f"Saved transcription settings are invalid: {exc}") from exc
        get_ensure_local_transcription_ready()(config)
        with job_mutation(job_id):
            queue_job_state(job_id, step="等待继续转写", progress=min(state.progress, 39))
            get_enqueue_serialized()(
                background_tasks,
                get_process_transcription_job(),
                job_id=job_id,
                job_dir=job_dir,
                video_path=video_path,
                config=config,
                store=store,
            )
        TaskDebugLog(job_dir).event("resume_transcription", "queued")
        return {"job_id": job_id, "resumed": True}

    @router.get("/api/jobs/{job_id}/storage")
    def get_job_storage(job_id: str) -> dict:
        current_store()
        job_dir = _resolve_job_dir_or_http(get_outputs_root(), job_id)
        usage = job_storage_usage(job_dir)
        return {"job_id": job_id, **asdict(usage), "available_bytes": available_storage_bytes(job_dir)}

    @router.delete("/api/jobs/{job_id}/transcription/cache")
    def delete_transcription_cache(job_id: str) -> dict:
        store = current_store()
        with job_mutation(job_id):
            state = store.get(job_id) or store.load_from_disk(job_id)
            if state is None:
                raise HTTPException(status_code=404, detail="Job not found.")
            if state.status in {JobStatus.pending, JobStatus.running, JobStatus.cancelling}:
                raise HTTPException(status_code=409, detail="Cannot clean transcription cache while the job is active.")
            job_dir = _resolve_job_dir_or_http(get_outputs_root(), job_id)
            if has_active_external_worker(job_dir):
                raise HTTPException(status_code=409, detail="Cannot clean cache while an external worker is still shutting down.")
            assert_current_operation_lease()
            freed_bytes = cleanup_transcription_cache(job_dir)
            if state.work_progress is not None:
                store.update(
                    job_id,
                    work_progress=state.work_progress.model_copy(
                        update={"resumable": False, "cache_hits": 0},
                        deep=True,
                    ),
                )
            TaskDebugLog(job_dir).event("cleanup_transcription_cache", "succeeded", freed_bytes=freed_bytes)
            return {"job_id": job_id, "freed_bytes": freed_bytes}

    @router.delete("/api/jobs/{job_id}")
    def delete_job(job_id: str) -> dict:
        store = current_store()
        with job_mutation(job_id):
            state = store.get(job_id)
            if state and state.status in {JobStatus.pending, JobStatus.running, JobStatus.cancelling}:
                raise HTTPException(status_code=409, detail="Cannot delete a running job.")
            job_dir = _resolve_job_dir_or_http(get_outputs_root(), job_id)
            try:
                assert_current_operation_lease()
                shutil.rmtree(job_dir)
            except PermissionError as exc:
                raise HTTPException(status_code=409, detail=f"Cannot delete job because files are in use: {exc}") from exc
            except OSError as exc:
                raise HTTPException(status_code=409, detail=f"Cannot delete job files: {exc}") from exc
            store.remove(job_id)
            return {"ok": True}

    return router


def _resolve_job_dir_or_http(outputs_root: Path, job_id: str) -> Path:
    try:
        return resolve_job_dir(outputs_root, job_id)
    except InvalidJobIdError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except JobDirectoryNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
