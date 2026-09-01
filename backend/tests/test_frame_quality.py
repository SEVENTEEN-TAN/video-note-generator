from __future__ import annotations

from backend.app.frame_quality import analyze_grayscale_pixels


def test_black_frame_is_flagged_and_receives_low_score() -> None:
    quality = analyze_grayscale_pixels(bytes([0] * 25), width=5, height=5)

    assert "black_frame" in quality.risk_flags
    assert "low_contrast" in quality.risk_flags
    assert quality.score == 0


def test_white_frame_is_flagged_and_receives_low_score() -> None:
    quality = analyze_grayscale_pixels(bytes([255] * 25), width=5, height=5)

    assert "white_frame" in quality.risk_flags
    assert "blurry_frame" in quality.risk_flags
    assert quality.score == 0


def test_checkerboard_frame_has_high_contrast_and_sharpness() -> None:
    pixels = bytes(
        255 if (row + column) % 2 else 0
        for row in range(8)
        for column in range(8)
    )

    quality = analyze_grayscale_pixels(pixels, width=8, height=8)

    assert quality.contrast is not None and quality.contrast > 0.45
    assert quality.sharpness is not None and quality.sharpness > 0.9
    assert "blurry_frame" not in quality.risk_flags
    assert "low_contrast" not in quality.risk_flags
    assert quality.score > 0.8


def test_invalid_pixel_dimensions_are_rejected() -> None:
    try:
        analyze_grayscale_pixels(bytes([0] * 10), width=5, height=5)
    except ValueError as exc:
        assert "dimensions" in str(exc)
    else:
        raise AssertionError("Expected invalid grayscale dimensions to fail.")
