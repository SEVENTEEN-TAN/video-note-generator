from __future__ import annotations

from io import BytesIO

import pytest

from backend.app import upload_limits
from backend.app.upload_limits import (
    InsufficientUploadStorageError,
    UploadConfigurationError,
    UploadTooLargeError,
    copy_upload_stream,
    ensure_upload_capacity,
    get_upload_limits,
    max_upload_request_bytes,
)


def test_upload_limits_support_environment_overrides(monkeypatch) -> None:
    monkeypatch.setenv("VIDEO_NOTE_MAX_VIDEO_UPLOAD_BYTES", "100")
    monkeypatch.setenv("VIDEO_NOTE_MAX_SUBTITLE_UPLOAD_BYTES", "20")
    monkeypatch.setenv("VIDEO_NOTE_UPLOAD_MIN_FREE_BYTES", "0")

    limits = get_upload_limits()

    assert limits.max_video_bytes == 100
    assert limits.max_subtitle_bytes == 20
    assert limits.minimum_free_bytes == 0


def test_upload_limits_reject_invalid_environment_values(monkeypatch) -> None:
    monkeypatch.setenv("VIDEO_NOTE_MAX_VIDEO_UPLOAD_BYTES", "not-a-number")

    with pytest.raises(UploadConfigurationError, match="must be an integer"):
        get_upload_limits()


def test_copy_upload_stream_enforces_limit_before_writing_oversized_chunk() -> None:
    destination = BytesIO()

    with pytest.raises(UploadTooLargeError, match="Video upload exceeds"):
        copy_upload_stream(
            BytesIO(b"12345"),
            destination,
            max_bytes=4,
            label="Video",
        )

    assert len(destination.getvalue()) <= 4


def test_copy_upload_stream_returns_written_byte_count() -> None:
    destination = BytesIO()

    copied = copy_upload_stream(
        BytesIO(b"1234"),
        destination,
        max_bytes=4,
        label="Video",
    )

    assert copied == 4
    assert destination.getvalue() == b"1234"


def test_upload_capacity_reserves_configured_free_space(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(upload_limits, "available_storage_bytes", lambda _path: 100)

    with pytest.raises(InsufficientUploadStorageError, match="10 more bytes"):
        ensure_upload_capacity(
            tmp_path,
            declared_bytes=80,
            minimum_free_bytes=30,
        )


def test_multipart_request_limits_include_bounded_overhead() -> None:
    limits = upload_limits.UploadLimits(
        max_video_bytes=100,
        max_subtitle_bytes=20,
        minimum_free_bytes=0,
    )

    frame_limit = max_upload_request_bytes("/api/jobs/frame-suggestion", limits)
    job_limit = max_upload_request_bytes("/api/jobs", limits)

    assert frame_limit is not None and frame_limit > limits.max_video_bytes
    assert job_limit is not None and job_limit > frame_limit
    assert max_upload_request_bytes("/api/health", limits) is None
