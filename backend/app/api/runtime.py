from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks

from ..cuda_dependencies import (
    CudaDependencyInstallState,
    get_cuda_dependency_install_state,
    run_cuda_dependency_install,
    start_cuda_dependency_install,
)
from ..local_dependencies import (
    LocalTranscriptionDependencyInstallState,
    get_local_dependency_install_state,
    run_local_dependency_install,
    start_local_dependency_install,
)
from ..model_downloads import (
    ModelDownloadRequest,
    ModelDownloadState,
    get_model_download_state,
    run_model_download,
    start_model_download,
)
from ..runtime_models import HealthState, RuntimeState
from ..runtime_status import get_runtime_status
from ..transcription import clear_internal_whisper_model_cache


router = APIRouter(tags=["runtime"])


@router.get("/api/ready")
def ready() -> dict:
    return {"ok": True}


@router.get("/api/health", response_model=HealthState)
def health() -> HealthState:
    runtime = get_runtime_status()
    return HealthState(
        ok=True,
        runtime_ok=runtime["ok"],
        ffmpeg_available=runtime["ffmpeg"]["available"],
        ffmpeg_path=runtime["ffmpeg"]["path"],
        runtime=RuntimeState.model_validate(runtime),
    )


@router.get("/api/runtime", response_model=RuntimeState)
def runtime() -> RuntimeState:
    return RuntimeState.model_validate(get_runtime_status())


@router.post("/api/runtime/faster-whisper/cache/clear")
def clear_faster_whisper_cache() -> dict:
    return {"cleared_models": clear_internal_whisper_model_cache()}


@router.post("/api/runtime/cuda-dependencies/install", response_model=CudaDependencyInstallState)
def install_cuda_dependencies(background_tasks: BackgroundTasks) -> CudaDependencyInstallState:
    state, should_enqueue = start_cuda_dependency_install()
    if should_enqueue:
        background_tasks.add_task(run_cuda_dependency_install)
    return state


@router.get("/api/runtime/cuda-dependencies/install", response_model=CudaDependencyInstallState)
def get_cuda_dependency_install() -> CudaDependencyInstallState:
    return get_cuda_dependency_install_state()


@router.post(
    "/api/runtime/local-dependencies/install",
    response_model=LocalTranscriptionDependencyInstallState,
)
def install_local_dependencies(
    background_tasks: BackgroundTasks,
) -> LocalTranscriptionDependencyInstallState:
    state, should_enqueue = start_local_dependency_install()
    if should_enqueue:
        background_tasks.add_task(run_local_dependency_install)
    return state


@router.get(
    "/api/runtime/local-dependencies/install",
    response_model=LocalTranscriptionDependencyInstallState,
)
def get_local_dependency_install() -> LocalTranscriptionDependencyInstallState:
    return get_local_dependency_install_state()


@router.post("/api/models/faster-whisper/download", response_model=ModelDownloadState)
def download_faster_whisper_model_endpoint(
    request: ModelDownloadRequest,
    background_tasks: BackgroundTasks,
) -> ModelDownloadState:
    state = start_model_download(request.model_name)
    if state.status == "pending":
        background_tasks.add_task(run_model_download, request.model_name)
    return state


@router.get(
    "/api/models/faster-whisper/download/{model_name}",
    response_model=ModelDownloadState,
)
def get_faster_whisper_model_download(model_name: str) -> ModelDownloadState:
    return get_model_download_state(model_name)
