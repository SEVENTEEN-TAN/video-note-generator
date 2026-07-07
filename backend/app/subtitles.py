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

SRT_TIMING_RE = re.compile(
    r"(?P<start>\d{1,2}:\d{2}:\d{2}[\.,]\d{1,3})\s*-->\s*"
    r"(?P<end>\d{1,2}:\d{2}:\d{2}[\.,]\d{1,3})"
)


class SubtitleParseError(RuntimeError):
    pass


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


def parse_srt_content(content: str) -> list[TranscriptSegment]:
    normalized = content.lstrip("\ufeff").replace("\r\n", "\n").replace("\r", "\n")
    segments: list[TranscriptSegment] = []
    for block in re.split(r"\n{2,}", normalized):
        lines = [line.strip() for line in block.split("\n") if line.strip()]
        if not lines:
            continue
        timing_index = next((index for index, line in enumerate(lines) if "-->" in line), -1)
        if timing_index < 0:
            continue
        match = SRT_TIMING_RE.search(lines[timing_index])
        if not match:
            continue
        text = normalize_transcript_text(" ".join(lines[timing_index + 1 :]))
        if not text:
            continue
        start = _parse_srt_timestamp(match.group("start"))
        end = _parse_srt_timestamp(match.group("end"))
        if end < start:
            end = start
        segments.append(TranscriptSegment(start=start, end=end, text=text))
    if not segments:
        raise SubtitleParseError("No usable SRT subtitle cues found.")
    return segments


def parse_srt_file(path: Path) -> list[TranscriptSegment]:
    try:
        return parse_srt_content(path.read_text(encoding="utf-8-sig"))
    except UnicodeDecodeError as exc:
        raise SubtitleParseError("Uploaded SRT subtitle must be UTF-8 encoded.") from exc


def _parse_srt_timestamp(value: str) -> float:
    time_part, millis_part = re.split(r"[\.,]", value, maxsplit=1)
    hours_text, minutes_text, seconds_text = time_part.split(":")
    millis_text = millis_part[:3].ljust(3, "0")
    return (
        int(hours_text) * 3600
        + int(minutes_text) * 60
        + int(seconds_text)
        + int(millis_text) / 1000
    )


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
