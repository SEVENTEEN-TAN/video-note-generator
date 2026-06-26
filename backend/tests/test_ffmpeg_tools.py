from __future__ import annotations

import pytest

from backend.app.ffmpeg_tools import FFmpegError, extract_frame, probe_duration, run_ffmpeg


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
