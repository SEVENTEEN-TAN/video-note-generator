from __future__ import annotations

from backend.app.install_tasks import PackageInstallController


PACKAGES = ("demo-package",)


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
