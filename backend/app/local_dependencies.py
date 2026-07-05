from __future__ import annotations

from pathlib import Path

from .install_tasks import PackageInstallController, PackageInstallState
from .runtime_config import get_python_package_install_args
from .runtime_paths import get_backend_requirements_file
from .transcription import find_external_python


class LocalTranscriptionDependencyInstallState(PackageInstallState):
    pass


def get_local_dependency_requirements_path() -> Path:
    return get_backend_requirements_file("requirements-local.txt")


_controller = PackageInstallController(
    packages=(),
    failure_message="Local transcription dependency installation failed.",
    python_finder=find_external_python,
    install_args_provider=get_python_package_install_args,
    requirements_file_provider=get_local_dependency_requirements_path,
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
