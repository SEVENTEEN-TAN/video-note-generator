from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractContextManager
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, BackgroundTasks, Form, HTTPException

from ..job_executor import enqueue_serialized
from ..job_paths import InvalidJobIdError, JobDirectoryNotFoundError, read_job_metadata, resolve_job_dir
from ..job_store import JobStore
from ..models import (
    AIProtocol,
    JobPublicState,
    NoteGenerationConfig,
    NoteLanguage,
    NoteStyle,
    NoteVersionIndex,
    NoteVersionSelection,
)
from ..note_chunks import NoteChunkIndex, load_note_chunk_index
from ..note_versions import activate_note_version, load_note_version_index, set_note_version_selection
from ..processor import SUBTITLES_PENDING_MARKER, mark_zip_dirty


JobMutation = Callable[[str], AbstractContextManager[None]]
RevisionGuard = Callable[..., JobPublicState | None]
BuildNoteGenerationConfig = Callable[..., NoteGenerationConfig]
QueueJobState = Callable[..., JobPublicState]
BackgroundJob = Callable[..., Any]
BackgroundJobGetter = Callable[[], BackgroundJob]


def create_notes_router(
    *,
    get_outputs_root: Callable[[], Path],
    get_store: Callable[[], JobStore],
    job_mutation: JobMutation,
    require_expected_job_revisions: RevisionGuard,
    build_note_generation_config: BuildNoteGenerationConfig,
    queue_job_state: QueueJobState,
    get_regenerate_chunk_job: BackgroundJobGetter,
    get_regenerate_note_job: BackgroundJobGetter,
) -> APIRouter:
    router = APIRouter(tags=["notes"])

    def current_store() -> JobStore:
        store = get_store()
        store.outputs_root = get_outputs_root()
        return store

    @router.get("/api/jobs/{job_id}/note-chunks", response_model=NoteChunkIndex)
    def list_note_chunks(job_id: str) -> NoteChunkIndex:
        job_dir = _resolve_job_dir_or_http(get_outputs_root(), job_id)
        return load_note_chunk_index(job_dir) or NoteChunkIndex()

    @router.post("/api/jobs/{job_id}/note-chunks/{chunk_id}/regenerate")
    def regenerate_note_chunk(
        job_id: str,
        chunk_id: str,
        background_tasks: BackgroundTasks,
        note_api_key: Annotated[str, Form()],
        note_api_protocol: Annotated[AIProtocol, Form()] = AIProtocol.openai_chat_completions,
        note_thinking_enabled: Annotated[bool, Form()] = False,
        note_context_window_tokens: Annotated[int, Form()] = 32_768,
        note_max_output_tokens: Annotated[int, Form()] = 8_192,
        note_base_url: Annotated[str, Form()] = "https://api.openai.com/v1",
        note_model: Annotated[str, Form()] = "gpt-5.5",
        note_language: Annotated[NoteLanguage, Form()] = NoteLanguage.zh,
        note_style: Annotated[NoteStyle, Form()] = NoteStyle.detailed,
        extras: Annotated[str, Form()] = "",
        frame_limit: Annotated[int, Form()] = 6,
    ) -> dict:
        job_dir = _resolve_job_dir_or_http(get_outputs_root(), job_id)
        _ensure_subtitles_confirmed(job_dir)
        index = load_note_chunk_index(job_dir)
        if not index:
            raise HTTPException(status_code=400, detail="Note chunks not found. Generate notes first.")
        if not any(meta.id == chunk_id for meta in index.chunks):
            raise HTTPException(status_code=404, detail=f"Chunk '{chunk_id}' not found.")
        metadata = read_job_metadata(job_dir)
        config = build_note_generation_config(
            note_api_key=note_api_key,
            note_api_protocol=note_api_protocol,
            note_thinking_enabled=note_thinking_enabled,
            note_context_window_tokens=note_context_window_tokens,
            note_max_output_tokens=note_max_output_tokens,
            note_base_url=note_base_url,
            note_model=note_model,
            note_language=note_language,
            note_style=note_style,
            extras=extras,
            frame_limit=frame_limit,
            original_filename=str(metadata.get("original_filename") or "video"),
        )
        store = current_store()
        with job_mutation(job_id):
            queue_job_state(job_id, step="等待重新生成笔记块", progress=70)
            enqueue_serialized(
                background_tasks,
                get_regenerate_chunk_job(),
                job_id=job_id,
                job_dir=job_dir,
                config=config,
                chunk_id=chunk_id,
                store=store,
            )
        return {"job_id": job_id, "status": "queued"}

    @router.get("/api/jobs/{job_id}/note-versions", response_model=NoteVersionIndex)
    def list_note_versions(job_id: str) -> NoteVersionIndex:
        return load_note_version_index(_resolve_job_dir_or_http(get_outputs_root(), job_id))

    @router.patch("/api/jobs/{job_id}/note-versions", response_model=NoteVersionIndex)
    def update_note_version_selection(
        job_id: str,
        selection: NoteVersionSelection,
        expected_state_revision: int | None = None,
        expected_artifact_revision: str | None = None,
    ) -> NoteVersionIndex:
        with job_mutation(job_id):
            require_expected_job_revisions(
                job_id,
                expected_state_revision=expected_state_revision,
                expected_artifact_revision=expected_artifact_revision,
            )
            job_dir = _resolve_job_dir_or_http(get_outputs_root(), job_id)
            if selection.active_version_id:
                try:
                    index = activate_note_version(job_dir, selection.active_version_id)
                except FileNotFoundError as exc:
                    raise HTTPException(status_code=404, detail=str(exc)) from exc
                except ValueError as exc:
                    raise HTTPException(status_code=400, detail=str(exc)) from exc
                index = set_note_version_selection(
                    job_dir,
                    selection.selected_version_ids,
                    selection.active_version_id,
                )
            else:
                index = set_note_version_selection(job_dir, selection.selected_version_ids)
            mark_zip_dirty(job_dir)
            current_store().refresh_artifacts(job_id)
            return index

    @router.post("/api/jobs/{job_id}/note-versions")
    def regenerate_note_version_endpoint(
        job_id: str,
        background_tasks: BackgroundTasks,
        note_language: Annotated[NoteLanguage, Form()],
        note_style: Annotated[NoteStyle, Form()] = NoteStyle.detailed,
        extras: Annotated[str, Form()] = "",
        note_api_key: Annotated[str, Form()] = "",
        note_api_protocol: Annotated[AIProtocol, Form()] = AIProtocol.openai_chat_completions,
        note_thinking_enabled: Annotated[bool, Form()] = False,
        note_context_window_tokens: Annotated[int, Form()] = 32_768,
        note_max_output_tokens: Annotated[int, Form()] = 8_192,
        note_base_url: Annotated[str, Form()] = "https://api.openai.com/v1",
        note_model: Annotated[str, Form()] = "gpt-5.5",
        frame_limit: Annotated[int, Form()] = 6,
    ) -> dict:
        job_dir = _resolve_job_dir_or_http(get_outputs_root(), job_id)
        _ensure_subtitles_confirmed(job_dir)
        if not (job_dir / "transcript.json").exists():
            raise HTTPException(status_code=400, detail="Transcript is not ready. Run the full job first.")
        if not (job_dir / "source_video").exists():
            raise HTTPException(status_code=400, detail="Source video is missing. This job cannot regenerate frames.")
        metadata = read_job_metadata(job_dir)
        config = build_note_generation_config(
            note_api_key=note_api_key,
            note_api_protocol=note_api_protocol,
            note_thinking_enabled=note_thinking_enabled,
            note_context_window_tokens=note_context_window_tokens,
            note_max_output_tokens=note_max_output_tokens,
            note_base_url=note_base_url,
            note_model=note_model,
            note_language=note_language,
            note_style=note_style,
            extras=extras,
            frame_limit=frame_limit,
            original_filename=str(metadata.get("original_filename") or "video"),
        )
        store = current_store()
        with job_mutation(job_id):
            queue_job_state(job_id, step="等待重新生成笔记", progress=62)
            enqueue_serialized(
                background_tasks,
                get_regenerate_note_job(),
                job_id=job_id,
                job_dir=job_dir,
                config=config,
                store=store,
            )
        return {"job_id": job_id, "status": "queued"}

    return router


def _resolve_job_dir_or_http(outputs_root: Path, job_id: str) -> Path:
    try:
        return resolve_job_dir(outputs_root, job_id)
    except InvalidJobIdError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except JobDirectoryNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


def _ensure_subtitles_confirmed(job_dir: Path) -> None:
    if (job_dir / SUBTITLES_PENDING_MARKER).exists():
        raise HTTPException(
            status_code=409,
            detail="Subtitles must be confirmed before generating or regenerating notes.",
        )
