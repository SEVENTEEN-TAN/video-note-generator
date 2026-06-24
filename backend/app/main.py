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

from .job_store import JobStore
from .cuda_dependencies import (
    CudaDependencyInstallState,
    get_cuda_dependency_install_state,
    run_cuda_dependency_install,
    start_cuda_dependency_install,
)
from .ffmpeg_tools import extract_mp3, probe_duration
from .llm import generate_note_draft
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
    FrameSuggestion,
    JobConfig,
    JobHistory,
    JobPublicState,
    NoteLanguage,
    NoteStyle,
    NoteVersionIndex,
    NoteVersionSelection,
    TranscriptionMode,
)
from .note_versions import activate_note_version, get_note_version, load_note_version_index, set_note_version_selection
from .processor import create_zip, process_job, regenerate_note_job
from .runtime_status import get_runtime_status
from .runtime_paths import get_frontend_dist_dir, get_outputs_root
from .settings import UserSettings, UserSettingsUpdate, clear_user_settings, load_user_settings, save_user_settings
from .subtitles import transcript_segments_from_payload
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
    note_api_key: Annotated[str, Form()] = "",
    note_base_url: Annotated[str, Form()] = "https://api.openai.com/v1",
    note_model: Annotated[str, Form()] = "gpt-5.5",
) -> FrameSuggestion:
    suffix = Path(video.filename or "").suffix.lower()
    if suffix not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported video format. Use one of: {', '.join(sorted(ALLOWED_EXTENSIONS))}.",
        )
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
    if transcription_mode == TranscriptionMode.local_faster_whisper:
        try:
            resolve_local_faster_whisper_model(transcription_model, get_faster_whisper_model_root())
        except TranscriptionError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    temp_dir = OUTPUTS_ROOT / ".frame-suggestions" / uuid.uuid4().hex
    source_dir = temp_dir / "source_video"
    source_dir.mkdir(parents=True, exist_ok=True)
    video_path = source_dir / f"input{suffix}"
    try:
        with video_path.open("wb") as target:
            shutil.copyfileobj(video.file, target)

        config = JobConfig(
            transcription_mode=transcription_mode,
            transcription_api_key=transcription_api_key,
            transcription_base_url=transcription_base_url,
            transcription_model=transcription_model,
            local_whisper_device=local_whisper_device,
            local_whisper_compute_type=local_whisper_compute_type,
            note_api_key=note_api_key,
            note_base_url=note_base_url,
            note_model=note_model,
            note_language=note_language,
            note_style=note_style,
            extras=extras,
            frame_limit=12,
            original_filename=video.filename or video_path.name,
        )
        duration = probe_duration(video_path)
        audio_path = temp_dir / "audio.mp3"
        extract_mp3(video_path, audio_path)
        transcript_payload = transcribe_audio(audio_path, config, temp_dir)
        segments = transcript_segments_from_payload(transcript_payload)
        if not segments:
            raise HTTPException(status_code=400, detail="Transcription returned no usable text segments.")
        draft = generate_note_draft(config, duration, segments)
        return FrameSuggestion(
            recommended_frame_count=draft.recommended_frame_count or min(max(len(draft.key_moments), 1), 12),
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
    note_api_key: Annotated[str, Form()] = "",
    note_base_url: Annotated[str, Form()] = "https://api.openai.com/v1",
    note_model: Annotated[str, Form()] = "gpt-5.5",
    frame_limit: Annotated[int, Form()] = 6,
) -> dict:
    suffix = Path(video.filename or "").suffix.lower()
    if suffix not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported video format. Use one of: {', '.join(sorted(ALLOWED_EXTENSIONS))}.",
        )
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
    if transcription_mode == TranscriptionMode.local_faster_whisper:
        try:
            resolve_local_faster_whisper_model(transcription_model, get_faster_whisper_model_root())
        except TranscriptionError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    job_id = uuid.uuid4().hex
    job_dir = OUTPUTS_ROOT / job_id
    source_dir = job_dir / "source_video"
    source_dir.mkdir(parents=True, exist_ok=True)
    video_path = source_dir / f"input{suffix}"
    with video_path.open("wb") as target:
        shutil.copyfileobj(video.file, target)

    config = JobConfig(
        transcription_mode=transcription_mode,
        transcription_api_key=transcription_api_key,
        transcription_base_url=transcription_base_url,
        transcription_model=transcription_model,
        local_whisper_device=local_whisper_device,
        local_whisper_compute_type=local_whisper_compute_type,
        note_api_key=note_api_key,
        note_base_url=note_base_url,
        note_model=note_model,
        note_language=note_language,
        note_style=note_style,
        extras=extras,
        frame_limit=frame_limit,
        original_filename=video.filename or video_path.name,
    )
    sync_store_outputs_root()
    store.create(job_id)
    background_tasks.add_task(
        process_job,
        job_id=job_id,
        job_dir=job_dir,
        video_path=video_path,
        config=config,
        store=store,
    )
    return {"job_id": job_id}


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
    shutil.rmtree(job_dir)
    store.remove(job_id)
    return {"ok": True}


@app.get("/api/jobs/{job_id}/preview/note", response_class=PlainTextResponse)
def preview_note(job_id: str) -> str:
    return read_job_text_file(job_id, "note.md")


@app.get("/api/jobs/{job_id}/preview/subtitles", response_class=PlainTextResponse)
def preview_subtitles(job_id: str) -> str:
    return read_job_text_file(job_id, "subtitles.md")


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
    index = set_note_version_selection(job_dir, selection.selected_version_ids, selection.active_version_id)
    if selection.active_version_id:
        index = activate_note_version(job_dir, selection.active_version_id)
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


def read_job_text_file(job_id: str, filename: str) -> str:
    file_path = safe_job_path(job_id, filename)
    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(status_code=404, detail=f"{filename} is not ready.")
    return file_path.read_text(encoding="utf-8-sig")


def safe_job_dir(job_id: str) -> Path:
    job_dir = (OUTPUTS_ROOT / job_id).resolve()
    if OUTPUTS_ROOT.resolve() not in job_dir.parents and job_dir != OUTPUTS_ROOT.resolve():
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
