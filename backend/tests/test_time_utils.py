from backend.app.time_utils import clamp_seconds, seconds_to_hhmmss, seconds_to_srt, seconds_to_vtt


def test_seconds_formatters() -> None:
    assert seconds_to_hhmmss(3661.2) == "01:01:01"
    assert seconds_to_srt(1.234) == "00:00:01,234"
    assert seconds_to_vtt(1.234) == "00:00:01.234"


def test_clamp_seconds() -> None:
    assert clamp_seconds(-1, 0, 10) == 0
    assert clamp_seconds(11, 0, 10) == 10
    assert clamp_seconds(5, 0, 10) == 5

