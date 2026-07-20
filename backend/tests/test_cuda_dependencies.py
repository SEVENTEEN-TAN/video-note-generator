from __future__ import annotations

from backend.app import cuda_dependencies
from backend.app.install_tasks import PackageInstallController


class FakeCompletedProcess:
    def __init__(self, *, returncode: int, stdout: str = "", stderr: str = "") -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr



def test_run_cuda_dependency_install_invokes_external_python_pip(monkeypatch) -> None:
    cuda_dependencies.clear_cuda_dependency_install_state()
    monkeypatch.setattr(cuda_dependencies, "find_external_python", lambda: "python")
    persisted: list[dict[str, str]] = []
    monkeypatch.setattr(cuda_dependencies, "save_user_settings", persisted.append)

    def fake_install(self, python_path: str) -> None:
        assert python_path == "python"

    monkeypatch.setattr(PackageInstallController, "install_packages", fake_install)

    initial, should_enqueue = cuda_dependencies.start_cuda_dependency_install()
    cuda_dependencies.run_cuda_dependency_install()
    finished = cuda_dependencies.get_cuda_dependency_install_state()

    assert initial.status == "pending"
    assert should_enqueue is True
    assert finished.status == "succeeded"
    assert finished.progress == 100
    assert finished.error == ""
    assert finished.python_path == "python"
    assert persisted == [{"external_python_path": "python"}]



def test_run_cuda_dependency_install_records_missing_python(monkeypatch) -> None:
    cuda_dependencies.clear_cuda_dependency_install_state()
    monkeypatch.setattr(cuda_dependencies, "find_external_python", lambda: None)

    cuda_dependencies.start_cuda_dependency_install()
    cuda_dependencies.run_cuda_dependency_install()
    finished = cuda_dependencies.get_cuda_dependency_install_state()

    assert finished.status == "failed"
    assert "External Python was not found" in finished.error



def test_start_cuda_dependency_install_does_not_reenqueue_while_pending(monkeypatch) -> None:
    cuda_dependencies.clear_cuda_dependency_install_state()
    monkeypatch.setattr(cuda_dependencies, "find_external_python", lambda: "python")

    first_state, first_should_enqueue = cuda_dependencies.start_cuda_dependency_install()
    second_state, second_should_enqueue = cuda_dependencies.start_cuda_dependency_install()

    assert first_state.status == "pending"
    assert first_should_enqueue is True
    assert second_state.status == "pending"
    assert second_should_enqueue is False
