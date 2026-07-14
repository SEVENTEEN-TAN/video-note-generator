from __future__ import annotations

from pathlib import Path

from backend.app.install_tasks import PackageInstallController


PACKAGES = ("demo-package",)
BACKEND_ROOT = Path(__file__).resolve().parents[1]


def test_default_requirements_include_app_and_test_dependencies_without_cuda_runtime() -> None:
    requirements = (BACKEND_ROOT / "requirements.txt").read_text(encoding="utf-8")

    assert "-r requirements-local.txt" in requirements
    assert "pytest==8.3.4" in requirements
    assert "nvidia-cublas" not in requirements
    assert "nvidia-cudnn" not in requirements


def test_package_install_controller_starts_once_and_reports_enqueue_flag() -> None:
    controller = PackageInstallController(packages=PACKAGES, failure_message="install failed")

    first_state, first_should_enqueue = controller.start()
    second_state, second_should_enqueue = controller.start()

    assert first_state.status == "pending"
    assert first_should_enqueue is True
    assert second_state.status == "pending"
    assert second_should_enqueue is False



def test_package_install_controller_allows_retry_after_terminal_state() -> None:
    controller = PackageInstallController(packages=PACKAGES, failure_message="install failed")

    controller.set_state(status="failed", progress=0, error="boom", python_path="python")
    state, should_enqueue = controller.start()

    assert state.status == "pending"
    assert state.error == ""
    assert should_enqueue is True


def test_package_install_controller_passes_install_args_before_packages(monkeypatch) -> None:
    calls: list[list[str]] = []
    controller = PackageInstallController(
        packages=PACKAGES,
        failure_message="install failed",
        python_finder=lambda: "python",
        install_args_provider=lambda: ["--user"],
    )

    def fake_run(command, **_kwargs):
        calls.append(command)
        return type("Completed", (), {"returncode": 0, "stdout": "", "stderr": ""})()

    monkeypatch.setattr("backend.app.install_tasks.subprocess.run", fake_run)

    controller.run()

    assert calls == [["python", "-m", "pip", "install", "--user", "demo-package"]]


def test_package_install_controller_installs_from_requirements_file(tmp_path, monkeypatch) -> None:
    calls: list[list[str]] = []
    requirements_path = tmp_path / "requirements-local.txt"
    requirements_path.write_text("demo-package==1.0\n", encoding="utf-8")
    controller = PackageInstallController(
        packages=(),
        failure_message="install failed",
        python_finder=lambda: "python",
        install_args_provider=lambda: ["--user"],
        requirements_file_provider=lambda: requirements_path,
    )

    def fake_run(command, **_kwargs):
        calls.append(command)
        return type("Completed", (), {"returncode": 0, "stdout": "", "stderr": ""})()

    monkeypatch.setattr("backend.app.install_tasks.subprocess.run", fake_run)

    controller.run()

    assert calls == [["python", "-m", "pip", "install", "--user", "-r", str(requirements_path)]]


def test_package_install_controller_reports_missing_requirements_file(tmp_path) -> None:
    missing_requirements = tmp_path / "missing.txt"
    controller = PackageInstallController(
        packages=(),
        failure_message="install failed",
        python_finder=lambda: "python",
        requirements_file_provider=lambda: missing_requirements,
    )

    controller.run()
    finished = controller.get_state()

    assert finished.status == "failed"
    assert str(missing_requirements) in finished.error
