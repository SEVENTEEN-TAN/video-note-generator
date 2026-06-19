from __future__ import annotations

import subprocess

from backend.app import cuda_dependencies


def test_run_cuda_dependency_install_invokes_external_python_pip(monkeypatch) -> None:
    cuda_dependencies.clear_cuda_dependency_install_state()
    monkeypatch.setattr(cuda_dependencies, "find_external_python", lambda: "python")

    def fake_run(args, **kwargs):
        assert args == [
            "python",
            "-m",
            "pip",
            "install",
            "nvidia-cublas-cu12",
            "nvidia-cudnn-cu12",
        ]
        assert kwargs["env"]["PYTHONIOENCODING"].lower() == "utf-8"
        return subprocess.CompletedProcess(args=args, returncode=0, stdout="installed", stderr="")

    monkeypatch.setattr(cuda_dependencies.subprocess, "run", fake_run)

    initial = cuda_dependencies.start_cuda_dependency_install()
    cuda_dependencies.run_cuda_dependency_install()
    finished = cuda_dependencies.get_cuda_dependency_install_state()

    assert initial.status == "pending"
    assert finished.status == "succeeded"
    assert finished.progress == 100
    assert finished.error == ""
    assert finished.python_path == "python"


def test_run_cuda_dependency_install_records_missing_python(monkeypatch) -> None:
    cuda_dependencies.clear_cuda_dependency_install_state()
    monkeypatch.setattr(cuda_dependencies, "find_external_python", lambda: None)

    cuda_dependencies.start_cuda_dependency_install()
    cuda_dependencies.run_cuda_dependency_install()
    finished = cuda_dependencies.get_cuda_dependency_install_state()

    assert finished.status == "failed"
    assert "External Python was not found" in finished.error
