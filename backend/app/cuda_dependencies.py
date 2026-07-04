from __future__ import annotations

from .install_tasks import PackageInstallController, PackageInstallState
from .runtime_config import get_python_package_install_args
from .transcription import find_external_python

CUDA_DEPENDENCY_PACKAGES = ("nvidia-cublas-cu12", "nvidia-cudnn-cu12")


class CudaDependencyInstallState(PackageInstallState):
    pass


_controller = PackageInstallController(
    packages=CUDA_DEPENDENCY_PACKAGES,
    failure_message="CUDA dependency installation failed.",
    python_finder=find_external_python,
    install_args_provider=get_python_package_install_args,
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
