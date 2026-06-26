from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import imageio_ffmpeg

from .time_utils import clamp_seconds


class FFmpegError(RuntimeError):
    pass


def get_ffmpeg_path() -> str | None:
    system_path = shutil.which("ffmpeg")
    if system_path:
        return system_path
    try:
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return None


def require_ffmpeg() -> str:
    ffmpeg_path = get_ffmpeg_path()
    if not ffmpeg_path:
        raise FFmpegError("FFmpeg is not available. Install dependencies and restart the backend.")
    return ffmpeg_path


def run_ffmpeg(args: list[str]) -> subprocess.CompletedProcess[str]:
    ffmpeg_path = require_ffmpeg()
    completed = subprocess.run(
        [ffmpeg_path, *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if completed.returncode != 0:
        message = completed.stderr.strip() or completed.stdout.strip() or "FFmpeg command failed."
        raise FFmpegError(message[-2000:])
    return completed


def probe_duration(video_path: Path) -> float | None:
    ffmpeg_path = require_ffmpeg()
    completed = subprocess.run(
        [ffmpeg_path, "-hide_banner", "-i", str(video_path)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    text = f"{completed.stderr}\n{completed.stdout}"
    match = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", text)
    if not match:
        return None
    hours, minutes, seconds = match.groups()
    return int(hours) * 3600 + int(minutes) * 60 + float(seconds)


def extract_mp3(video_path: Path, audio_path: Path) -> None:
    run_ffmpeg(
        [
            "-y",
            "-hide_banner",
            "-i",
            str(video_path),
            "-vn",
            "-codec:a",
            "libmp3lame",
            "-ar",
            "44100",
            "-ac",
            "2",
            "-b:a",
            "192k",
            str(audio_path),
        ]
    )
    if not audio_path.exists() or audio_path.stat().st_size == 0:
        raise FFmpegError("MP3 extraction produced no output. The video may not contain an audio track.")


def split_audio(audio_path: Path, chunks_dir: Path, segment_seconds: int = 600) -> list[Path]:
    chunks_dir.mkdir(parents=True, exist_ok=True)
    for old_chunk in chunks_dir.glob("chunk_*.mp3"):
        old_chunk.unlink()
    run_ffmpeg(
        [
            "-y",
            "-hide_banner",
            "-i",
            str(audio_path),
            "-vn",
            "-codec:a",
            "libmp3lame",
            "-ar",
            "16000",
            "-ac",
            "1",
            "-b:a",
            "64k",
            "-f",
            "segment",
            "-segment_time",
            str(segment_seconds),
            "-reset_timestamps",
            "1",
            str(chunks_dir / "chunk_%03d.mp3"),
        ]
    )
    chunks = sorted(chunks_dir.glob("chunk_*.mp3"))
    if not chunks:
        raise FFmpegError("Audio splitting produced no chunks.")
    return chunks


def extract_frame(video_path: Path, output_path: Path, timestamp: float, duration: float | None) -> float:
    safe_time = max(0, timestamp)
    if duration and duration > 1:
        safe_time = clamp_seconds(safe_time, 0.25, max(0.25, duration - 0.25))
    output_path.parent.mkdir(parents=True, exist_ok=True)

    errors: list[str] = []
    for candidate_time in _frame_seek_candidates(safe_time):
        if output_path.exists():
            output_path.unlink()
        try:
            run_ffmpeg(
                [
                    "-y",
                    "-hide_banner",
                    "-ss",
                    f"{candidate_time:.3f}",
                    "-i",
                    str(video_path),
                    "-frames:v",
                    "1",
                    "-q:v",
                    "2",
                    str(output_path),
                ]
            )
        except FFmpegError as exc:
            errors.append(f"{candidate_time:.3f}s: {exc}")
            continue
        if output_path.exists() and output_path.stat().st_size > 0:
            return candidate_time
        errors.append(f"{candidate_time:.3f}s: no output")

    attempted = ", ".join(f"{candidate:.3f}s" for candidate in _frame_seek_candidates(safe_time))
    detail = errors[-1] if errors else "unknown error"
    raise FFmpegError(f"Frame extraction failed after trying {attempted}. Last error: {detail}")


def _frame_seek_candidates(safe_time: float) -> list[float]:
    candidates = [safe_time]
    if safe_time > 0:
        candidates.extend([max(0.0, safe_time - 0.5), 0.0])

    unique: list[float] = []
    for candidate in candidates:
        if not any(abs(candidate - existing) < 0.001 for existing in unique):
            unique.append(candidate)
    return unique
