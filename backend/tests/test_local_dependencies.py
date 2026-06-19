from __future__ import annotations

import subprocess

from backend.app import local_dependencies


def test_run_local_dependency_install_invokes_external_python_pip(monkeypatch) -> None:
    local_dependencies.clear_local_dependency_install_state()
    monkeypatch.setattr(local_dependencies, "find_external_python", lambda: "python")

    def fake_run(args, **kwargs):
        assert args == [
            "python",
            "-m",
            "pip",
            "install",
            "fastapi==0.115.6",
            "uvicorn[standard]==0.34.0",
            "python-multipart==0.0.20",
            "openai==1.59.7",
            "pydantic==2.12.5",
            "imageio-ffmpeg==0.5.1",
            "faster-whisper==1.1.1",
        ]
        assert kwargs["env"]["PYTHONIOENCODING"].lower() == "utf-8"
        return subprocess.CompletedProcess(args=args, returncode=0, stdout="installed", stderr="")

    monkeypatch.setattr(local_dependencies.subprocess, "run", fake_run)

    initial = local_dependencies.start_local_dependency_install()
    local_dependencies.run_local_dependency_install()
    finished = local_dependencies.get_local_dependency_install_state()

    assert initial.status == "pending"
    assert finished.status == "succeeded"
    assert finished.progress == 100
    assert finished.error == ""
    assert finished.python_path == "python"



def test_run_local_dependency_install_records_missing_python(monkeypatch) -> None:
    local_dependencies.clear_local_dependency_install_state()
    monkeypatch.setattr(local_dependencies, "find_external_python", lambda: None)

    local_dependencies.start_local_dependency_install()
    local_dependencies.run_local_dependency_install()
    finished = local_dependencies.get_local_dependency_install_state()

    assert finished.status == "failed"
    assert "External Python was not found" in finished.error
