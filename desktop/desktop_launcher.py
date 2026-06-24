from __future__ import annotations

import socket
import sys
import threading
import time
import traceback
import urllib.request
import webbrowser
from dataclasses import dataclass
from pathlib import Path

import uvicorn

from backend.app.main import app


APP_TITLE = "视频笔记生成器"
HOST = "127.0.0.1"


@dataclass
class DesktopServerHandle:
    server: uvicorn.Server
    thread: threading.Thread

    def stop(self, timeout_seconds: float = 5.0) -> None:
        self.server.should_exit = True
        if hasattr(self.server, "force_exit"):
            self.server.force_exit = True
        is_alive = getattr(self.thread, "is_alive", lambda: True)
        if is_alive():
            self.thread.join(timeout_seconds)


class DesktopBridge:
    def save_file(self, suggested_name: str, source_url: str) -> dict[str, str | bool]:
        import webview

        selected = webview.windows[0].create_file_dialog(
            webview.SAVE_DIALOG,
            save_filename=suggested_name,
        )
        if not selected:
            return {"ok": False, "reason": "cancelled"}

        target = selected if isinstance(selected, str) else selected[0]
        target_path = Path(target)
        with urllib.request.urlopen(source_url, timeout=30) as response:
            target_path.write_bytes(response.read())
        return {"ok": True, "path": str(target_path)}


def find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind((HOST, 0))
        return int(sock.getsockname()[1])


def run_server(port: int) -> DesktopServerHandle:
    config = uvicorn.Config(
        app,
        host=HOST,
        port=port,
        access_log=False,
        log_config=None,
        log_level="warning",
    )
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, name="video-note-backend", daemon=True)
    thread.start()
    return DesktopServerHandle(server=server, thread=thread)


def wait_until_ready(url: str, timeout_seconds: float = 20.0) -> None:
    deadline = time.time() + timeout_seconds
    ready_url = f"{url}/api/ready"
    last_error: Exception | None = None
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(ready_url, timeout=1.5) as response:
                if response.status == 200:
                    return
        except Exception as exc:
            last_error = exc
        time.sleep(0.2)
    raise RuntimeError(f"Backend did not start in time: {last_error}")


def log_error(message: str) -> None:
    if getattr(sys, "frozen", False):
        log_path = Path(sys.executable).resolve().with_suffix(".log")
    else:
        log_path = Path.cwd() / "desktop-launcher.log"
    with log_path.open("a", encoding="utf-8") as log_file:
        log_file.write(message.rstrip())
        log_file.write("\n")


def destroy_other_webview_windows(webview_module, main_window) -> None:
    for window in list(getattr(webview_module, "windows", [])):
        if window is main_window:
            continue
        try:
            window.destroy()
        except Exception:
            log_error("Failed to destroy secondary WebView window.")
            log_error(traceback.format_exc())


def open_window(url: str, server_handle: DesktopServerHandle | None = None) -> None:
    try:
        import webview

        window = webview.create_window(
            APP_TITLE,
            url,
            js_api=DesktopBridge(),
            width=1420,
            height=940,
            min_size=(1040, 720),
        )

        def cleanup_after_close() -> None:
            destroy_other_webview_windows(webview, window)
            if server_handle:
                server_handle.stop(timeout_seconds=0.5)

        window.events.closed += cleanup_after_close
        try:
            webview.start()
        finally:
            cleanup_after_close()
    except Exception:
        log_error("Native WebView failed; falling back to system browser.")
        log_error(traceback.format_exc())
        webbrowser.open(url)
        while True:
            time.sleep(3600)


def main() -> None:
    port = find_free_port()
    url = f"http://{HOST}:{port}"
    server_handle = run_server(port)
    try:
        wait_until_ready(url)
        open_window(url, server_handle)
    finally:
        server_handle.stop()


if __name__ == "__main__":
    try:
        main()
    except Exception:
        log_error(traceback.format_exc())
        raise
