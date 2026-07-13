from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from backend.app import ffmpeg_tools
from backend.app.ffmpeg_tools import (
    FFmpegError,
    extract_frame,
    get_ffmpeg_path,
    prepare_audio_artifacts,
    probe_duration,
    run_ffmpeg,
)


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


def test_prepare_long_local_audio_uses_one_source_read_and_flac_chunks(tmp_path, monkeypatch) -> None:
    video_path = Path("input.mp4")
    mp3_path = tmp_path / "audio.mp3"
    asr_dir = tmp_path / "work" / "asr"
    commands: list[list[str]] = []

    monkeypatch.setattr(
        ffmpeg_tools,
        "probe_duration",
        lambda path: (_ for _ in ()).throw(AssertionError(f"unexpected duration probe: {path}")),
    )

    def fake_run(args: list[str]):
        commands.append(args)
        mp3_path.write_bytes(b"mp3")
        chunks_dir = asr_dir / "chunks"
        chunks_dir.mkdir(parents=True, exist_ok=True)
        (chunks_dir / "chunk_000.flac").write_bytes(b"first")
        (chunks_dir / "chunk_001.flac").write_bytes(b"second")
        return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

    monkeypatch.setattr(ffmpeg_tools, "run_ffmpeg", fake_run)

    prepared = prepare_audio_artifacts(
        video_path,
        mp3_path,
        asr_dir,
        chunk_seconds=600,
        duration_seconds=1200.0,
    )

    assert len(commands) == 1
    command = commands[0]
    assert command[command.index("-i") + 1] == str(video_path)
    assert command.count("-i") == 1
    assert "libmp3lame" in command
    assert "flac" in command
    assert "segment" in command
    assert [chunk.path.suffix for chunk in prepared.chunks] == [".flac", ".flac"]
    assert [(chunk.start, chunk.end) for chunk in prepared.chunks] == [(0.0, 600.0), (600.0, 1200.0)]


def test_prepare_short_local_audio_creates_one_flac_chunk(tmp_path, monkeypatch) -> None:
    video_path = Path("short.mp4")
    mp3_path = tmp_path / "audio.mp3"
    asr_dir = tmp_path / "work" / "asr"

    monkeypatch.setattr(
        ffmpeg_tools,
        "probe_duration",
        lambda path: (_ for _ in ()).throw(AssertionError(f"unexpected duration probe: {path}")),
    )

    def fake_run(args: list[str]):
        mp3_path.write_bytes(b"mp3")
        chunk_path = asr_dir / "chunks" / "chunk_000.flac"
        chunk_path.parent.mkdir(parents=True, exist_ok=True)
        chunk_path.write_bytes(b"flac")
        return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

    monkeypatch.setattr(ffmpeg_tools, "run_ffmpeg", fake_run)

    prepared = prepare_audio_artifacts(
        video_path,
        mp3_path,
        asr_dir,
        chunk_seconds=0,
        duration_seconds=900.0,
    )

    assert len(prepared.chunks) == 1
    assert prepared.chunks[0].path.name == "chunk_000.flac"
    assert (prepared.chunks[0].start, prepared.chunks[0].end) == (0.0, 900.0)


def test_prepare_audio_removes_stale_flac_chunks_before_build(tmp_path, monkeypatch) -> None:
    video_path = Path("input.mp4")
    mp3_path = tmp_path / "audio.mp3"
    asr_dir = tmp_path / "work" / "asr"
    chunks_dir = asr_dir / "chunks"
    chunks_dir.mkdir(parents=True)
    (chunks_dir / "chunk_009.flac").write_bytes(b"stale")

    monkeypatch.setattr(ffmpeg_tools, "probe_duration", lambda _path: 600.0)

    def fake_run(args: list[str]):
        mp3_path.write_bytes(b"mp3")
        (chunks_dir / "chunk_000.flac").write_bytes(b"fresh")
        return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

    monkeypatch.setattr(ffmpeg_tools, "run_ffmpeg", fake_run)

    prepared = prepare_audio_artifacts(video_path, mp3_path, asr_dir, chunk_seconds=600)

    assert [chunk.path.name for chunk in prepared.chunks] == ["chunk_000.flac"]
    assert not (chunks_dir / "chunk_009.flac").exists()


def test_prepare_audio_rejects_any_empty_flac_chunk(tmp_path, monkeypatch) -> None:
    video_path = Path("input.mp4")
    mp3_path = tmp_path / "audio.mp3"
    asr_dir = tmp_path / "work" / "asr"

    def fake_run(args: list[str]):
        mp3_path.write_bytes(b"mp3")
        chunks_dir = asr_dir / "chunks"
        chunks_dir.mkdir(parents=True, exist_ok=True)
        (chunks_dir / "chunk_000.flac").write_bytes(b"first")
        (chunks_dir / "chunk_001.flac").write_bytes(b"")
        return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

    monkeypatch.setattr(ffmpeg_tools, "run_ffmpeg", fake_run)

    with pytest.raises(FFmpegError, match="empty FLAC chunk"):
        prepare_audio_artifacts(
            video_path,
            mp3_path,
            asr_dir,
            chunk_seconds=600,
            duration_seconds=1200.0,
        )


def test_prepare_audio_sorts_chunk_names_by_numeric_index(tmp_path, monkeypatch) -> None:
    video_path = Path("input.mp4")
    mp3_path = tmp_path / "audio.mp3"
    asr_dir = tmp_path / "work" / "asr"

    def fake_run(args: list[str]):
        mp3_path.write_bytes(b"mp3")
        chunks_dir = asr_dir / "chunks"
        chunks_dir.mkdir(parents=True, exist_ok=True)
        (chunks_dir / "chunk_1000.flac").write_bytes(b"later")
        (chunks_dir / "chunk_999.flac").write_bytes(b"earlier")
        return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

    monkeypatch.setattr(ffmpeg_tools, "run_ffmpeg", fake_run)

    prepared = prepare_audio_artifacts(
        video_path,
        mp3_path,
        asr_dir,
        chunk_seconds=600,
        duration_seconds=1001 * 600.0,
    )

    assert [chunk.index for chunk in prepared.chunks] == [999, 1000]
    assert [chunk.path.name for chunk in prepared.chunks] == ["chunk_999.flac", "chunk_1000.flac"]
