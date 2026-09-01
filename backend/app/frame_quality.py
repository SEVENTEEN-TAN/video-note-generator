from __future__ import annotations

import math
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from .ffmpeg_tools import require_ffmpeg


SAMPLE_WIDTH = 96
SAMPLE_HEIGHT = 54
DARK_PIXEL = 18
BRIGHT_PIXEL = 238


@dataclass(frozen=True)
class FrameVisualQuality:
    available: bool
    score: float
    brightness: float | None
    contrast: float | None
    sharpness: float | None
    dark_ratio: float | None
    bright_ratio: float | None
    risk_flags: tuple[str, ...]


def analyze_frame_visual_quality(path: Path) -> FrameVisualQuality:
    try:
        with path.open("rb") as stream:
            header = stream.read(12)
    except OSError:
        header = b""
    if not (
        header.startswith(b"\xff\xd8\xff")
        or header.startswith(b"\x89PNG\r\n\x1a\n")
        or (header.startswith(b"RIFF") and header[8:12] == b"WEBP")
    ):
        return _unavailable_quality()
    pixels = _read_grayscale_pixels(path, SAMPLE_WIDTH, SAMPLE_HEIGHT)
    if len(pixels) != SAMPLE_WIDTH * SAMPLE_HEIGHT:
        return _unavailable_quality()
    return analyze_grayscale_pixels(pixels, SAMPLE_WIDTH, SAMPLE_HEIGHT)


def analyze_grayscale_pixels(pixels: bytes, width: int, height: int) -> FrameVisualQuality:
    expected = width * height
    if width < 3 or height < 3 or len(pixels) != expected:
        raise ValueError("Grayscale sample dimensions do not match the pixel payload.")

    count = len(pixels)
    mean = sum(pixels) / count
    variance = sum((pixel - mean) ** 2 for pixel in pixels) / count
    brightness = mean / 255.0
    contrast = math.sqrt(variance) / 255.0
    dark_ratio = sum(pixel <= DARK_PIXEL for pixel in pixels) / count
    bright_ratio = sum(pixel >= BRIGHT_PIXEL for pixel in pixels) / count
    sharpness = _laplacian_energy(pixels, width, height)

    flags: list[str] = []
    if brightness <= 0.07 or dark_ratio >= 0.90:
        flags.append("black_frame")
    elif brightness < 0.18 or dark_ratio >= 0.65:
        flags.append("underexposed")
    if brightness >= 0.95 or bright_ratio >= 0.90:
        flags.append("white_frame")
    elif brightness > 0.88 or bright_ratio >= 0.65:
        flags.append("overexposed")
    if contrast < 0.055:
        flags.append("low_contrast")
    if sharpness < 0.075:
        flags.append("blurry_frame")

    penalty = 0.0
    penalty += 0.65 if "black_frame" in flags or "white_frame" in flags else 0.0
    penalty += 0.20 if "underexposed" in flags or "overexposed" in flags else 0.0
    penalty += 0.18 if "low_contrast" in flags else 0.0
    penalty += 0.27 if "blurry_frame" in flags else 0.0
    exposure_balance = max(0.0, 1.0 - abs(brightness - 0.5) * 1.6)
    base_score = 0.45 * min(1.0, sharpness / 0.30) + 0.30 * min(1.0, contrast / 0.22) + 0.25 * exposure_balance
    score = max(0.0, min(1.0, base_score - penalty))

    return FrameVisualQuality(
        available=True,
        score=round(score, 3),
        brightness=round(brightness, 3),
        contrast=round(contrast, 3),
        sharpness=round(sharpness, 3),
        dark_ratio=round(dark_ratio, 3),
        bright_ratio=round(bright_ratio, 3),
        risk_flags=tuple(flags),
    )


def _laplacian_energy(pixels: bytes, width: int, height: int) -> float:
    values: list[int] = []
    for row in range(1, height - 1):
        offset = row * width
        for column in range(1, width - 1):
            index = offset + column
            laplacian = (
                4 * pixels[index]
                - pixels[index - 1]
                - pixels[index + 1]
                - pixels[index - width]
                - pixels[index + width]
            )
            values.append(laplacian)
    if not values:
        return 0.0
    root_mean_square = math.sqrt(sum(value * value for value in values) / len(values))
    return min(1.0, root_mean_square / 255.0)


def _unavailable_quality() -> FrameVisualQuality:
    return FrameVisualQuality(
        available=False,
        score=0.5,
        brightness=None,
        contrast=None,
        sharpness=None,
        dark_ratio=None,
        bright_ratio=None,
        risk_flags=(),
    )


def _read_grayscale_pixels(path: Path, width: int, height: int) -> bytes:
    ffmpeg_path = require_ffmpeg()
    command = [
        ffmpeg_path,
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        str(path),
        "-vf",
        f"scale={width}:{height},format=gray",
        "-frames:v",
        "1",
        "-f",
        "rawvideo",
        "pipe:1",
    ]
    kwargs: dict[str, object] = {"capture_output": True}
    if sys.platform == "win32":
        kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
    try:
        completed = subprocess.run(command, **kwargs)
    except OSError:
        return b""
    if completed.returncode != 0:
        return b""
    return completed.stdout[: width * height]
