from __future__ import annotations

import pytest

from backend.app.frame_selection import select_key_frame_moments
from backend.app.models import Chapter, KeyMoment, NoteDraft


def make_draft(
    *,
    chapters: list[Chapter] | None = None,
    key_moments: list[KeyMoment] | None = None,
) -> NoteDraft:
    return NoteDraft(
        title="Test note",
        summary="Test summary",
        chapters=chapters or [],
        key_moments=key_moments or [],
    )


def test_select_key_frame_moments_clamps_deduplicates_and_limits() -> None:
    draft = make_draft(
        key_moments=[
            KeyMoment(time=-10, reason="before"),
            KeyMoment(time=1, reason="too close"),
            KeyMoment(time=4.5, reason="kept"),
            KeyMoment(time=99, reason="after"),
            KeyMoment(time=20, reason="over limit"),
        ]
    )

    selected = select_key_frame_moments(
        draft,
        duration=30,
        frame_limit=3,
        dedup_window_seconds=4,
    )

    assert [moment.time for moment in selected] == pytest.approx([0.25, 4.5, 29.75])
    assert [moment.reason for moment in selected] == ["before", "kept", "after"]
    assert draft.key_moments[0].time == -10


def test_select_key_frame_moments_falls_back_to_chapter_midpoints_and_starts() -> None:
    draft = make_draft(
        chapters=[
            Chapter(title="Opening", start_time=0, end_time=10),
            Chapter(title="Still", start_time=12, end_time=12),
        ]
    )

    selected = select_key_frame_moments(draft, duration=20, frame_limit=2)

    assert [moment.time for moment in selected] == pytest.approx([5, 12])
    assert [moment.chapter_index for moment in selected] == [0, 1]


def test_select_key_frame_moments_falls_back_to_video_midpoint_without_chapters() -> None:
    selected = select_key_frame_moments(make_draft(), duration=40, frame_limit=6)

    assert len(selected) == 1
    assert selected[0].time == pytest.approx(20)
    assert selected[0].reason == "Video midpoint"
