from __future__ import annotations

import subprocess
import threading
from collections.abc import Callable, Sequence

from pydantic import BaseModel

from .transcription import TranscriptionError, external_worker_env


class PackageInstallState(BaseModel):
    status: str = "idle"
    progress: int = 0
    error: str = ""
    python_path: str = ""


class PackageInstallController:
    def __init__(
        self,
        *,
        packages: Sequence[str],
        failure_message: str,
        python_finder: Callable[[], str | None] | None = None,
        install_args_provider: Callable[[], Sequence[str]] | None = None,
    ) -> None:
        self._packages = tuple(packages)
        self._failure_message = failure_message
        self._python_finder = python_finder
        self._install_args_provider = install_args_provider
        self._state = PackageInstallState()
        self._lock = threading.Lock()

    def clear(self) -> None:
        with self._lock:
            self._state = PackageInstallState()

    def get_state(self) -> PackageInstallState:
        with self._lock:
            return self._state.model_copy()

    def start(self) -> tuple[PackageInstallState, bool]:
        python_path = self._find_python() or ""
        with self._lock:
            if self._state.status in {"pending", "running"}:
                return self._state.model_copy(), False
            self._state = PackageInstallState(status="pending", progress=0, error="", python_path=python_path)
            return self._state.model_copy(), True

    def run(self) -> None:
        python_path = self._find_python()
        if not python_path:
            self.set_state(
                status="failed",
                progress=0,
                error="External Python was not found on PATH. Install Python 3.10+ or set VIDEO_NOTE_PYTHON_PATH.",
                python_path="",
            )
            return

        self.set_state(status="running", progress=10, error="", python_path=python_path)
        try:
            self.install_packages(python_path)
            self.set_state(status="succeeded", progress=100, error="", python_path=python_path)
        except Exception as exc:
            self.set_state(status="failed", progress=0, error=str(exc), python_path=python_path)

    def set_state(self, *, status: str, progress: int, error: str, python_path: str) -> None:
        with self._lock:
            self._state = PackageInstallState(
                status=status,
                progress=progress,
                error=error,
                python_path=python_path,
            )

    def install_packages(self, python_path: str) -> None:
        install_args = list(self._install_args_provider() if self._install_args_provider else [])
        completed = subprocess.run(
            [
                python_path,
                "-m",
                "pip",
                "install",
                *install_args,
                *self._packages,
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=external_worker_env(),
        )
        if completed.returncode != 0:
            message = completed.stderr.strip() or completed.stdout.strip() or self._failure_message
            raise TranscriptionError(message[-2000:])

    def _find_python(self) -> str | None:
        if self._python_finder is None:
            return None
        return self._python_finder()
