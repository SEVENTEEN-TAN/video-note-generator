from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from collections.abc import Callable

from .ffmpeg_tools import FFmpegCancelled, FFmpegError, extract_grayscale_frames
from .frame_quality import analyze_grayscale_pixels
from .time_utils import clamp_seconds


SCENE_SAMPLE_WIDTH = 64
SCENE_SAMPLE_HEIGHT = 36
SCENE_SAMPLE_OFFSETS = (-1.0, -0.5, 0.0, 0.5, 1.0)
SCENE_DIFFERENCE_SCALE = 0.24


@dataclass(frozen=True)
class FrameStabilityRequest:
    key: str
    anchor_time: float
    lower_bound: float = 0.0
    upper_bound: float | None = None


@dataclass(frozen=True)
class FrameStabilitySelection:
    anchor_time: float
    selected_time: float
    stability_score: float
    transition_score: float
    sample_count: int
    available: bool


def select_stable_frame_times(
    video_path: Path,
    requests: list[FrameStabilityRequest],
    duration: float | None,
    *,
    is_cancelled: Callable[[], bool] | None = None,
) -> dict[str, FrameStabilitySelection]:
    if not requests:
        return {}
    fallback = {request.key: _fallback_selection(request, duration) for request in requests}
    try:
        if not video_path.is_file() or video_path.stat().st_size < 128:
            return fallback
    except OSError:
        return fallback

    sample_times_by_key = {
        request.key: _sample_times(request, duration)
        for request in requests
    }
    all_times = sorted(
        {
            timestamp
            for timestamps in sample_times_by_key.values()
            for timestamp in timestamps
        }
    )
    try:
        samples = extract_grayscale_frames(
            video_path,
            all_times,
            duration,
            width=SCENE_SAMPLE_WIDTH,
            height=SCENE_SAMPLE_HEIGHT,
            is_cancelled=is_cancelled,
        )
    except FFmpegCancelled:
        raise
    except (FFmpegError, OSError, ValueError):
        return fallback

    selections: dict[str, FrameStabilitySelection] = {}
    for request in requests:
        timestamps = sample_times_by_key[request.key]
        available_samples = {
            timestamp: samples[timestamp]
            for timestamp in timestamps
            if timestamp in samples
        }
        selections[request.key] = analyze_stability_samples(
            request,
            available_samples,
            width=SCENE_SAMPLE_WIDTH,
            height=SCENE_SAMPLE_HEIGHT,
            duration=duration,
        )
    return selections


def analyze_stability_samples(
    request: FrameStabilityRequest,
    samples: dict[float, bytes],
    *,
    width: int,
    height: int,
    duration: float | None = None,
) -> FrameStabilitySelection:
    ordered = sorted(samples.items())
    if not ordered:
        return _fallback_selection(request, duration)

    anchor = _clamped_anchor(request, duration)
    window = max(
        0.5,
        max((abs(timestamp - anchor) for timestamp, _pixels in ordered), default=0.5),
    )
    assessed: list[tuple[float, float, float, float, bool]] = []
    for index, (timestamp, pixels) in enumerate(ordered):
        if len(pixels) != width * height:
            continue
        neighbor_differences: list[float] = []
        if index > 0:
            neighbor_differences.append(_mean_absolute_difference(pixels, ordered[index - 1][1]))
        if index + 1 < len(ordered):
            neighbor_differences.append(_mean_absolute_difference(pixels, ordered[index + 1][1]))
        nearest_difference = min(neighbor_differences, default=0.0)
        transition_score = min(1.0, nearest_difference / SCENE_DIFFERENCE_SCALE)
        stability_score = 1.0 - transition_score
        quality = analyze_grayscale_pixels(pixels, width, height)
        proximity = max(0.0, 1.0 - abs(timestamp - anchor) / window)
        severe_risk = any(flag in {"black_frame", "white_frame"} for flag in quality.risk_flags)
        assessed.append(
            (
                timestamp,
                stability_score,
                transition_score,
                quality.score,
                severe_risk,
            )
        )
    if not assessed:
        return _fallback_selection(request, duration)
    anchor_assessment = min(assessed, key=lambda item: abs(item[0] - anchor))
    anchor_is_unstable = anchor_assessment[2] >= 0.45

    ranked: list[tuple[tuple[float, float, float, float], float, float, float]] = []
    for timestamp, stability_score, transition_score, quality_score, severe_risk in assessed:
        proximity = max(0.0, 1.0 - abs(timestamp - anchor) / window)
        post_transition_bonus = (
            0.10
            if (
                anchor_is_unstable
                and timestamp > anchor
                and stability_score >= 0.6
                and quality_score >= 0.5
            )
            else 0.0
        )
        score = (
            quality_score * 0.42
            + stability_score * 0.38
            + proximity * 0.20
            + (0.025 if timestamp >= anchor else 0.0)
            + post_transition_bonus
            - (0.55 if severe_risk else 0.0)
        )
        ranked.append(
            (
                (
                    score,
                    stability_score,
                    quality_score,
                    -abs(timestamp - anchor),
                ),
                timestamp,
                stability_score,
                transition_score,
            )
        )
    _rank, selected_time, stability_score, transition_score = max(ranked, key=lambda item: item[0])
    return FrameStabilitySelection(
        anchor_time=request.anchor_time,
        selected_time=selected_time,
        stability_score=round(stability_score, 3),
        transition_score=round(transition_score, 3),
        sample_count=len(ordered),
        available=True,
    )


def _sample_times(request: FrameStabilityRequest, duration: float | None) -> list[float]:
    anchor = _clamped_anchor(request, duration)
    lower, upper = _time_bounds(request, duration)
    samples: list[float] = []
    for offset in SCENE_SAMPLE_OFFSETS:
        timestamp = round(clamp_seconds(anchor + offset, lower, upper), 3)
        if timestamp not in samples:
            samples.append(timestamp)
    return samples


def _fallback_selection(
    request: FrameStabilityRequest,
    duration: float | None,
) -> FrameStabilitySelection:
    return FrameStabilitySelection(
        anchor_time=request.anchor_time,
        selected_time=_clamped_anchor(request, duration),
        stability_score=0.5,
        transition_score=0.0,
        sample_count=0,
        available=False,
    )


def _clamped_anchor(request: FrameStabilityRequest, duration: float | None) -> float:
    lower, upper = _time_bounds(request, duration)
    return round(clamp_seconds(request.anchor_time, lower, upper), 3)


def _time_bounds(
    request: FrameStabilityRequest,
    duration: float | None,
) -> tuple[float, float]:
    video_lower = 0.25 if duration and duration > 1 else 0.0
    video_upper = max(video_lower, duration - 0.25) if duration and duration > 1 else max(video_lower, request.anchor_time + 1)
    lower = max(video_lower, request.lower_bound)
    requested_upper = request.upper_bound if request.upper_bound is not None else video_upper
    upper = min(video_upper, max(lower, requested_upper))
    return lower, upper


def _mean_absolute_difference(left: bytes, right: bytes) -> float:
    if not left or len(left) != len(right):
        return 1.0
    return sum(abs(left_value - right_value) for left_value, right_value in zip(left, right)) / (
        len(left) * 255.0
    )
