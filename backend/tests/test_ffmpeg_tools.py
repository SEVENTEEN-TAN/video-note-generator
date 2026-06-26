from __future__ import annotations

import subprocess
import sys

import pytest

from backend.app import ffmpeg_tools
from backend.app.ffmpeg_tools import FFmpegError, extract_frame, get_ffmpeg_path, probe_duration, run_ffmpeg


def test_get_ffmpeg_path_prefers_bundled_binary_when_frozen(monkeypatch) -> None:
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(ffmpeg_tools.shutil, "which", lambda _name: "C:/system/ffmpeg.exe")
    monkeypatch.setattr(ffmpeg_tools.imageio_ffmpeg, "get_ffmpeg_exe", lambda: "D:/app/_internal/ffmpeg.exe")

    assert get_ffmpeg_path() == "D:/app/_internal/ffmpeg.exe"


def test_run_ffmpeg_retries_windows_startup_failure(monkeypatch) -> None:
    attempts: list[list[str]] = []
    startup_failure = subprocess.CompletedProcess(
        ["ffmpeg"],
        -1073741502,
        stdout="",
        stderr="",
    )
    success = subprocess.CompletedProcess(["ffmpeg"], 0, stdout="ok", stderr="")
    responses = iter([startup_failure, success])

    def fake_run(command, **_kwargs):
        attempts.append(command)
        return next(responses)

    monkeypatch.setattr(ffmpeg_tools, "require_ffmpeg", lambda: "ffmpeg")
    monkeypatch.setattr(ffmpeg_tools.subprocess, "run", fake_run)

    completed = run_ffmpeg(["-version"])

    assert completed.returncode == 0
    assert len(attempts) == 2


def test_extract_frame_falls_back_when_short_video_seek_has_no_frame(tmp_path) -> None:
    video_path = tmp_path / "short.mp4"
    frame_path = tmp_path / "frame.jpg"

    try:
        run_ffmpeg(
            [
                "-y",
                "-f",
                "lavfi",
                "-i",
                "testsrc=size=160x90:rate=1",
                "-t",
                "0.3",
                "-pix_fmt",
                "yuv420p",
                "-c:v",
                "libx264",
                str(video_path),
            ]
        )
    except FFmpegError as exc:
        pytest.skip(f"FFmpeg test video generation is unavailable: {exc}")

    actual_time = extract_frame(video_path, frame_path, 0.25, probe_duration(video_path))

    assert actual_time == pytest.approx(0)
    assert frame_path.exists()
    assert frame_path.stat().st_size > 0
