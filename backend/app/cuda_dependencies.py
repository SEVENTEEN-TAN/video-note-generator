from __future__ import annotations

from pathlib import Path

from .install_tasks import PackageInstallController, PackageInstallState
from .runtime_config import get_python_package_install_args
from .runtime_paths import get_backend_requirements_file
from .settings import save_user_settings
from .transcription import find_external_python


class CudaDependencyInstallState(PackageInstallState):
    pass


def get_cuda_dependency_requirements_path() -> Path:
    return get_backend_requirements_file("requirements-cuda.txt")


def persist_external_python_path(python_path: str) -> None:
    save_user_settings({"external_python_path": python_path})


_controller = PackageInstallController(
    packages=(),
    failure_message="CUDA dependency installation failed.",
    python_finder=find_external_python,
    install_args_provider=get_python_package_install_args,
    requirements_file_provider=get_cuda_dependency_requirements_path,
    success_callback=persist_external_python_path,
)


def clear_cuda_dependency_install_state() -> None:
    _controller.clear()


def get_cuda_dependency_install_state() -> CudaDependencyInstallState:
    return CudaDependencyInstallState.model_validate(_controller.get_state().model_dump())


def _sync_python_finder() -> None:
    _controller._python_finder = find_external_python


def start_cuda_dependency_install() -> tuple[CudaDependencyInstallState, bool]:
    _sync_python_finder()
    state, should_enqueue = _controller.start()
    return CudaDependencyInstallState.model_validate(state.model_dump()), should_enqueue


def run_cuda_dependency_install() -> None:
    _sync_python_finder()
    _controller.run()
