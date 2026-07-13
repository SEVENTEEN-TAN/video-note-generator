from __future__ import annotations

import math
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import imageio_ffmpeg

from .time_utils import clamp_seconds
from .transcription_checkpoints import ChunkSpec


class FFmpegError(RuntimeError):
    pass


@dataclass(frozen=True)
class PreparedAudio:
    mp3_path: Path
    chunks: list[ChunkSpec]
    duration: float


def get_ffmpeg_path() -> str | None:
    if getattr(sys, "frozen", False):
        bundled_path = _get_bundled_ffmpeg_path()
        if bundled_path:
            return bundled_path
        return shutil.which("ffmpeg")

    system_path = shutil.which("ffmpeg")
    if system_path:
        return system_path
    return _get_bundled_ffmpeg_path()


def _get_bundled_ffmpeg_path() -> str | None:
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
    completed = _run_ffmpeg_process_with_startup_retries([ffmpeg_path, *args])
    if completed.returncode != 0:
        message = completed.stderr.strip() or completed.stdout.strip() or "FFmpeg command failed."
        raise FFmpegError(message[-2000:])
    return completed


def probe_duration(video_path: Path) -> float | None:
    ffmpeg_path = require_ffmpeg()
    completed = _run_ffmpeg_process_with_startup_retries([ffmpeg_path, "-hide_banner", "-i", str(video_path)])
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


def prepare_audio_artifacts(
    video_path: Path,
    mp3_path: Path,
    asr_dir: Path,
    chunk_seconds: int,
    *,
    duration_seconds: float | None = None,
) -> PreparedAudio:
    """Create the public MP3 and local-ASR FLAC input from one source read."""

    mp3_path.parent.mkdir(parents=True, exist_ok=True)
    chunks_dir = asr_dir / "chunks"
    chunks_dir.mkdir(parents=True, exist_ok=True)
    for old_chunk in chunks_dir.glob("chunk_*.flac"):
        old_chunk.unlink()

    asr_args = [
        "-map",
        "0:a:0",
        "-vn",
        "-codec:a",
        "flac",
        "-ar",
        "16000",
        "-ac",
        "1",
    ]
    if chunk_seconds > 0:
        asr_args.extend(
            [
                "-f",
                "segment",
                "-segment_time",
                str(chunk_seconds),
                "-reset_timestamps",
                "1",
                str(chunks_dir / "chunk_%03d.flac"),
            ]
        )
    else:
        asr_args.append(str(chunks_dir / "chunk_000.flac"))

    run_ffmpeg(
        [
            "-y",
            "-hide_banner",
            "-i",
            str(video_path),
            "-map",
            "0:a:0",
            "-vn",
            "-codec:a",
            "libmp3lame",
            "-ar",
            "44100",
            "-ac",
            "2",
            "-b:a",
            "192k",
            str(mp3_path),
            *asr_args,
        ]
    )

    if not mp3_path.exists() or mp3_path.stat().st_size == 0:
        raise FFmpegError("MP3 extraction produced no output. The video may not contain an audio track.")
    chunk_paths = sorted(chunks_dir.glob("chunk_*.flac"), key=_flac_chunk_index)
    if not chunk_paths:
        raise FFmpegError("Local ASR audio preparation produced no FLAC chunks.")
    empty_chunks = [path.name for path in chunk_paths if path.stat().st_size == 0]
    if empty_chunks:
        raise FFmpegError(f"Local ASR audio preparation produced an empty FLAC chunk: {', '.join(empty_chunks)}")

    duration_known = duration_seconds is not None
    duration = max(0.0, float(duration_seconds if duration_known else 0.0))
    chunks: list[ChunkSpec] = []
    for chunk_path in chunk_paths:
        index = _flac_chunk_index(chunk_path)
        if duration_known:
            start = float(index * chunk_seconds) if chunk_seconds > 0 else 0.0
            end = min(duration, start + chunk_seconds) if chunk_seconds > 0 else duration
        else:
            start = float(index * chunk_seconds) if chunk_seconds > 0 else 0.0
            measured = float(
                probe_duration(chunk_path)
                or (duration if len(chunk_paths) == 1 else chunk_seconds)
                or 0.0
            )
            end = start + measured
        chunks.append(ChunkSpec(index=index, start=start, end=max(start, end), path=chunk_path))

    resolved_duration = duration if duration_known else max((chunk.end for chunk in chunks), default=0.0)
    return PreparedAudio(mp3_path=mp3_path, chunks=chunks, duration=resolved_duration)


def load_prepared_audio_artifacts(
    mp3_path: Path,
    asr_dir: Path,
    chunk_seconds: int,
    *,
    duration_seconds: float,
) -> PreparedAudio:
    """Validate and reuse local-ASR artifacts without changing checkpoint signatures."""

    if not mp3_path.exists() or mp3_path.stat().st_size == 0:
        raise FFmpegError("Reusable MP3 audio is missing or empty.")
    chunk_paths = sorted((asr_dir / "chunks").glob("chunk_*.flac"), key=_flac_chunk_index)
    if not chunk_paths:
        raise FFmpegError("Reusable local ASR chunks are missing.")
    indexes = [_flac_chunk_index(path) for path in chunk_paths]
    if indexes != list(range(len(indexes))):
        raise FFmpegError("Reusable local ASR chunks are incomplete or non-contiguous.")
    if chunk_seconds <= 0 and len(chunk_paths) != 1:
        raise FFmpegError("Reusable unchunked local ASR audio must contain exactly one FLAC file.")
    empty_chunks = [path.name for path in chunk_paths if path.stat().st_size == 0]
    if empty_chunks:
        raise FFmpegError(f"Reusable local ASR audio contains an empty FLAC chunk: {', '.join(empty_chunks)}")

    duration = max(0.0, float(duration_seconds))
    expected_chunk_count = 1 if chunk_seconds <= 0 else max(1, math.ceil(duration / chunk_seconds))
    if len(chunk_paths) != expected_chunk_count:
        raise FFmpegError(
            f"Reusable local ASR chunk count does not match the current plan: "
            f"expected {expected_chunk_count}, found {len(chunk_paths)}."
        )
    chunks = []
    for index, chunk_path in enumerate(chunk_paths):
        start = float(index * chunk_seconds) if chunk_seconds > 0 else 0.0
        end = min(duration, start + chunk_seconds) if chunk_seconds > 0 else duration
        chunks.append(ChunkSpec(index=index, start=start, end=max(start, end), path=chunk_path))
    if duration > 0 and chunks[-1].start >= duration:
        raise FFmpegError("Reusable local ASR chunks do not match the current duration or chunk plan.")
    return PreparedAudio(mp3_path=mp3_path, chunks=chunks, duration=duration)


def _flac_chunk_index(path: Path) -> int:
    match = re.fullmatch(r"chunk_(\d+)\.flac", path.name)
    if not match:
        raise FFmpegError(f"Invalid local ASR chunk filename: {path.name}")
    return int(match.group(1))


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


def _run_ffmpeg_process_with_startup_retries(command: list[str]) -> subprocess.CompletedProcess[str]:
    completed: subprocess.CompletedProcess[str] | None = None
    for attempt in range(3):
        completed = _run_ffmpeg_process(command)
        if not _is_windows_startup_failure(completed.returncode):
            return completed
        if attempt < 2:
            time.sleep(0.25 * (attempt + 1))
    if completed is None:
        raise FFmpegError("FFmpeg command failed.")
    return completed


def _run_ffmpeg_process(command: list[str]) -> subprocess.CompletedProcess[str]:
    _suppress_windows_error_dialogs()
    kwargs: dict = {
        "capture_output": True,
        "text": True,
        "encoding": "utf-8",
        "errors": "replace",
    }
    if sys.platform == "win32":
        kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
    return subprocess.run(command, **kwargs)


def _is_windows_startup_failure(returncode: int) -> bool:
    return returncode in {-1073741502, 3221225794}


def _suppress_windows_error_dialogs() -> None:
    if sys.platform != "win32":
        return
    try:
        import ctypes

        sem_failcriticalerrors = 0x0001
        sem_nogpfault_errorbox = 0x0002
        sem_noopenfile_errorbox = 0x8000
        ctypes.windll.kernel32.SetErrorMode(
            sem_failcriticalerrors | sem_nogpfault_errorbox | sem_noopenfile_errorbox
        )
    except Exception:
        return
