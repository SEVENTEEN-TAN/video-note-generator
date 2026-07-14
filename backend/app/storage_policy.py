from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class StorageEstimate:
    source_bytes: int
    mp3_bytes: int
    asr_work_bytes: int
    frame_bytes: int
    zip_bytes: int
    temporary_headroom_bytes: int
    required_free_bytes: int


@dataclass(frozen=True)
class JobStorageUsage:
    total_bytes: int
    cache_bytes: int
    final_bytes: int


def estimate_local_job_storage(
    *,
    source_bytes: int,
    duration_seconds: float,
    frame_limit: int,
) -> StorageEstimate:
    source_size = max(0, int(source_bytes))
    duration = max(0.0, float(duration_seconds))
    frames = max(1, int(frame_limit))
    mp3_bytes = int(duration * 24_000)  # 192 kbps
    asr_work_bytes = int(duration * 64_000)  # conservative 16 kHz mono FLAC allowance
    frame_bytes = frames * 3 * 350_000  # candidate previews plus selected frames
    zip_bytes = mp3_bytes + frame_bytes + 5 * 1024 * 1024
    temporary_headroom_bytes = max(256 * 1024 * 1024, int((mp3_bytes + asr_work_bytes) * 0.2))
    required = mp3_bytes + asr_work_bytes + frame_bytes + zip_bytes + temporary_headroom_bytes
    return StorageEstimate(
        source_bytes=source_size,
        mp3_bytes=mp3_bytes,
        asr_work_bytes=asr_work_bytes,
        frame_bytes=frame_bytes,
        zip_bytes=zip_bytes,
        temporary_headroom_bytes=temporary_headroom_bytes,
        required_free_bytes=required,
    )


def job_storage_usage(job_dir: Path) -> JobStorageUsage:
    root = job_dir.resolve()
    cache_root = (root / "work" / "asr").resolve()
    total_bytes = 0
    cache_bytes = 0
    if root.exists():
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            try:
                size = path.stat().st_size
                resolved = path.resolve()
            except OSError:
                continue
            total_bytes += size
            if _is_within(resolved, cache_root):
                cache_bytes += size
    return JobStorageUsage(
        total_bytes=total_bytes,
        cache_bytes=cache_bytes,
        final_bytes=max(0, total_bytes - cache_bytes),
    )


def cleanup_transcription_cache(job_dir: Path) -> int:
    root = job_dir.resolve()
    cache_root = (root / "work" / "asr").resolve()
    if not _is_within(cache_root, root) or cache_root == root:
        raise ValueError("Transcription cache path escapes the job directory.")
    before = _directory_size(cache_root)
    if cache_root.exists():
        shutil.rmtree(cache_root)
    return before


def available_storage_bytes(path: Path) -> int:
    target = path if path.exists() else path.parent
    return int(shutil.disk_usage(target).free)


def _directory_size(root: Path) -> int:
    total = 0
    if not root.exists():
        return 0
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        try:
            total += path.stat().st_size
        except OSError:
            continue
    return total


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False
