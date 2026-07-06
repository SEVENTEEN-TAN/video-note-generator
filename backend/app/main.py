from __future__ import annotations

import shutil
import uuid
from pathlib import Path
from typing import Annotated

import json

from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError

from .job_store import JobStore
from .cuda_dependencies import (
    CudaDependencyInstallState,
    get_cuda_dependency_install_state,
    run_cuda_dependency_install,
    start_cuda_dependency_install,
)
from .ffmpeg_tools import extract_mp3, probe_duration
from .filenames import normalize_uploaded_filename
from .frame_candidates import (
    build_frame_candidate_index,
    load_frame_candidate_index,
    reject_frame_candidate,
    select_frame_candidate,
    write_frame_candidate_index,
)
from .llm import LLMError, generate_note_draft
from .local_dependencies import (
    LocalTranscriptionDependencyInstallState,
    get_local_dependency_install_state,
    run_local_dependency_install,
    start_local_dependency_install,
)
from .model_downloads import (
    ModelDownloadRequest,
    ModelDownloadState,
    get_model_download_state,
    run_model_download,
    start_model_download,
)
from .models import (
    FrameCandidateIndex,
    FrameSuggestion,
    JobConfig,
    JobHistory,
    JobPublicState,
    JobStatus,
    NoteLanguage,
    NoteStyle,
    QualityReport,
    ReviewDraft,
    ReviewDraftParagraphUpdate,
    TranscriptionLanguage,
    NoteVersionIndex,
    NoteVersionSelection,
    TranscriptionMode,
    TranscriptCorrectionApplyRequest,
    TranscriptCorrectionPreview,
    TranscriptCorrectionRequest,
)
from .note_chunks import (
    load_note_chunk_index,
    load_chunk_draft,
    regenerate_chunk_and_reduce,
)
from .note_versions import (
    activate_note_version,
    create_note_version_from_draft,
    find_source_video,
    get_note_version,
    load_note_version_index,
    set_note_version_selection,
)
from .processor import (
    continue_job_to_notes,
    create_zip,
    process_transcription_job,
    regenerate_note_job,
    regenerate_subtitles_job,
    write_job_metadata,
)
from .runtime_status import get_runtime_status
from .runtime_paths import get_frontend_dist_dir, get_outputs_root
from .review_quality import build_quality_report, write_quality_report
from .review_finalization import finalize_reviewed_note, is_note_review_pending, mark_note_review_pending
from .review_drafts import get_or_build_review_draft, update_review_draft_paragraph
from .settings import UserSettings, UserSettingsUpdate, clear_user_settings, load_user_settings, save_user_settings
from .subtitles import transcript_segments_from_payload
from .task_debug_log import TaskDebugLog
from .transcript_corrections import TranscriptCorrectionError, apply_pending_transcript_correction, create_transcript_correction
from .transcription import TranscriptionError, get_faster_whisper_model_root, resolve_local_faster_whisper_model, transcribe_audio

OUTPUTS_ROOT = get_outputs_root()
OUTPUTS_ROOT.mkdir(parents=True, exist_ok=True)

ALLOWED_EXTENSIONS = {".mp4", ".mov", ".mkv", ".webm", ".avi"}

app = FastAPI(title="Video Note Generator MVP")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:5173", "http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
store = JobStore(OUTPUTS_ROOT)


@app.get("/api/ready")
def ready() -> dict:
    return {"ok": True}


@app.get("/api/health")
def health() -> dict:
    runtime = get_runtime_status()
    return {
        "ok": True,
        "runtime_ok": runtime["ok"],
        "ffmpeg_available": runtime["ffmpeg"]["available"],
        "ffmpeg_path": runtime["ffmpeg"]["path"],
        "runtime": runtime,
    }


@app.get("/api/runtime")
def runtime() -> dict:
    return get_runtime_status()


@app.post("/api/runtime/cuda-dependencies/install", response_model=CudaDependencyInstallState)
def install_cuda_dependencies(background_tasks: BackgroundTasks) -> CudaDependencyInstallState:
    state, should_enqueue = start_cuda_dependency_install()
    if should_enqueue:
        background_tasks.add_task(run_cuda_dependency_install)
    return state


@app.get("/api/runtime/cuda-dependencies/install", response_model=CudaDependencyInstallState)
def get_cuda_dependency_install() -> CudaDependencyInstallState:
    return get_cuda_dependency_install_state()


@app.post("/api/runtime/local-dependencies/install", response_model=LocalTranscriptionDependencyInstallState)
def install_local_dependencies(background_tasks: BackgroundTasks) -> LocalTranscriptionDependencyInstallState:
    state, should_enqueue = start_local_dependency_install()
    if should_enqueue:
        background_tasks.add_task(run_local_dependency_install)
    return state


@app.get("/api/runtime/local-dependencies/install", response_model=LocalTranscriptionDependencyInstallState)
def get_local_dependency_install() -> LocalTranscriptionDependencyInstallState:
    return get_local_dependency_install_state()


@app.get("/api/settings", response_model=UserSettings)
def get_settings() -> UserSettings:
    return load_user_settings()


@app.patch("/api/settings", response_model=UserSettings)
def update_settings(update: UserSettingsUpdate) -> UserSettings:
    return save_user_settings(update.model_dump(mode="json", exclude_none=True))


@app.delete("/api/settings", response_model=UserSettings)
def delete_settings() -> UserSettings:
    return clear_user_settings()


@app.post("/api/models/faster-whisper/download", response_model=ModelDownloadState)
def download_faster_whisper_model_endpoint(
    request: ModelDownloadRequest,
    background_tasks: BackgroundTasks,
) -> ModelDownloadState:
    state = start_model_download(request.model_name)
    if state.status == "pending":
        background_tasks.add_task(run_model_download, request.model_name)
    return state


@app.get("/api/models/faster-whisper/download/{model_name}", response_model=ModelDownloadState)
def get_faster_whisper_model_download(model_name: str) -> ModelDownloadState:
    return get_model_download_state(model_name)


def validate_video_extension(filename: str | None) -> str:
    suffix = Path(filename or "").suffix.lower()
    if suffix not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported video format. Use one of: {', '.join(sorted(ALLOWED_EXTENSIONS))}.",
        )
    return suffix


def build_job_config_or_400(
    *,
    transcription_mode: TranscriptionMode,
    transcription_api_key: str,
    transcription_base_url: str,
    transcription_model: str,
    local_whisper_device: str,
    local_whisper_compute_type: str,
    transcription_language: TranscriptionLanguage = TranscriptionLanguage.auto,
    note_api_key: str = "",
    note_base_url: str = "https://api.openai.com/v1",
    note_model: str = "gpt-5.5",
    note_language: NoteLanguage = NoteLanguage.zh,
    note_style: NoteStyle = NoteStyle.detailed,
    extras: str = "",
    frame_limit: int = 6,
    original_filename: str = "video",
) -> JobConfig:
    uses_remote_transcription = transcription_mode != TranscriptionMode.local_faster_whisper
    if uses_remote_transcription and not transcription_api_key.strip():
        raise HTTPException(status_code=400, detail="Transcription API Key is required.")
    if uses_remote_transcription and not transcription_base_url.strip():
        raise HTTPException(status_code=400, detail="Transcription Base URL is required.")
    if not note_api_key.strip():
        raise HTTPException(status_code=400, detail="Note API Key is required.")
    if not transcription_model.strip():
        raise HTTPException(status_code=400, detail="Transcription model is required.")
    if not note_model.strip():
        raise HTTPException(status_code=400, detail="Note model is required.")
    if frame_limit < 1 or frame_limit > 24:
        raise HTTPException(status_code=400, detail="frame_limit must be between 1 and 24.")

    try:
        return JobConfig(
            transcription_mode=transcription_mode,
            transcription_api_key=transcription_api_key,
            transcription_base_url=transcription_base_url,
            transcription_model=transcription_model,
            local_whisper_device=local_whisper_device,
            local_whisper_compute_type=local_whisper_compute_type,
            transcription_language=transcription_language,
            note_api_key=note_api_key,
            note_base_url=note_base_url,
            note_model=note_model,
            note_language=note_language,
            note_style=note_style,
            extras=extras,
            frame_limit=frame_limit,
            original_filename=normalize_uploaded_filename(original_filename),
        )
    except ValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def ensure_local_cuda_ready(config: JobConfig) -> None:
    if config.transcription_mode != TranscriptionMode.local_faster_whisper:
        return
    if str(config.local_whisper_device or "").strip() != "cuda":
        return

    runtime = get_runtime_status()
    faster_whisper = runtime.get("faster_whisper", {})
    if faster_whisper.get("ready_for_cuda"):
        return

    detail = (
        faster_whisper.get("cuda_runtime_hint")
        or faster_whisper.get("cuda_error")
        or "CUDA runtime is not ready. Install CUDA dependencies or switch local transcription to CPU."
    )
    raise HTTPException(status_code=400, detail=f"CUDA 未就绪：{detail}")


def ensure_local_transcription_ready(config: JobConfig) -> None:
    if config.transcription_mode != TranscriptionMode.local_faster_whisper:
        return
    try:
        resolve_local_faster_whisper_model(config.transcription_model, get_faster_whisper_model_root())
    except TranscriptionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    ensure_local_cuda_ready(config)


@app.post("/api/jobs/frame-suggestion", response_model=FrameSuggestion)
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
    transcription_language: Annotated[TranscriptionLanguage, Form()] = TranscriptionLanguage.auto,
    note_api_key: Annotated[str, Form()] = "",
    note_base_url: Annotated[str, Form()] = "https://api.openai.com/v1",
    note_model: Annotated[str, Form()] = "gpt-5.5",
) -> FrameSuggestion:
    suffix = validate_video_extension(video.filename)
    config = build_job_config_or_400(
        transcription_mode=transcription_mode,
        transcription_api_key=transcription_api_key,
        transcription_base_url=transcription_base_url,
        transcription_model=transcription_model,
        local_whisper_device=local_whisper_device,
        local_whisper_compute_type=local_whisper_compute_type,
        transcription_language=transcription_language,
        note_api_key=note_api_key,
        note_base_url=note_base_url,
        note_model=note_model,
        note_language=note_language,
        note_style=note_style,
        extras=extras,
        frame_limit=24,
        original_filename=video.filename or f"input{suffix}",
    )
    ensure_local_transcription_ready(config)

    temp_dir = OUTPUTS_ROOT / ".frame-suggestions" / uuid.uuid4().hex
    source_dir = temp_dir / "source_video"
    source_dir.mkdir(parents=True, exist_ok=True)
    video_path = source_dir / f"input{suffix}"
    try:
        with video_path.open("wb") as target:
            shutil.copyfileobj(video.file, target)

        duration = probe_duration(video_path)
        audio_path = temp_dir / "audio.mp3"
        extract_mp3(video_path, audio_path)
        transcript_payload = transcribe_audio(audio_path, config, temp_dir)
        segments = transcript_segments_from_payload(transcript_payload)
        if not segments:
            raise HTTPException(status_code=400, detail="Transcription returned no usable text segments.")
        draft = generate_note_draft(config, duration, segments)
        return FrameSuggestion(
            recommended_frame_count=draft.recommended_frame_count or min(max(len(draft.key_moments), 1), 24),
            candidate_count=len(draft.key_moments),
            reasons=[moment.reason for moment in draft.key_moments[:3]],
        )
    except HTTPException:
        raise
    except (OSError, TranscriptionError, Exception) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


@app.post("/api/jobs")
async def create_job(
    background_tasks: BackgroundTasks,
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
    transcription_language: Annotated[TranscriptionLanguage, Form()] = TranscriptionLanguage.auto,
    note_api_key: Annotated[str, Form()] = "",
    note_base_url: Annotated[str, Form()] = "https://api.openai.com/v1",
    note_model: Annotated[str, Form()] = "gpt-5.5",
    frame_limit: Annotated[int, Form()] = 6,
) -> dict:
    suffix = validate_video_extension(video.filename)
    config = build_job_config_or_400(
        transcription_mode=transcription_mode,
        transcription_api_key=transcription_api_key,
        transcription_base_url=transcription_base_url,
        transcription_model=transcription_model,
        local_whisper_device=local_whisper_device,
        local_whisper_compute_type=local_whisper_compute_type,
        transcription_language=transcription_language,
        note_api_key=note_api_key,
        note_base_url=note_base_url,
        note_model=note_model,
        note_language=note_language,
        note_style=note_style,
        extras=extras,
        frame_limit=frame_limit,
        original_filename=video.filename or f"input{suffix}",
    )
    ensure_local_transcription_ready(config)

    job_id = uuid.uuid4().hex
    job_dir = OUTPUTS_ROOT / job_id
    source_dir = job_dir / "source_video"
    video_path = source_dir / f"input{suffix}"
    try:
        source_dir.mkdir(parents=True, exist_ok=True)
        with video_path.open("wb") as target:
            shutil.copyfileobj(video.file, target)
        write_job_metadata(
            job_id=job_id,
            job_dir=job_dir,
            config=config,
            title=config.original_filename,
            duration=None,
        )
        TaskDebugLog(job_dir).event(
            "create_job",
            "job files created",
            job_id=job_id,
            original_filename=config.original_filename,
            video_path=str(video_path),
            video_size_bytes=video_path.stat().st_size,
            transcription_mode=config.transcription_mode.value,
            transcription_model=config.transcription_model,
            note_model=config.note_model,
            note_base_url=config.note_base_url,
            frame_limit=config.frame_limit,
        )
    except OSError as exc:
        shutil.rmtree(job_dir, ignore_errors=True)
        raise HTTPException(status_code=400, detail=f"Cannot create job files: {exc}") from exc
    sync_store_outputs_root()
    store.create(job_id)
    background_tasks.add_task(
        process_transcription_job,
        job_id=job_id,
        job_dir=job_dir,
        video_path=video_path,
        config=config,
        store=store,
    )
    return {"job_id": job_id}


@app.post("/api/jobs/{job_id}/subtitles/confirm")
def confirm_subtitles(
    job_id: str,
    background_tasks: BackgroundTasks,
    note_language: Annotated[NoteLanguage, Form()],
    note_style: Annotated[NoteStyle, Form()] = NoteStyle.detailed,
    extras: Annotated[str, Form()] = "",
    note_api_key: Annotated[str, Form()] = "",
    note_base_url: Annotated[str, Form()] = "https://api.openai.com/v1",
    note_model: Annotated[str, Form()] = "gpt-5.5",
    frame_limit: Annotated[int, Form()] = 6,
) -> dict:
    sync_store_outputs_root()
    state = store.get(job_id) or store.load_from_disk(job_id)
    if not state:
        safe_job_dir(job_id)
        raise HTTPException(status_code=404, detail="Job not found.")
    if state.status != JobStatus.awaiting_subtitle_confirmation:
        raise HTTPException(status_code=409, detail="Subtitles are not awaiting confirmation.")
    job_dir = safe_job_dir(job_id)
    if not (job_dir / "transcript.json").exists() or not (job_dir / "source_video").exists():
        raise HTTPException(status_code=400, detail="Transcript or source video is missing.")
    if not note_api_key.strip():
        raise HTTPException(status_code=400, detail="Note API Key is required.")
    if not note_model.strip():
        raise HTTPException(status_code=400, detail="Note model is required.")
    if frame_limit < 1 or frame_limit > 24:
        raise HTTPException(status_code=400, detail="frame_limit must be between 1 and 24.")
    metadata = read_metadata(job_dir)
    original_filename = str(metadata.get("original_filename") or "video")
    config = JobConfig(
        transcription_mode=TranscriptionMode.local_faster_whisper,
        transcription_model="reuse-transcript",
        note_api_key=note_api_key,
        note_base_url=note_base_url,
        note_model=note_model,
        note_language=note_language,
        note_style=note_style,
        extras=extras,
        frame_limit=frame_limit,
        original_filename=original_filename,
    )
    store.update(job_id, status=JobStatus.running, step="笔记生成", progress=60, error="")
    background_tasks.add_task(
        continue_job_to_notes,
        job_id=job_id,
        job_dir=job_dir,
        video_path=_job_source_video_path(job_dir),
        config=config,
        store=store,
    )
    return {"job_id": job_id, "status": "running"}


@app.post("/api/jobs/{job_id}/subtitles/regenerate")
def regenerate_subtitles(
    job_id: str,
    background_tasks: BackgroundTasks,
    transcription_mode: Annotated[TranscriptionMode, Form()] = TranscriptionMode.audio_transcriptions,
    transcription_api_key: Annotated[str, Form()] = "",
    transcription_base_url: Annotated[str, Form()] = "https://api.openai.com/v1",
    transcription_model: Annotated[str, Form()] = "whisper-1",
    local_whisper_device: Annotated[str, Form()] = "",
    local_whisper_compute_type: Annotated[str, Form()] = "",
    transcription_language: Annotated[TranscriptionLanguage, Form()] = TranscriptionLanguage.auto,
) -> dict:
    sync_store_outputs_root()
    state = store.get(job_id) or store.load_from_disk(job_id)
    if not state:
        safe_job_dir(job_id)
        raise HTTPException(status_code=404, detail="Job not found.")
    if state.status != JobStatus.awaiting_subtitle_confirmation:
        raise HTTPException(status_code=409, detail="Subtitles are not awaiting confirmation.")
    job_dir = safe_job_dir(job_id)
    if not (job_dir / "source_video").exists():
        raise HTTPException(status_code=400, detail="Source video is missing. Subtitles cannot be regenerated.")
    uses_remote_transcription = transcription_mode != TranscriptionMode.local_faster_whisper
    if uses_remote_transcription and not transcription_api_key.strip():
        raise HTTPException(status_code=400, detail="Transcription API Key is required.")
    if uses_remote_transcription and not transcription_base_url.strip():
        raise HTTPException(status_code=400, detail="Transcription Base URL is required.")
    if not transcription_model.strip():
        raise HTTPException(status_code=400, detail="Transcription model is required.")
    try:
        config = JobConfig(
            transcription_mode=transcription_mode,
            transcription_api_key=transcription_api_key,
            transcription_base_url=transcription_base_url,
            transcription_model=transcription_model,
            local_whisper_device=local_whisper_device,
            local_whisper_compute_type=local_whisper_compute_type,
            transcription_language=transcription_language,
            note_api_key="placeholder",
            note_base_url="https://api.openai.com/v1",
            note_model="placeholder",
            note_language=NoteLanguage.zh,
            note_style=NoteStyle.detailed,
            extras="",
            frame_limit=6,
            original_filename=str(read_metadata(job_dir).get("original_filename") or "video"),
        )
    except ValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if config.transcription_mode == TranscriptionMode.local_faster_whisper:
        ensure_local_transcription_ready(config)
    store.update(job_id, status=JobStatus.running, step="字幕生成", progress=30, error="")
    background_tasks.add_task(
        regenerate_subtitles_job,
        job_id=job_id,
        job_dir=job_dir,
        video_path=_job_source_video_path(job_dir),
        config=config,
        store=store,
    )
    return {"job_id": job_id, "status": "running"}


def _job_source_video_path(job_dir: Path) -> Path:
    source_dir = job_dir / "source_video"
    candidates = sorted(source_dir.glob("input.*")) if source_dir.exists() else []
    return candidates[0] if candidates else source_dir / "input.mp4"


@app.get("/api/jobs", response_model=JobHistory)
def list_jobs() -> JobHistory:
    sync_store_outputs_root()
    return JobHistory(jobs=store.list_history())


@app.get("/api/jobs/{job_id}", response_model=JobPublicState)
def get_job(job_id: str) -> JobPublicState:
    sync_store_outputs_root()
    state = store.get(job_id)
    if not state:
        safe_job_dir(job_id)
        state = store.load_from_disk(job_id)
    if not state:
        raise HTTPException(status_code=404, detail="Job not found.")
    store.refresh_artifacts(job_id)
    return state


@app.delete("/api/jobs/{job_id}")
def delete_job(job_id: str) -> dict:
    sync_store_outputs_root()
    state = store.get(job_id)
    if state and state.status in {JobStatus.pending, JobStatus.running}:
        raise HTTPException(status_code=409, detail="Cannot delete a running job.")
    job_dir = safe_job_dir(job_id)
    try:
        shutil.rmtree(job_dir)
    except PermissionError as exc:
        raise HTTPException(status_code=409, detail=f"Cannot delete job because files are in use: {exc}") from exc
    except OSError as exc:
        raise HTTPException(status_code=409, detail=f"Cannot delete job files: {exc}") from exc
    store.remove(job_id)
    return {"ok": True}


@app.get("/api/jobs/{job_id}/preview/note", response_class=PlainTextResponse)
def preview_note(job_id: str) -> str:
    return read_job_text_file(job_id, "note.md")


@app.get("/api/jobs/{job_id}/preview/subtitles", response_class=PlainTextResponse)
def preview_subtitles(job_id: str) -> str:
    return read_job_text_file(job_id, "subtitles.md")


@app.get("/api/jobs/{job_id}/quality-report", response_model=QualityReport)
def get_quality_report(job_id: str) -> QualityReport:
    job_dir = safe_job_dir(job_id)
    if not (job_dir / "note.md").exists():
        raise HTTPException(status_code=400, detail="quality report requires note.md.")
    if not (job_dir / "transcript.json").exists():
        raise HTTPException(status_code=400, detail="quality report requires transcript.json.")
    report = build_quality_report(job_dir)
    write_quality_report(job_dir, report)
    store.refresh_artifacts(job_id)
    return report


@app.get("/api/jobs/{job_id}/frame-candidates", response_model=FrameCandidateIndex)
def get_frame_candidates(job_id: str) -> FrameCandidateIndex:
    job_dir = safe_job_dir(job_id)
    if not (job_dir / "note.md").exists():
        raise HTTPException(status_code=400, detail="frame candidates require note.md.")
    existing = load_frame_candidate_index(job_dir)
    if existing is not None:
        return existing
    try:
        video_path = find_source_video(job_dir)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    metadata = read_metadata(job_dir)
    duration = metadata.get("duration_seconds")
    index = build_frame_candidate_index(
        job_dir,
        video_path,
        duration=float(duration) if duration is not None else None,
    )
    write_frame_candidate_index(job_dir, index)
    store.refresh_artifacts(job_id)
    return index


@app.post("/api/jobs/{job_id}/frame-candidates/{candidate_id}/select", response_model=FrameCandidateIndex)
def select_job_frame_candidate(job_id: str, candidate_id: str) -> FrameCandidateIndex:
    job_dir = safe_job_dir(job_id)
    try:
        metadata = read_metadata(job_dir)
        index = select_frame_candidate(job_dir, candidate_id, frame_limit=int(metadata.get("frame_limit") or 6))
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    store.refresh_artifacts(job_id)
    return index


@app.post("/api/jobs/{job_id}/frame-candidates/{candidate_id}/reject", response_model=FrameCandidateIndex)
def reject_job_frame_candidate(job_id: str, candidate_id: str) -> FrameCandidateIndex:
    job_dir = safe_job_dir(job_id)
    try:
        index = reject_frame_candidate(job_dir, candidate_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    store.refresh_artifacts(job_id)
    return index


@app.get("/api/jobs/{job_id}/review-draft", response_model=ReviewDraft)
def get_job_review_draft(job_id: str) -> ReviewDraft:
    job_dir = safe_job_dir(job_id)
    try:
        draft = get_or_build_review_draft(job_dir)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    store.refresh_artifacts(job_id)
    return draft


@app.patch("/api/jobs/{job_id}/review-draft/paragraphs/{paragraph_id}", response_model=ReviewDraft)
def update_job_review_draft_paragraph(
    job_id: str,
    paragraph_id: str,
    update: ReviewDraftParagraphUpdate,
) -> ReviewDraft:
    job_dir = safe_job_dir(job_id)
    try:
        draft = update_review_draft_paragraph(
            job_dir,
            paragraph_id,
            body=update.body,
            selected_frame_ids=update.selected_frame_ids,
            status=update.status,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    store.refresh_artifacts(job_id)
    return draft


@app.post("/api/jobs/{job_id}/finalize", response_model=JobPublicState)
def finalize_job(job_id: str) -> JobPublicState:
    job_dir = safe_job_dir(job_id)
    if not is_note_review_pending(job_dir):
        raise HTTPException(status_code=409, detail="note review is not pending.")
    try:
        finalize_reviewed_note(job_dir)
        report = build_quality_report(job_dir)
        write_quality_report(job_dir, report)
        create_zip(job_dir)
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    store.refresh_artifacts(job_id)
    if not store.get(job_id):
        store.load_from_disk(job_id)
    store.update(job_id, status=JobStatus.succeeded, step="完成", progress=100, error="")
    state = store.get(job_id)
    if not state:
        raise HTTPException(status_code=404, detail="Job not found.")
    return state


@app.get("/api/jobs/{job_id}/assets/{asset_path:path}")
def get_asset(job_id: str, asset_path: str) -> FileResponse:
    file_path = safe_job_path(job_id, asset_path)
    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(status_code=404, detail="Asset not found.")
    suffix = file_path.suffix.lower()
    inline_suffixes = {".jpg", ".jpeg", ".png", ".gif", ".webp"}
    if suffix in inline_suffixes:
        return FileResponse(file_path)
    return FileResponse(file_path, filename=file_path.name)


@app.get("/api/jobs/{job_id}/download.zip")
def download_zip(job_id: str) -> FileResponse:
    file_path = safe_job_path(job_id, "download.zip")
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="ZIP is not ready.")
    return FileResponse(file_path, filename=f"video-note-{job_id}.zip")


@app.get("/api/jobs/{job_id}/note-chunks")
def list_note_chunks(job_id: str) -> dict:
    job_dir = safe_job_dir(job_id)
    index = load_note_chunk_index(job_dir)
    if not index:
        return {"chunks": [], "total_segments": 0}
    return index.model_dump(mode="json")


@app.post("/api/jobs/{job_id}/note-chunks/{chunk_id}/regenerate")
def regenerate_note_chunk(
    job_id: str,
    chunk_id: str,
    background_tasks: BackgroundTasks,
    note_api_key: Annotated[str, Form()],
    note_base_url: Annotated[str, Form()] = "https://api.openai.com/v1",
    note_model: Annotated[str, Form()] = "gpt-5.5",
    note_language: Annotated[NoteLanguage, Form()] = NoteLanguage.zh,
    note_style: Annotated[NoteStyle, Form()] = NoteStyle.detailed,
    extras: Annotated[str, Form()] = "",
    frame_limit: Annotated[int, Form()] = 6,
) -> dict:
    job_dir = safe_job_dir(job_id)
    index = load_note_chunk_index(job_dir)
    if not index:
        raise HTTPException(status_code=400, detail="Note chunks not found. Generate notes first.")
    meta = next((m for m in index.chunks if m.id == chunk_id), None)
    if not meta:
        raise HTTPException(status_code=404, detail=f"Chunk '{chunk_id}' not found.")
    if not note_api_key.strip():
        raise HTTPException(status_code=400, detail="Note API Key is required.")

    metadata = read_metadata(job_dir)
    original_filename = str(metadata.get("original_filename") or "video")
    config = JobConfig(
        transcription_mode=TranscriptionMode.local_faster_whisper,
        transcription_model="reuse-transcript",
        note_api_key=note_api_key,
        note_base_url=note_base_url,
        note_model=note_model,
        note_language=note_language,
        note_style=note_style,
        extras=extras,
        frame_limit=frame_limit,
        original_filename=original_filename,
    )
    store.update(job_id, status=JobStatus.running, step="重新生成笔记块", progress=70, error="")
    background_tasks.add_task(
        _regenerate_chunk_job,
        job_id=job_id,
        job_dir=job_dir,
        config=config,
        chunk_id=chunk_id,
    )
    return {"job_id": job_id, "status": "running"}


def _regenerate_chunk_job(job_id: str, job_dir: Path, config: JobConfig, chunk_id: str) -> None:
    from .processor import write_job_metadata
    from .task_debug_log import TaskDebugLog
    from .subtitles import transcript_segments_from_payload
    import json as _json

    debug_log = TaskDebugLog(job_dir)
    try:
        metadata = _json.loads((job_dir / "metadata.json").read_text(encoding="utf-8"))
        duration = metadata.get("duration_seconds")
        transcript_payload = _json.loads((job_dir / "transcript.json").read_text(encoding="utf-8"))
        segments = transcript_segments_from_payload(transcript_payload)
        system_prompt = (
            "You are a professional video content editor, course note writer, and knowledge management expert. "
            "You must write only from the transcript. Do not invent facts. "
            "Return strict JSON only. Preserve timestamps for chapter navigation and frame extraction."
        )
        debug_log.event("regenerate_note_chunk", "starting", chunk_id=chunk_id)
        draft = regenerate_chunk_and_reduce(job_dir, config, duration, segments, chunk_id, system_prompt)
        debug_log.event("regenerate_note_chunk", "succeeded", chunk_id=chunk_id)
        write_job_metadata(job_id=job_id, job_dir=job_dir, config=config, title=draft.title, duration=duration)
        stale_zip = job_dir / "download.zip"
        if stale_zip.exists():
            stale_zip.unlink()
        video_path = find_source_video(job_dir)
        duration_value = float(duration) if duration is not None else None
        create_note_version_from_draft(
            job_dir=job_dir,
            video_path=video_path,
            draft=draft,
            duration=duration_value,
            config=config,
        )
        frame_candidates = build_frame_candidate_index(job_dir, video_path, duration=duration_value)
        write_frame_candidate_index(job_dir, frame_candidates)
        quality_report = build_quality_report(job_dir)
        write_quality_report(job_dir, quality_report)
        mark_note_review_pending(job_dir)
        store.refresh_artifacts(job_id)
        store.update(job_id, status=JobStatus.awaiting_note_review, step="等待复核笔记", progress=92)
    except Exception as exc:
        debug_log.exception("regenerate_note_chunk", "failed", exc)
        store.refresh_artifacts(job_id)
        store.update(job_id, status=JobStatus.failed, step="失败", error=str(exc), progress=100)


@app.get("/api/jobs/{job_id}/note-versions", response_model=NoteVersionIndex)
def list_note_versions(job_id: str) -> NoteVersionIndex:
    job_dir = safe_job_dir(job_id)
    return load_note_version_index(job_dir)


@app.get("/api/jobs/{job_id}/preview/note/{version_id}", response_class=PlainTextResponse)
def preview_note_version(job_id: str, version_id: str) -> str:
    job_dir = safe_job_dir(job_id)
    index = load_note_version_index(job_dir)
    version = get_note_version(index, version_id)
    if not version:
        raise HTTPException(status_code=404, detail="Note version not found.")
    return read_job_text_file(job_id, version.note_path)


@app.patch("/api/jobs/{job_id}/note-versions", response_model=NoteVersionIndex)
def update_note_version_selection(job_id: str, selection: NoteVersionSelection) -> NoteVersionIndex:
    job_dir = safe_job_dir(job_id)
    if selection.active_version_id:
        try:
            index = activate_note_version(job_dir, selection.active_version_id)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        index = set_note_version_selection(job_dir, selection.selected_version_ids, selection.active_version_id)
    else:
        index = set_note_version_selection(job_dir, selection.selected_version_ids)
    create_zip(job_dir)
    store.refresh_artifacts(job_id)
    return index


@app.post("/api/jobs/{job_id}/note-versions")
def regenerate_note_version_endpoint(
    job_id: str,
    background_tasks: BackgroundTasks,
    note_language: Annotated[NoteLanguage, Form()],
    note_style: Annotated[NoteStyle, Form()] = NoteStyle.detailed,
    extras: Annotated[str, Form()] = "",
    note_api_key: Annotated[str, Form()] = "",
    note_base_url: Annotated[str, Form()] = "https://api.openai.com/v1",
    note_model: Annotated[str, Form()] = "gpt-5.5",
    frame_limit: Annotated[int, Form()] = 6,
) -> dict:
    job_dir = safe_job_dir(job_id)
    if not (job_dir / "transcript.json").exists():
        raise HTTPException(status_code=400, detail="Transcript is not ready. Run the full job first.")
    if not (job_dir / "source_video").exists():
        raise HTTPException(status_code=400, detail="Source video is missing. This job cannot regenerate frames.")
    if not note_api_key.strip():
        raise HTTPException(status_code=400, detail="Note API Key is required.")
    if not note_model.strip():
        raise HTTPException(status_code=400, detail="Note model is required.")
    if frame_limit < 1 or frame_limit > 24:
        raise HTTPException(status_code=400, detail="frame_limit must be between 1 and 24.")

    metadata = read_metadata(job_dir)
    config = JobConfig(
        transcription_mode=TranscriptionMode.local_faster_whisper,
        transcription_model="reuse-transcript",
        note_api_key=note_api_key,
        note_base_url=note_base_url,
        note_model=note_model,
        note_language=note_language,
        note_style=note_style,
        extras=extras,
        frame_limit=frame_limit,
        original_filename=str(metadata.get("original_filename") or "video"),
    )
    background_tasks.add_task(
        regenerate_note_job,
        job_id=job_id,
        job_dir=job_dir,
        config=config,
        store=store,
    )
    return {"job_id": job_id, "status": "queued"}


@app.post("/api/jobs/{job_id}/transcript-corrections", response_model=TranscriptCorrectionPreview)
def create_transcript_correction_endpoint(job_id: str, request: TranscriptCorrectionRequest) -> TranscriptCorrectionPreview:
    job_dir = safe_job_dir(job_id)
    if not request.note_api_key.strip():
        raise HTTPException(status_code=400, detail="Note API Key is required.")
    if not request.note_model.strip():
        raise HTTPException(status_code=400, detail="Note model is required.")

    metadata = read_metadata(job_dir)
    try:
        note_language = NoteLanguage(str(metadata.get("note_language") or "zh"))
    except ValueError:
        note_language = NoteLanguage.zh
    try:
        note_style = NoteStyle(str(metadata.get("note_style") or "detailed"))
    except ValueError:
        note_style = NoteStyle.detailed
    config = JobConfig(
        transcription_mode=TranscriptionMode.local_faster_whisper,
        transcription_model="reuse-transcript",
        note_api_key=request.note_api_key,
        note_base_url=request.note_base_url,
        note_model=request.note_model,
        note_language=note_language,
        note_style=note_style,
        frame_limit=int(metadata.get("frame_limit") or 6),
        original_filename=str(metadata.get("original_filename") or "video"),
    )
    try:
        preview = create_transcript_correction(job_dir, config, request.instructions)
        return preview.model_copy(update={"job_id": job_id})
    except (LLMError, TranscriptCorrectionError, FileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/jobs/{job_id}/transcript-corrections/apply")
def apply_transcript_correction_endpoint(
    job_id: str,
    request: TranscriptCorrectionApplyRequest,
    background_tasks: BackgroundTasks,
) -> dict:
    job_dir = safe_job_dir(job_id)
    if not (job_dir / "source_video").exists():
        raise HTTPException(status_code=400, detail="Source video is missing. This job cannot regenerate frames.")
    if not request.note_api_key.strip():
        raise HTTPException(status_code=400, detail="Note API Key is required.")
    if not request.note_model.strip():
        raise HTTPException(status_code=400, detail="Note model is required.")
    try:
        apply_pending_transcript_correction(job_dir)
    except (TranscriptCorrectionError, FileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    metadata = read_metadata(job_dir)
    config = JobConfig(
        transcription_mode=TranscriptionMode.local_faster_whisper,
        transcription_model="reuse-transcript",
        note_api_key=request.note_api_key,
        note_base_url=request.note_base_url,
        note_model=request.note_model,
        note_language=request.note_language,
        note_style=request.note_style,
        extras=request.extras,
        frame_limit=request.frame_limit,
        original_filename=str(metadata.get("original_filename") or "video"),
    )
    background_tasks.add_task(
        regenerate_note_job,
        job_id=job_id,
        job_dir=job_dir,
        config=config,
        store=store,
    )
    store.refresh_artifacts(job_id)
    return {"job_id": job_id, "status": "queued"}


def read_job_text_file(job_id: str, filename: str) -> str:
    file_path = safe_job_path(job_id, filename)
    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(status_code=404, detail=f"{filename} is not ready.")
    return file_path.read_text(encoding="utf-8-sig")


def safe_job_dir(job_id: str) -> Path:
    if not job_id or job_id in {".", ".."} or "/" in job_id or "\\" in job_id or ":" in job_id:
        raise HTTPException(status_code=400, detail="Invalid job id.")

    outputs_root = OUTPUTS_ROOT.resolve()
    job_dir = (outputs_root / job_id).resolve()
    if job_dir.parent != outputs_root or job_dir.name != job_id:
        raise HTTPException(status_code=400, detail="Invalid job id.")
    if not job_dir.exists():
        raise HTTPException(status_code=404, detail="Job not found.")
    return job_dir


def safe_job_path(job_id: str, relative_path: str) -> Path:
    job_dir = safe_job_dir(job_id)
    file_path = (job_dir / relative_path).resolve()
    if job_dir not in file_path.parents and file_path != job_dir:
        raise HTTPException(status_code=400, detail="Invalid asset path.")
    return file_path


def read_metadata(job_dir: Path) -> dict:
    metadata_path = job_dir / "metadata.json"
    if not metadata_path.exists():
        return {}
    return json.loads(metadata_path.read_text(encoding="utf-8"))


def sync_store_outputs_root() -> None:
    store.outputs_root = OUTPUTS_ROOT


frontend_dist_dir = get_frontend_dist_dir()
if frontend_dist_dir.exists():
    app.mount("/", StaticFiles(directory=frontend_dist_dir, html=True), name="frontend")
