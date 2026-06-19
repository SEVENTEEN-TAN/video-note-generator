from backend.app.models import TranscriptSegment
from backend.app.subtitles import render_srt, render_subtitle_markdown, render_vtt, transcript_segments_from_payload


def test_transcript_segments_from_payload() -> None:
    payload = {"segments": [{"start": 0, "end": 1.5, "text": " hello "}]}
    assert transcript_segments_from_payload(payload) == [TranscriptSegment(start=0, end=1.5, text="hello")]


def test_render_subtitle_formats() -> None:
    segments = [TranscriptSegment(start=0, end=1.5, text="hello")]
    assert "00:00:00,000 --> 00:00:01,500" in render_srt(segments)
    assert "WEBVTT" in render_vtt(segments)
    assert "`00:00:00 - 00:00:01` hello" in render_subtitle_markdown(segments)

