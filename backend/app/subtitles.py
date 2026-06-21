from __future__ import annotations

import re
from pathlib import Path

from .models import TranscriptSegment
from .time_utils import seconds_to_hhmmss, seconds_to_srt, seconds_to_vtt


TERM_NORMALIZATIONS = {
    "低贩": "Dify",
    "defy": "Dify",
    "codes": "Coze",
    "扣子": "Coze",
    "欧拉马": "Ollama",
    "安索皮克": "Anthropic",
    "mcp协议": "MCP 协议",
    "mcp": "MCP",
}


def normalize_transcript_text(text: str) -> str:
    normalized = str(text).strip()
    for source, target in TERM_NORMALIZATIONS.items():
        normalized = re.sub(source, target, normalized, flags=re.IGNORECASE)
    normalized = re.sub(r"(?<!\s)MCP", " MCP", normalized)
    normalized = re.sub(r"\s{2,}", " ", normalized).strip()
    return normalized


def transcript_segments_from_payload(payload: dict) -> list[TranscriptSegment]:
    raw_segments = payload.get("segments") or []
    segments: list[TranscriptSegment] = []
    for item in raw_segments:
        text = normalize_transcript_text(item.get("text", ""))
        if not text:
            continue
        segments.append(
            TranscriptSegment(
                start=float(item.get("start", 0)),
                end=float(item.get("end", item.get("start", 0))),
                text=text,
            )
        )
    if not segments and payload.get("text"):
        segments.append(TranscriptSegment(start=0, end=0, text=normalize_transcript_text(payload["text"])))
    return segments


def render_srt(segments: list[TranscriptSegment]) -> str:
    blocks: list[str] = []
    for index, segment in enumerate(segments, start=1):
        blocks.append(
            f"{index}\n"
            f"{seconds_to_srt(segment.start)} --> {seconds_to_srt(segment.end)}\n"
            f"{segment.text}"
        )
    return "\n\n".join(blocks) + "\n"


def render_vtt(segments: list[TranscriptSegment]) -> str:
    blocks = ["WEBVTT\n"]
    for segment in segments:
        blocks.append(
            f"{seconds_to_vtt(segment.start)} --> {seconds_to_vtt(segment.end)}\n"
            f"{segment.text}"
        )
    return "\n\n".join(blocks) + "\n"


def render_subtitle_markdown(segments: list[TranscriptSegment]) -> str:
    lines = ["# 字幕", ""]
    for segment in segments:
        lines.append(
            f"- `{seconds_to_hhmmss(segment.start)} - {seconds_to_hhmmss(segment.end)}` {segment.text}"
        )
    return "\n".join(lines) + "\n"


def write_subtitle_files(segments: list[TranscriptSegment], output_dir: Path) -> None:
    (output_dir / "subtitles.srt").write_text(render_srt(segments), encoding="utf-8-sig")
    (output_dir / "subtitles.vtt").write_text(render_vtt(segments), encoding="utf-8-sig")
    (output_dir / "subtitles.md").write_text(render_subtitle_markdown(segments), encoding="utf-8-sig")

