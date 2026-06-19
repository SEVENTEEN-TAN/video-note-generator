from __future__ import annotations


def clamp_seconds(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))


def seconds_to_hhmmss(seconds: float) -> str:
    seconds = max(0, seconds)
    total_seconds = int(seconds)
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    secs = total_seconds % 60
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def seconds_to_srt(seconds: float) -> str:
    seconds = max(0, seconds)
    total_ms = int(round(seconds * 1000))
    hours = total_ms // 3_600_000
    minutes = (total_ms % 3_600_000) // 60_000
    secs = (total_ms % 60_000) // 1000
    millis = total_ms % 1000
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def seconds_to_vtt(seconds: float) -> str:
    return seconds_to_srt(seconds).replace(",", ".")

