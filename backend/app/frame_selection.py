from __future__ import annotations

from .models import Chapter, KeyMoment, NoteDraft
from .time_utils import clamp_seconds


DEFAULT_DEDUP_WINDOW_SECONDS = 4.0


def select_key_frame_moments(
    draft: NoteDraft,
    duration: float | None,
    frame_limit: int,
    *,
    dedup_window_seconds: float = DEFAULT_DEDUP_WINDOW_SECONDS,
) -> list[KeyMoment]:
    if frame_limit <= 0:
        return []

    candidates = list(draft.key_moments)
    if not candidates:
        candidates = _fallback_key_moments(draft, duration)

    selected: list[KeyMoment] = []
    for moment in candidates:
        clamped_time = clamp_key_frame_time(moment.time, duration)
        if _is_near_selected(clamped_time, selected, dedup_window_seconds):
            continue
        selected.append(moment.model_copy(update={"time": clamped_time, "frame_path": None}))
        if len(selected) >= frame_limit:
            break
    return selected


def clamp_key_frame_time(timestamp: float, duration: float | None) -> float:
    minimum, maximum = _frame_time_bounds(duration)
    if maximum is None:
        return max(minimum, timestamp)
    return clamp_seconds(timestamp, minimum, maximum)


def _frame_time_bounds(duration: float | None) -> tuple[float, float | None]:
    if duration is None or duration <= 0:
        return 0.0, None
    if duration > 1:
        return 0.25, max(0.25, duration - 0.25)
    return 0.0, duration


def _is_near_selected(
    timestamp: float,
    selected_moments: list[KeyMoment],
    dedup_window_seconds: float,
) -> bool:
    return any(abs(timestamp - moment.time) < dedup_window_seconds for moment in selected_moments)


def _fallback_key_moments(draft: NoteDraft, duration: float | None) -> list[KeyMoment]:
    moments: list[KeyMoment] = []
    for index, chapter in enumerate(draft.chapters):
        moments.append(
            KeyMoment(
                time=_chapter_fallback_time(chapter),
                reason=f"Chapter frame: {chapter.title}",
                chapter_index=index,
            )
        )
    if moments:
        return moments
    return [KeyMoment(time=_video_midpoint(duration), reason="Video midpoint")]


def _chapter_fallback_time(chapter: Chapter) -> float:
    if chapter.end_time > chapter.start_time:
        return chapter.start_time + ((chapter.end_time - chapter.start_time) / 2)
    return chapter.start_time


def _video_midpoint(duration: float | None) -> float:
    if duration is None or duration <= 0:
        return 0.0
    return duration / 2
