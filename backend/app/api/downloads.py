from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractContextManager
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, PlainTextResponse

from ..job_paths import (
    InvalidJobAssetPathError,
    InvalidJobIdError,
    JobArtifactNotFoundError,
    JobDirectoryNotFoundError,
    read_job_text,
    resolve_job_dir,
    resolve_job_path,
)
from ..job_store import JobStore
from ..models import JobStatus
from ..note_versions import get_note_version, load_note_version_index
from ..processor import DIAGNOSTICS_ZIP_FILENAME, create_diagnostics_zip, create_zip


JobMutation = Callable[[str], AbstractContextManager[None]]


def create_downloads_router(
    *,
    get_outputs_root: Callable[[], Path],
    get_store: Callable[[], JobStore],
    job_mutation: JobMutation,
) -> APIRouter:
    router = APIRouter(tags=["downloads"])

    def current_store() -> JobStore:
        store = get_store()
        store.outputs_root = get_outputs_root()
        return store

    @router.get("/api/jobs/{job_id}/preview/note", response_class=PlainTextResponse)
    def preview_note(job_id: str) -> str:
        return _read_job_text_or_http(get_outputs_root(), job_id, "note.md")

    @router.get("/api/jobs/{job_id}/preview/subtitles", response_class=PlainTextResponse)
    def preview_subtitles(job_id: str) -> str:
        return _read_job_text_or_http(get_outputs_root(), job_id, "subtitles.md")

    @router.get("/api/jobs/{job_id}/preview/note/{version_id}", response_class=PlainTextResponse)
    def preview_note_version(job_id: str, version_id: str) -> str:
        job_dir = _resolve_job_dir_or_http(get_outputs_root(), job_id)
        version = get_note_version(load_note_version_index(job_dir), version_id)
        if not version:
            raise HTTPException(status_code=404, detail="Note version not found.")
        return _read_job_text_or_http(get_outputs_root(), job_id, version.note_path)

    @router.get("/api/jobs/{job_id}/assets/{asset_path:path}")
    def get_asset(job_id: str, asset_path: str) -> FileResponse:
        file_path = _resolve_job_path_or_http(get_outputs_root(), job_id, asset_path)
        if not file_path.exists() or not file_path.is_file():
            raise HTTPException(status_code=404, detail="Asset not found.")
        if file_path.suffix.lower() in {".jpg", ".jpeg", ".png", ".gif", ".webp"}:
            return FileResponse(file_path)
        return FileResponse(file_path, filename=file_path.name)

    @router.get("/api/jobs/{job_id}/download.zip")
    def download_zip(job_id: str) -> FileResponse:
        store = current_store()
        state = store.get(job_id) or store.load_from_disk(job_id)
        if state is None:
            raise HTTPException(status_code=404, detail="Job not found.")
        if state.status != JobStatus.succeeded:
            raise HTTPException(status_code=409, detail="ZIP is available after the job is finalized.")
        with job_mutation(job_id):
            job_dir = _resolve_job_dir_or_http(get_outputs_root(), job_id)
            if not (job_dir / "note.md").exists():
                raise HTTPException(status_code=404, detail="ZIP is not ready.")
            file_path = create_zip(job_dir)
            return FileResponse(file_path, filename=f"video-note-{job_id}.zip")

    @router.get("/api/jobs/{job_id}/diagnostics.zip")
    def download_diagnostics_zip(job_id: str) -> FileResponse:
        store = current_store()
        state = store.get(job_id) or store.load_from_disk(job_id)
        if state is None:
            raise HTTPException(status_code=404, detail="Job not found.")
        if state.status in {JobStatus.pending, JobStatus.running, JobStatus.cancelling}:
            raise HTTPException(status_code=409, detail="Diagnostics are available after the active operation stops.")
        with job_mutation(job_id):
            job_dir = _resolve_job_dir_or_http(get_outputs_root(), job_id)
            file_path = create_diagnostics_zip(job_dir)
            return FileResponse(
                file_path,
                filename=f"video-note-{job_id}-{DIAGNOSTICS_ZIP_FILENAME}",
            )

    return router


def _resolve_job_dir_or_http(outputs_root: Path, job_id: str) -> Path:
    try:
        return resolve_job_dir(outputs_root, job_id)
    except InvalidJobIdError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except JobDirectoryNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


def _resolve_job_path_or_http(outputs_root: Path, job_id: str, relative_path: str) -> Path:
    try:
        return resolve_job_path(outputs_root, job_id, relative_path)
    except (InvalidJobIdError, InvalidJobAssetPathError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except JobDirectoryNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


def _read_job_text_or_http(outputs_root: Path, job_id: str, relative_path: str) -> str:
    try:
        return read_job_text(outputs_root, job_id, relative_path)
    except (InvalidJobIdError, InvalidJobAssetPathError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except (JobDirectoryNotFoundError, JobArtifactNotFoundError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
