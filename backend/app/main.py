from __future__ import annotations

import shutil
from contextlib import asynccontextmanager, contextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError

from .api.ai import router as ai_router
from .api.downloads import create_downloads_router
from .api.jobs import create_jobs_router
from .api.notes import create_notes_router
from .api.review import create_review_router
from .api.runtime import router as runtime_router
from .api.settings import router as settings_router
from .api.subtitles import create_subtitles_router
from .job_paths import (
    InvalidJobIdError,
    JobDirectoryNotFoundError,
    resolve_job_dir,
)
from .job_store import JobStore
from .job_executor import JobBusyError, enqueue_serialized, job_executor
from .operation_leases import OperationLeaseLostError
from .operation_recovery import recover_incomplete_operations
from .ffmpeg_tools import extract_mp3, probe_duration
from .filenames import normalize_uploaded_filename
from .llm import generate_note_draft
from .models import (
    AIProtocol,
    JobPublicState,
    JobStage,
    JobStatus,
    NoteGenerationConfig,
    NoteLanguage,
    NotePreferences,
    NoteStyle,
    PerformanceMode,
    TranscriptionLanguage,
    TranscriptionConfig,
    TranscriptionMode,
)
from .note_regeneration import _regenerate_chunk_job
from .processor import (
    continue_job_to_notes,
    create_zip,
    process_uploaded_subtitle_job,
    process_transcription_job,
    regenerate_note_job,
    regenerate_subtitles_job,
)
from .runtime_status import get_runtime_status
from .runtime_paths import get_frontend_dist_dir, get_outputs_root
from .transcription import (
    TranscriptionError,
    get_faster_whisper_model_root,
    resolve_local_faster_whisper_model,
    transcribe_audio,
)
from .upload_limits import (
    InsufficientUploadStorageError,
    UploadConfigurationError,
    UploadLimits,
    UploadTooLargeError,
    ensure_upload_capacity,
    get_upload_limits,
    max_upload_request_bytes,
    validate_declared_upload_size,
)

OUTPUTS_ROOT = get_outputs_root()
OUTPUTS_ROOT.mkdir(parents=True, exist_ok=True)

ALLOWED_EXTENSIONS = {".mp4", ".mov", ".mkv", ".webm", ".avi"}
ALLOWED_SUBTITLE_EXTENSIONS = {".srt"}


@asynccontextmanager
async def app_lifespan(_app: FastAPI):
    sync_store_outputs_root()
    recover_incomplete_operations(OUTPUTS_ROOT, store)
    yield


app = FastAPI(title="Video Note Generator MVP", lifespan=app_lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:5173", "http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def enforce_upload_request_size(request: Request, call_next):
    if request.method == "POST":
        try:
            request_limit = max_upload_request_bytes(request.url.path, get_upload_limits())
        except UploadConfigurationError as exc:
            return JSONResponse(status_code=500, content={"detail": str(exc)})
        if request_limit is not None:
            raw_content_length = request.headers.get("content-length", "").strip()
            try:
                content_length = int(raw_content_length) if raw_content_length else None
            except ValueError:
                content_length = None
            if content_length is not None and content_length > request_limit:
                return JSONResponse(
                    status_code=413,
                    content={"detail": "Upload request exceeds the configured size limit."},
                )
    return await call_next(request)
app.include_router(runtime_router)
app.include_router(settings_router)
app.include_router(ai_router)
store = JobStore(OUTPUTS_ROOT)


@contextmanager
def job_mutation(job_id: str):
    safe_job_dir(job_id)
    try:
        with job_executor.acquire(
            job_id,
            blocking=False,
            outputs_root=OUTPUTS_ROOT,
        ):
            yield
    except (JobBusyError, OperationLeaseLostError) as exc:
        raise HTTPException(status_code=409, detail="Job is already being modified. Retry after the current operation finishes.") from exc


downloads_router = create_downloads_router(
    get_outputs_root=lambda: OUTPUTS_ROOT,
    get_store=lambda: store,
    job_mutation=job_mutation,
)
app.include_router(downloads_router)


def ensure_job_can_queue(job_id: str) -> JobPublicState:
    state = store.get(job_id) or store.load_from_disk(job_id)
    if state is None:
        raise HTTPException(status_code=404, detail="Job not found.")
    if state.status in {JobStatus.pending, JobStatus.running, JobStatus.cancelling}:
        raise HTTPException(status_code=409, detail="Job is already queued or running.")
    return state


def require_expected_job_revisions(
    job_id: str,
    *,
    expected_state_revision: int | None,
    expected_artifact_revision: str | None,
) -> JobPublicState | None:
    if expected_state_revision is None and expected_artifact_revision is None:
        return None
    state = store.get(job_id) or store.load_from_disk(job_id)
    if state is None:
        raise HTTPException(status_code=404, detail="Job not found.")
    store.refresh_artifacts(job_id)
    current = store.get(job_id)
    if current is None:
        raise HTTPException(status_code=404, detail="Job not found.")
    if expected_state_revision is not None and current.state_revision != expected_state_revision:
        raise HTTPException(
            status_code=409,
            detail=(
                "Job state changed since this page was loaded. Reload before applying this change "
                f"(expected state_revision={expected_state_revision}, current={current.state_revision})."
            ),
        )
    if (
        expected_artifact_revision is not None
        and current.artifact_revision != expected_artifact_revision
    ):
        raise HTTPException(
            status_code=409,
            detail=(
                "Job artifacts changed since this page was loaded. Reload before applying this change "
                f"(expected artifact_revision={expected_artifact_revision}, "
                f"current={current.artifact_revision})."
            ),
        )
    return current


review_router = create_review_router(
    get_outputs_root=lambda: OUTPUTS_ROOT,
    get_store=lambda: store,
    job_mutation=job_mutation,
    require_expected_job_revisions=require_expected_job_revisions,
    create_zip=lambda job_dir: create_zip(job_dir),
)
app.include_router(review_router)


def queue_job_state(job_id: str, *, step: str, progress: int) -> JobPublicState:
    ensure_job_can_queue(job_id)
    store.clear_cancel_request(job_id)
    store.update(
        job_id,
        status=JobStatus.pending,
        stage=JobStage.queued,
        step=step,
        progress=progress,
        error="",
    )
    queued = store.get(job_id)
    if queued is None:
        raise HTTPException(status_code=404, detail="Job not found.")
    return queued


def validate_video_extension(filename: str | None) -> str:
    suffix = Path(filename or "").suffix.lower()
    if suffix not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported video format. Use one of: {', '.join(sorted(ALLOWED_EXTENSIONS))}.",
        )
    return suffix


def validate_subtitle_extension(filename: str | None) -> str:
    suffix = Path(filename or "").suffix.lower()
    if suffix not in ALLOWED_SUBTITLE_EXTENSIONS:
        raise HTTPException(status_code=400, detail="Unsupported subtitle format. Use .srt.")
    return suffix


def build_transcription_config_or_400(
    *,
    transcription_mode: TranscriptionMode,
    transcription_api_key: str,
    transcription_base_url: str,
    transcription_model: str,
    local_whisper_device: str,
    local_whisper_compute_type: str,
    performance_mode: PerformanceMode = PerformanceMode.balanced,
    transcription_language: TranscriptionLanguage = TranscriptionLanguage.auto,
    original_filename: str = "video",
) -> TranscriptionConfig:
    uses_remote_transcription = transcription_mode != TranscriptionMode.local_faster_whisper
    if uses_remote_transcription and not transcription_api_key.strip():
        raise HTTPException(status_code=400, detail="Transcription API Key is required.")
    if uses_remote_transcription and not transcription_base_url.strip():
        raise HTTPException(status_code=400, detail="Transcription Base URL is required.")
    if not transcription_model.strip():
        raise HTTPException(status_code=400, detail="Transcription model is required.")

    try:
        return TranscriptionConfig(
            transcription_mode=transcription_mode,
            transcription_api_key=transcription_api_key,
            transcription_base_url=transcription_base_url,
            transcription_model=transcription_model,
            local_whisper_device=local_whisper_device,
            local_whisper_compute_type=local_whisper_compute_type,
            performance_mode=performance_mode,
            transcription_language=transcription_language,
            original_filename=normalize_uploaded_filename(original_filename),
        )
    except ValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def build_note_preferences_or_400(
    *,
    note_api_protocol: AIProtocol = AIProtocol.openai_chat_completions,
    note_base_url: str,
    note_model: str,
    note_language: NoteLanguage,
    note_style: NoteStyle,
    extras: str,
    frame_limit: int,
    original_filename: str,
) -> NotePreferences:
    try:
        return NotePreferences(
            note_api_protocol=note_api_protocol,
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


def build_note_generation_config_or_400(
    *,
    note_api_key: str,
    note_api_protocol: AIProtocol = AIProtocol.openai_chat_completions,
    note_base_url: str,
    note_model: str,
    note_language: NoteLanguage,
    note_style: NoteStyle,
    extras: str,
    frame_limit: int,
    original_filename: str,
) -> NoteGenerationConfig:
    if not note_api_key.strip():
        raise HTTPException(status_code=400, detail="Note API Key is required.")
    if not note_base_url.strip():
        raise HTTPException(status_code=400, detail="Note Base URL is required.")
    if not note_model.strip():
        raise HTTPException(status_code=400, detail="Note model is required.")
    try:
        return NoteGenerationConfig(
            note_api_key=note_api_key,
            note_api_protocol=note_api_protocol,
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


def ensure_local_cuda_ready(config: TranscriptionConfig) -> None:
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


def ensure_local_transcription_ready(config: TranscriptionConfig) -> None:
    if config.transcription_mode != TranscriptionMode.local_faster_whisper:
        return
    try:
        resolve_local_faster_whisper_model(config.transcription_model, get_faster_whisper_model_root())
    except TranscriptionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    ensure_local_cuda_ready(config)


subtitles_router = create_subtitles_router(
    get_outputs_root=lambda: OUTPUTS_ROOT,
    get_store=lambda: store,
    job_mutation=job_mutation,
    build_transcription_config=build_transcription_config_or_400,
    build_note_generation_config=build_note_generation_config_or_400,
    ensure_local_transcription_ready=ensure_local_transcription_ready,
    queue_job_state=queue_job_state,
    ensure_job_can_queue=ensure_job_can_queue,
    get_continue_job_to_notes=lambda: continue_job_to_notes,
    get_regenerate_subtitles_job=lambda: regenerate_subtitles_job,
    get_regenerate_note_job=lambda: regenerate_note_job,
)
app.include_router(subtitles_router)


notes_router = create_notes_router(
    get_outputs_root=lambda: OUTPUTS_ROOT,
    get_store=lambda: store,
    job_mutation=job_mutation,
    require_expected_job_revisions=require_expected_job_revisions,
    build_note_generation_config=build_note_generation_config_or_400,
    queue_job_state=queue_job_state,
    get_regenerate_chunk_job=lambda: _regenerate_chunk_job,
    get_regenerate_note_job=lambda: regenerate_note_job,
)
app.include_router(notes_router)


def validate_uploads_or_http(
    video: UploadFile,
    subtitle: UploadFile | None = None,
) -> UploadLimits:
    try:
        limits = get_upload_limits()
        validate_declared_upload_size(
            video.size,
            max_bytes=limits.max_video_bytes,
            label="Video",
        )
        declared_bytes = max(0, int(video.size or 0))
        if subtitle is not None and subtitle.filename:
            validate_declared_upload_size(
                subtitle.size,
                max_bytes=limits.max_subtitle_bytes,
                label="Subtitle",
            )
            declared_bytes += max(0, int(subtitle.size or 0))
        ensure_upload_capacity(
            OUTPUTS_ROOT,
            declared_bytes=declared_bytes,
            minimum_free_bytes=limits.minimum_free_bytes,
        )
        return limits
    except UploadTooLargeError as exc:
        raise HTTPException(status_code=413, detail=str(exc)) from exc
    except InsufficientUploadStorageError as exc:
        raise HTTPException(status_code=507, detail=str(exc)) from exc
    except UploadConfigurationError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


jobs_router = create_jobs_router(
    get_outputs_root=lambda: OUTPUTS_ROOT,
    get_store=lambda: store,
    job_mutation=job_mutation,
    validate_video_extension=validate_video_extension,
    validate_subtitle_extension=validate_subtitle_extension,
    build_transcription_config=build_transcription_config_or_400,
    build_note_preferences=build_note_preferences_or_400,
    build_note_generation_config=build_note_generation_config_or_400,
    validate_uploads=validate_uploads_or_http,
    queue_job_state=queue_job_state,
    get_ensure_local_transcription_ready=lambda: ensure_local_transcription_ready,
    get_enqueue_serialized=lambda: enqueue_serialized,
    get_process_uploaded_subtitle_job=lambda: process_uploaded_subtitle_job,
    get_process_transcription_job=lambda: process_transcription_job,
    get_probe_duration=lambda: probe_duration,
    get_extract_mp3=lambda: extract_mp3,
    get_transcribe_audio=lambda: transcribe_audio,
    get_generate_note_draft=lambda: generate_note_draft,
)
app.include_router(jobs_router)


def safe_job_dir(job_id: str) -> Path:
    try:
        return resolve_job_dir(OUTPUTS_ROOT, job_id)
    except InvalidJobIdError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except JobDirectoryNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


def sync_store_outputs_root() -> None:
    store.outputs_root = OUTPUTS_ROOT


frontend_dist_dir = get_frontend_dist_dir()
if frontend_dist_dir.exists():
    app.mount("/", StaticFiles(directory=frontend_dist_dir, html=True), name="frontend")
