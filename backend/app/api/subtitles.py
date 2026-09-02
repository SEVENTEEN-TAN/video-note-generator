from __future__ import annotations

import shutil
from collections.abc import Callable
from contextlib import AbstractContextManager
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, BackgroundTasks, Form, HTTPException

from ..job_executor import enqueue_serialized
from ..job_paths import InvalidJobIdError, JobDirectoryNotFoundError, read_job_metadata, resolve_job_dir
from ..job_store import JobStore
from ..llm import LLMError
from ..models import (
    AIProtocol,
    JobPublicState,
    JobStatus,
    NoteGenerationConfig,
    NoteLanguage,
    NoteStyle,
    PerformanceMode,
    TranscriptionConfig,
    TranscriptionLanguage,
    TranscriptionMode,
    TranscriptCorrectionApplyRequest,
    TranscriptCorrectionPreview,
    TranscriptCorrectionRequest,
)
from ..operation_leases import assert_current_operation_lease
from ..processor import SUBTITLES_PENDING_MARKER
from ..transcript_corrections import (
    TranscriptCorrectionError,
    apply_pending_transcript_correction,
    create_transcript_correction,
)


JobMutation = Callable[[str], AbstractContextManager[None]]
BuildTranscriptionConfig = Callable[..., TranscriptionConfig]
BuildNoteGenerationConfig = Callable[..., NoteGenerationConfig]
EnsureLocalTranscriptionReady = Callable[[TranscriptionConfig], None]
QueueJobState = Callable[..., JobPublicState]
EnsureJobCanQueue = Callable[[str], JobPublicState]
BackgroundJob = Callable[..., Any]
BackgroundJobGetter = Callable[[], BackgroundJob]


def create_subtitles_router(
    *,
    get_outputs_root: Callable[[], Path],
    get_store: Callable[[], JobStore],
    job_mutation: JobMutation,
    build_transcription_config: BuildTranscriptionConfig,
    build_note_generation_config: BuildNoteGenerationConfig,
    ensure_local_transcription_ready: EnsureLocalTranscriptionReady,
    queue_job_state: QueueJobState,
    ensure_job_can_queue: EnsureJobCanQueue,
    get_continue_job_to_notes: BackgroundJobGetter,
    get_regenerate_subtitles_job: BackgroundJobGetter,
    get_regenerate_note_job: BackgroundJobGetter,
) -> APIRouter:
    router = APIRouter(tags=["subtitles"])

    def current_store() -> JobStore:
        store = get_store()
        store.outputs_root = get_outputs_root()
        return store

    @router.post("/api/jobs/{job_id}/subtitles/confirm")
    def confirm_subtitles(
        job_id: str,
        background_tasks: BackgroundTasks,
        note_language: Annotated[NoteLanguage, Form()],
        note_style: Annotated[NoteStyle, Form()] = NoteStyle.detailed,
        extras: Annotated[str, Form()] = "",
        note_api_key: Annotated[str, Form()] = "",
        note_api_protocol: Annotated[AIProtocol, Form()] = AIProtocol.openai_chat_completions,
        note_base_url: Annotated[str, Form()] = "https://api.openai.com/v1",
        note_model: Annotated[str, Form()] = "gpt-5.5",
        frame_limit: Annotated[int, Form()] = 6,
    ) -> dict:
        store = current_store()
        state = store.get(job_id) or store.load_from_disk(job_id)
        if not state:
            _resolve_job_dir_or_http(get_outputs_root(), job_id)
            raise HTTPException(status_code=404, detail="Job not found.")
        if state.status != JobStatus.awaiting_subtitle_confirmation:
            raise HTTPException(status_code=409, detail="Subtitles are not awaiting confirmation.")
        job_dir = _resolve_job_dir_or_http(get_outputs_root(), job_id)
        if not (job_dir / "transcript.json").exists() or not (job_dir / "source_video").exists():
            raise HTTPException(status_code=400, detail="Transcript or source video is missing.")
        metadata = read_job_metadata(job_dir)
        config = build_note_generation_config(
            note_api_key=note_api_key,
            note_api_protocol=note_api_protocol,
            note_base_url=note_base_url,
            note_model=note_model,
            note_language=note_language,
            note_style=note_style,
            extras=extras,
            frame_limit=frame_limit,
            original_filename=str(metadata.get("original_filename") or "video"),
        )
        with job_mutation(job_id):
            queue_job_state(job_id, step="等待生成笔记", progress=60)
            enqueue_serialized(
                background_tasks,
                get_continue_job_to_notes(),
                job_id=job_id,
                job_dir=job_dir,
                video_path=_job_source_video_path(job_dir),
                config=config,
                store=store,
            )
        return {"job_id": job_id, "status": "queued"}

    @router.post("/api/jobs/{job_id}/subtitles/regenerate")
    def regenerate_subtitles(
        job_id: str,
        background_tasks: BackgroundTasks,
        transcription_mode: Annotated[TranscriptionMode, Form()] = TranscriptionMode.audio_transcriptions,
        transcription_api_key: Annotated[str, Form()] = "",
        transcription_base_url: Annotated[str, Form()] = "https://api.openai.com/v1",
        transcription_model: Annotated[str, Form()] = "whisper-1",
        local_whisper_device: Annotated[str, Form()] = "",
        local_whisper_compute_type: Annotated[str, Form()] = "",
        performance_mode: Annotated[PerformanceMode, Form()] = PerformanceMode.balanced,
        transcription_language: Annotated[TranscriptionLanguage, Form()] = TranscriptionLanguage.auto,
    ) -> dict:
        store = current_store()
        state = store.get(job_id) or store.load_from_disk(job_id)
        if not state:
            _resolve_job_dir_or_http(get_outputs_root(), job_id)
            raise HTTPException(status_code=404, detail="Job not found.")
        if state.status != JobStatus.awaiting_subtitle_confirmation:
            raise HTTPException(status_code=409, detail="Subtitles are not awaiting confirmation.")
        job_dir = _resolve_job_dir_or_http(get_outputs_root(), job_id)
        if not (job_dir / "source_video").exists():
            raise HTTPException(status_code=400, detail="Source video is missing. Subtitles cannot be regenerated.")
        metadata = read_job_metadata(job_dir)
        config = build_transcription_config(
            transcription_mode=transcription_mode,
            transcription_api_key=transcription_api_key,
            transcription_base_url=transcription_base_url,
            transcription_model=transcription_model,
            local_whisper_device=local_whisper_device,
            local_whisper_compute_type=local_whisper_compute_type,
            performance_mode=performance_mode,
            transcription_language=transcription_language,
            original_filename=str(metadata.get("original_filename") or "video"),
        )
        if config.transcription_mode == TranscriptionMode.local_faster_whisper:
            ensure_local_transcription_ready(config)
        with job_mutation(job_id):
            queue_job_state(job_id, step="等待重新生成字幕", progress=20)
            enqueue_serialized(
                background_tasks,
                get_regenerate_subtitles_job(),
                job_id=job_id,
                job_dir=job_dir,
                video_path=_job_source_video_path(job_dir),
                config=config,
                store=store,
            )
        return {"job_id": job_id, "status": "queued"}

    @router.post("/api/jobs/{job_id}/transcript-corrections", response_model=TranscriptCorrectionPreview)
    def create_transcript_correction_endpoint(
        job_id: str,
        request: TranscriptCorrectionRequest,
    ) -> TranscriptCorrectionPreview:
        job_dir = _resolve_job_dir_or_http(get_outputs_root(), job_id)
        metadata = read_job_metadata(job_dir)
        try:
            note_language = NoteLanguage(str(metadata.get("note_language") or "zh"))
        except ValueError:
            note_language = NoteLanguage.zh
        try:
            note_style = NoteStyle(str(metadata.get("note_style") or "detailed"))
        except ValueError:
            note_style = NoteStyle.detailed
        config = build_note_generation_config(
            note_api_key=request.note_api_key,
            note_api_protocol=request.note_api_protocol,
            note_base_url=request.note_base_url,
            note_model=request.note_model,
            note_language=note_language,
            note_style=note_style,
            extras="",
            frame_limit=int(metadata.get("frame_limit") or 6),
            original_filename=str(metadata.get("original_filename") or "video"),
        )
        with job_mutation(job_id):
            try:
                preview = create_transcript_correction(job_dir, config, request.instructions)
                return preview.model_copy(update={"job_id": job_id})
            except (LLMError, TranscriptCorrectionError, FileNotFoundError, ValueError) as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/api/jobs/{job_id}/transcript-corrections/apply")
    def apply_transcript_correction_endpoint(
        job_id: str,
        request: TranscriptCorrectionApplyRequest,
        background_tasks: BackgroundTasks,
    ) -> dict:
        store = current_store()
        job_dir = _resolve_job_dir_or_http(get_outputs_root(), job_id)
        if not (job_dir / "source_video").exists():
            raise HTTPException(status_code=400, detail="Source video is missing. This job cannot regenerate frames.")
        with job_mutation(job_id):
            ensure_job_can_queue(job_id)
            try:
                apply_pending_transcript_correction(job_dir)
            except (TranscriptCorrectionError, FileNotFoundError, ValueError) as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            assert_current_operation_lease()
            (job_dir / SUBTITLES_PENDING_MARKER).unlink(missing_ok=True)
            stale_note_chunks = job_dir / "note_chunks"
            if stale_note_chunks.exists():
                shutil.rmtree(stale_note_chunks)

            metadata = read_job_metadata(job_dir)
            config = build_note_generation_config(
                note_api_key=request.note_api_key,
                note_api_protocol=request.note_api_protocol,
                note_base_url=request.note_base_url,
                note_model=request.note_model,
                note_language=request.note_language,
                note_style=request.note_style,
                extras=request.extras,
                frame_limit=request.frame_limit,
                original_filename=str(metadata.get("original_filename") or "video"),
            )
            queue_job_state(job_id, step="等待重新生成笔记", progress=62)
            enqueue_serialized(
                background_tasks,
                get_regenerate_note_job(),
                job_id=job_id,
                job_dir=job_dir,
                config=config,
                store=store,
            )
            store.refresh_artifacts(job_id)
        return {"job_id": job_id, "status": "queued"}

    return router


def _resolve_job_dir_or_http(outputs_root: Path, job_id: str) -> Path:
    try:
        return resolve_job_dir(outputs_root, job_id)
    except InvalidJobIdError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except JobDirectoryNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


def _job_source_video_path(job_dir: Path) -> Path:
    source_dir = job_dir / "source_video"
    candidates = sorted(source_dir.glob("input.*")) if source_dir.exists() else []
    return candidates[0] if candidates else source_dir / "input.mp4"
