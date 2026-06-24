from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

from desktop import desktop_launcher


class FakeResponse:
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, _exc_type, _exc, _traceback):
        return False


class FakeDownloadResponse:
    def __init__(self, payload: bytes):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, _exc_type, _exc, _traceback):
        return False

    def read(self) -> bytes:
        return self.payload


class FakeThread:
    def __init__(self) -> None:
        self.joined_with: float | None = None

    def join(self, timeout: float | None = None) -> None:
        self.joined_with = timeout


class FakeServer:
    def __init__(self) -> None:
        self.should_exit = False
        self.force_exit = False


def test_desktop_launcher_waits_on_lightweight_ready_endpoint(monkeypatch) -> None:
    requested_urls: list[str] = []

    def fake_urlopen(url: str, timeout: float):
        requested_urls.append(url)
        return FakeResponse()

    monkeypatch.setattr(desktop_launcher.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(desktop_launcher.time, "sleep", lambda _seconds: None)

    desktop_launcher.wait_until_ready("http://127.0.0.1:12345", timeout_seconds=1)

    assert requested_urls == ["http://127.0.0.1:12345/api/ready"]


def test_desktop_bridge_returns_cancelled_when_user_closes_save_dialog(monkeypatch) -> None:
    fake_webview = SimpleNamespace(
        SAVE_DIALOG="save-dialog",
        windows=[SimpleNamespace(create_file_dialog=lambda *_args, **_kwargs: None)],
    )
    monkeypatch.setitem(sys.modules, "webview", fake_webview)

    result = desktop_launcher.DesktopBridge().save_file("note.md", "http://127.0.0.1:8000/api/jobs/job-1/assets/note.md")

    assert result == {"ok": False, "reason": "cancelled"}


def test_desktop_bridge_saves_downloaded_file_to_selected_path(monkeypatch, tmp_path: Path) -> None:
    target_path = tmp_path / "saved-note.md"
    requested_urls: list[str] = []

    fake_webview = SimpleNamespace(
        SAVE_DIALOG="save-dialog",
        windows=[SimpleNamespace(create_file_dialog=lambda *_args, **_kwargs: str(target_path))],
    )

    def fake_urlopen(url: str, timeout: float):
        requested_urls.append(url)
        return FakeDownloadResponse(b"# saved")

    monkeypatch.setitem(sys.modules, "webview", fake_webview)
    monkeypatch.setattr(desktop_launcher.urllib.request, "urlopen", fake_urlopen)

    result = desktop_launcher.DesktopBridge().save_file("note.md", "http://127.0.0.1:8000/api/jobs/job-1/assets/note.md")

    assert result == {"ok": True, "path": str(target_path)}
    assert requested_urls == ["http://127.0.0.1:8000/api/jobs/job-1/assets/note.md"]
    assert target_path.read_bytes() == b"# saved"


def test_desktop_server_handle_stops_uvicorn_thread() -> None:
    server = FakeServer()
    thread = FakeThread()

    desktop_launcher.DesktopServerHandle(server=server, thread=thread).stop(timeout_seconds=1.5)

    assert server.should_exit is True
    assert server.force_exit is True
    assert thread.joined_with == 1.5


def test_destroy_other_webview_windows_keeps_main_and_closes_children() -> None:
    destroyed: list[str] = []

    class FakeWindow:
        def __init__(self, uid: str) -> None:
            self.uid = uid

        def destroy(self) -> None:
            destroyed.append(self.uid)

    main_window = FakeWindow("master")
    child_window = FakeWindow("child")
    fake_webview = SimpleNamespace(windows=[main_window, child_window])

    desktop_launcher.destroy_other_webview_windows(fake_webview, main_window)

    assert destroyed == ["child"]
