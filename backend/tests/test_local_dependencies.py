from __future__ import annotations

from backend.app import local_dependencies
from backend.app.install_tasks import PackageInstallController



def test_run_local_dependency_install_invokes_external_python_pip(monkeypatch) -> None:
    local_dependencies.clear_local_dependency_install_state()
    monkeypatch.setattr(local_dependencies, "find_external_python", lambda: "python")

    def fake_install(self, python_path: str) -> None:
        assert python_path == "python"

    monkeypatch.setattr(PackageInstallController, "install_packages", fake_install)

    initial, should_enqueue = local_dependencies.start_local_dependency_install()
    local_dependencies.run_local_dependency_install()
    finished = local_dependencies.get_local_dependency_install_state()

    assert initial.status == "pending"
    assert should_enqueue is True
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



def test_start_local_dependency_install_does_not_reenqueue_while_pending(monkeypatch) -> None:
    local_dependencies.clear_local_dependency_install_state()
    monkeypatch.setattr(local_dependencies, "find_external_python", lambda: "python")

    first_state, first_should_enqueue = local_dependencies.start_local_dependency_install()
    second_state, second_should_enqueue = local_dependencies.start_local_dependency_install()

    assert first_state.status == "pending"
    assert first_should_enqueue is True
    assert second_state.status == "pending"
    assert second_should_enqueue is False
