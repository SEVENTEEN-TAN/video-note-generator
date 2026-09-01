from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

from .storage_policy import available_storage_bytes


DEFAULT_MAX_VIDEO_UPLOAD_BYTES = 20 * 1024**3
DEFAULT_MAX_SUBTITLE_UPLOAD_BYTES = 16 * 1024**2
DEFAULT_MINIMUM_FREE_BYTES = 256 * 1024**2
MULTIPART_OVERHEAD_BYTES = 1024**2


class UploadConfigurationError(ValueError):
    pass


class UploadTooLargeError(ValueError):
    pass


class InsufficientUploadStorageError(OSError):
    pass


@dataclass(frozen=True)
class UploadLimits:
    max_video_bytes: int
    max_subtitle_bytes: int
    minimum_free_bytes: int


def get_upload_limits() -> UploadLimits:
    return UploadLimits(
        max_video_bytes=_positive_env_bytes(
            "VIDEO_NOTE_MAX_VIDEO_UPLOAD_BYTES",
            DEFAULT_MAX_VIDEO_UPLOAD_BYTES,
        ),
        max_subtitle_bytes=_positive_env_bytes(
            "VIDEO_NOTE_MAX_SUBTITLE_UPLOAD_BYTES",
            DEFAULT_MAX_SUBTITLE_UPLOAD_BYTES,
        ),
        minimum_free_bytes=_non_negative_env_bytes(
            "VIDEO_NOTE_UPLOAD_MIN_FREE_BYTES",
            DEFAULT_MINIMUM_FREE_BYTES,
        ),
    )


def validate_declared_upload_size(
    declared_size: int | None,
    *,
    max_bytes: int,
    label: str,
) -> None:
    if declared_size is None:
        return
    size = max(0, int(declared_size))
    if size > max_bytes:
        raise UploadTooLargeError(
            f"{label} upload exceeds the {_format_bytes(max_bytes)} limit."
        )


def ensure_upload_capacity(
    target_root: Path,
    *,
    declared_bytes: int,
    minimum_free_bytes: int,
) -> None:
    available = available_storage_bytes(target_root)
    required = max(0, int(declared_bytes)) + max(0, int(minimum_free_bytes))
    if available < required:
        shortfall = required - available
        raise InsufficientUploadStorageError(
            f"Insufficient disk space for upload. Free at least {shortfall} more bytes."
        )


def max_upload_request_bytes(path: str, limits: UploadLimits) -> int | None:
    if path == "/api/jobs/frame-suggestion":
        return limits.max_video_bytes + MULTIPART_OVERHEAD_BYTES
    if path == "/api/jobs":
        return (
            limits.max_video_bytes
            + limits.max_subtitle_bytes
            + MULTIPART_OVERHEAD_BYTES
        )
    return None


def copy_upload_stream(
    source: BinaryIO,
    destination: BinaryIO,
    *,
    max_bytes: int,
    label: str,
) -> int:
    limited_source = _LimitedUploadReader(source, max_bytes=max_bytes, label=label)
    shutil.copyfileobj(limited_source, destination)
    return limited_source.bytes_read


class _LimitedUploadReader:
    def __init__(self, source: BinaryIO, *, max_bytes: int, label: str) -> None:
        self.source = source
        self.max_bytes = max(0, int(max_bytes))
        self.label = label
        self.bytes_read = 0

    def read(self, size: int = -1) -> bytes:
        chunk = self.source.read(size)
        if not chunk:
            return b""
        self.bytes_read += len(chunk)
        if self.bytes_read > self.max_bytes:
            raise UploadTooLargeError(
                f"{self.label} upload exceeds the {_format_bytes(self.max_bytes)} limit."
            )
        return chunk


def _positive_env_bytes(name: str, default: int) -> int:
    value = _environment_integer(name, default)
    if value <= 0:
        raise UploadConfigurationError(f"{name} must be greater than zero.")
    return value


def _non_negative_env_bytes(name: str, default: int) -> int:
    value = _environment_integer(name, default)
    if value < 0:
        raise UploadConfigurationError(f"{name} must be zero or greater.")
    return value


def _environment_integer(name: str, default: int) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise UploadConfigurationError(f"{name} must be an integer number of bytes.") from exc


def _format_bytes(value: int) -> str:
    size = float(max(0, value))
    for unit in ("bytes", "KiB", "MiB", "GiB", "TiB"):
        if size < 1024 or unit == "TiB":
            return f"{size:.0f} {unit}" if unit == "bytes" else f"{size:.2f} {unit}"
        size /= 1024
    return f"{value} bytes"
