from __future__ import annotations

from .install_tasks import PackageInstallController, PackageInstallState
from .runtime_config import get_python_package_install_args
from .transcription import find_external_python

LOCAL_TRANSCRIPTION_DEPENDENCY_PACKAGES = (
    "fastapi==0.115.6",
    "uvicorn[standard]==0.34.0",
    "python-multipart==0.0.20",
    "openai==1.59.7",
    "pydantic==2.12.5",
    "imageio-ffmpeg==0.5.1",
    "faster-whisper==1.1.1",
)


class LocalTranscriptionDependencyInstallState(PackageInstallState):
    pass


_controller = PackageInstallController(
    packages=LOCAL_TRANSCRIPTION_DEPENDENCY_PACKAGES,
    failure_message="Local transcription dependency installation failed.",
    python_finder=find_external_python,
    install_args_provider=get_python_package_install_args,
)


def clear_local_dependency_install_state() -> None:
    _controller.clear()


def get_local_dependency_install_state() -> LocalTranscriptionDependencyInstallState:
    return LocalTranscriptionDependencyInstallState.model_validate(_controller.get_state().model_dump())


def _sync_python_finder() -> None:
    _controller._python_finder = find_external_python


def start_local_dependency_install() -> tuple[LocalTranscriptionDependencyInstallState, bool]:
    _sync_python_finder()
    state, should_enqueue = _controller.start()
    return LocalTranscriptionDependencyInstallState.model_validate(state.model_dump()), should_enqueue


def run_local_dependency_install() -> None:
    _sync_python_finder()
    _controller.run()
