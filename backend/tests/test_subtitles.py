from backend.app.models import TranscriptSegment
from backend.app.subtitles import render_srt, render_subtitle_markdown, render_vtt, transcript_segments_from_payload


def test_transcript_segments_from_payload() -> None:
    payload = {"segments": [{"start": 0, "end": 1.5, "text": " hello "}]}
    assert transcript_segments_from_payload(payload) == [TranscriptSegment(start=0, end=1.5, text="hello")]


def test_transcript_segments_normalize_high_frequency_ai_terms() -> None:
    payload = {
        "segments": [
            {"start": 0, "end": 1.5, "text": "低贩 和 codes 还有 欧拉马 以及 安索皮克 的mcp协议"}
        ]
    }

    segments = transcript_segments_from_payload(payload)

    assert segments[0].text == "Dify 和 Coze 还有 Ollama 以及 Anthropic 的 MCP 协议"


def test_render_subtitle_formats() -> None:
    segments = [TranscriptSegment(start=0, end=1.5, text="hello")]
    assert "00:00:00,000 --> 00:00:01,500" in render_srt(segments)
    assert "WEBVTT" in render_vtt(segments)
    assert "`00:00:00 - 00:00:01` hello" in render_subtitle_markdown(segments)


def test_render_subtitle_markdown_preserves_many_segments() -> None:
    segments = [
        TranscriptSegment(start=index * 2, end=index * 2 + 1, text=f"第 {index} 段字幕")
        for index in range(300)
    ]

    markdown = render_subtitle_markdown(segments)

    assert "第 0 段字幕" in markdown
    assert "第 299 段字幕" in markdown
    assert markdown.index("第 0 段字幕") < markdown.index("第 299 段字幕")
