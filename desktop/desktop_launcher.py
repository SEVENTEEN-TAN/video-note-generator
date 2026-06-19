from __future__ import annotations

import socket
import sys
import threading
import time
import traceback
import urllib.request
import webbrowser
from pathlib import Path

import uvicorn

from backend.app.main import app


APP_TITLE = "视频笔记生成器"
HOST = "127.0.0.1"


def find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind((HOST, 0))
        return int(sock.getsockname()[1])


def run_server(port: int) -> uvicorn.Server:
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
    return server


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


def open_window(url: str) -> None:
    try:
        import webview
        webview.create_window(
            APP_TITLE,
            url,
            width=1420,
            height=940,
            min_size=(1040, 720),
        )
        webview.start()
    except Exception:
        log_error("Native WebView failed; falling back to system browser.")
        log_error(traceback.format_exc())
        webbrowser.open(url)
        while True:
            time.sleep(3600)


def main() -> None:
    port = find_free_port()
    url = f"http://{HOST}:{port}"
    server = run_server(port)
    try:
        wait_until_ready(url)
        open_window(url)
    finally:
        server.should_exit = True


if __name__ == "__main__":
    try:
        main()
    except Exception:
        log_error(traceback.format_exc())
        raise
