from __future__ import annotations

from backend.app.frame_stability import (
    FrameStabilityRequest,
    analyze_stability_samples,
)


def _pattern(offset: int, *, width: int = 8, height: int = 8) -> bytes:
    return bytes(
        (offset + (220 if (row + column) % 2 else 30)) % 256
        for row in range(height)
        for column in range(width)
    )


def test_stable_anchor_is_preferred_when_neighboring_frames_match() -> None:
    request = FrameStabilityRequest(key="candidate", anchor_time=10)
    frame = _pattern(0)

    selection = analyze_stability_samples(
        request,
        {
            9.5: frame,
            10.0: frame,
            10.5: frame,
        },
        width=8,
        height=8,
        duration=20,
    )

    assert selection.available is True
    assert selection.selected_time == 10.0
    assert selection.stability_score == 1.0
    assert selection.transition_score == 0.0
    assert selection.sample_count == 3


def test_transition_frame_is_skipped_for_stable_post_cut_frame() -> None:
    request = FrameStabilityRequest(key="candidate", anchor_time=10)
    old_scene = _pattern(0)
    transition = bytes((value + index * 17) % 256 for index, value in enumerate(_pattern(40)))
    new_scene = _pattern(90)

    selection = analyze_stability_samples(
        request,
        {
            9.0: old_scene,
            9.5: old_scene,
            10.0: transition,
            10.5: new_scene,
            11.0: new_scene,
        },
        width=8,
        height=8,
        duration=20,
    )

    assert selection.available is True
    assert selection.selected_time == 10.5
    assert selection.stability_score == 1.0
    assert selection.transition_score == 0.0


def test_missing_scene_samples_fall_back_to_clamped_anchor() -> None:
    request = FrameStabilityRequest(
        key="candidate",
        anchor_time=0,
        lower_bound=0,
        upper_bound=20,
    )

    selection = analyze_stability_samples(
        request,
        {},
        width=8,
        height=8,
        duration=20,
    )

    assert selection.available is False
    assert selection.selected_time == 0.25
    assert selection.stability_score == 0.5
    assert selection.sample_count == 0
