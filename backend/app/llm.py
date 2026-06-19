from __future__ import annotations

import json
import re

from openai import OpenAI

from .models import JobConfig, NoteDraft, NoteStyle, TranscriptSegment
from .time_utils import seconds_to_hhmmss


class LLMError(RuntimeError):
    pass


MAX_SINGLE_PROMPT_CHARS = 24_000
MAX_CHUNK_TRANSCRIPT_CHARS = 12_000
MAX_REDUCE_PROMPT_CHARS = 24_000


NOTE_SCHEMA_DESCRIPTION = """
Return only valid JSON with this shape:
{
  "title": "specific video title",
  "summary": "concise summary",
  "chapters": [
    {
      "title": "chapter title",
      "start_time": 0.0,
      "end_time": 42.0,
      "bullets": ["point"],
      "detail": "short explanatory paragraph",
      "quote_times": ["00:00:03 - 00:00:08"]
    }
  ],
  "key_moments": [
    {"time": 12.0, "reason": "why this frame illustrates the note", "chapter_index": 0}
  ],
  "key_takeaways": ["takeaway"],
  "action_items": ["action item"],
  "markdown_body": "optional additional markdown, no image paths"
}
"""


NOTE_STYLE_INSTRUCTIONS = {
    NoteStyle.minimal.value: "Be concise. Prefer short chapters, brief bullets, and only essential takeaways.",
    NoteStyle.detailed.value: "Produce a thorough professional note with clear chapters, useful detail, and concrete takeaways.",
    NoteStyle.tutorial.value: (
        "Explain ideas as a learning path. Include definitions, steps, examples, and practice-oriented action items "
        "when supported by the transcript."
    ),
    NoteStyle.academic.value: (
        "Use precise terminology, careful structure, and evidence-aware phrasing. Distinguish claims, methods, "
        "and conclusions when present."
    ),
    NoteStyle.task_oriented.value: (
        "Emphasize decisions, next steps, checklists, owners, risks, and practical action items when supported "
        "by the transcript."
    ),
    NoteStyle.meeting_minutes.value: (
        "Format the content like meeting minutes. Emphasize agenda topics, decisions, discussion points, and "
        "follow-up actions."
    ),
}


def build_style_guidance(note_style: str, extras: str = "") -> str:
    instruction = NOTE_STYLE_INSTRUCTIONS.get(note_style, NOTE_STYLE_INSTRUCTIONS[NoteStyle.detailed.value])
    lines = [f"Note style: {note_style}. {instruction}"]
    extras = extras.strip()
    if extras:
        lines.append(f"Extra user instructions: {extras}")
        lines.append(
            "Apply extra user instructions only when they do not conflict with transcript facts, timestamp rules, "
            "the JSON schema, or image path rules."
        )
    return "\n".join(lines)


def build_transcript_prompt(
    original_filename: str,
    duration: float | None,
    note_language: str,
    frame_limit: int,
    segments: list[TranscriptSegment],
    note_style: str = NoteStyle.detailed.value,
    extras: str = "",
) -> str:
    language_instruction = {
        "zh": "Output the final note content in Simplified Chinese.",
        "en": "Output the final note content in English.",
        "follow": "Use the primary language of the transcript.",
    }[note_language]
    duration_text = seconds_to_hhmmss(duration or 0) if duration else "unknown"
    style_guidance = build_style_guidance(note_style, extras)
    transcript_lines = [
        f"[{seconds_to_hhmmss(segment.start)} - {seconds_to_hhmmss(segment.end)}] {segment.text}"
        for segment in segments
    ]
    return f"""
Video filename: {original_filename}
Video duration: {duration_text}
Target note language: {note_language}. {language_instruction}
{style_guidance}
Maximum key moments for frame extraction: {frame_limit}

Transcript with timestamps:
{chr(10).join(transcript_lines)}

Create a professional video note. Use only facts from the transcript. Preserve useful timestamps.
Choose key moments that can work as visual illustrations. Keep key_moments length <= {frame_limit}.
{NOTE_SCHEMA_DESCRIPTION}
""".strip()


def render_transcript_lines(segments: list[TranscriptSegment]) -> list[str]:
    return [
        f"[{seconds_to_hhmmss(segment.start)} - {seconds_to_hhmmss(segment.end)}] {segment.text}"
        for segment in segments
    ]


def chunk_segments(segments: list[TranscriptSegment], max_chars: int) -> list[list[TranscriptSegment]]:
    chunks: list[list[TranscriptSegment]] = []
    current: list[TranscriptSegment] = []
    current_chars = 0
    for segment in segments:
        line_chars = len(segment.text) + 32
        if current and current_chars + line_chars > max_chars:
            chunks.append(current)
            current = []
            current_chars = 0
        current.append(segment)
        current_chars += line_chars
    if current:
        chunks.append(current)
    return chunks


def extract_json(text: str) -> dict:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?", "", text, flags=re.IGNORECASE).strip()
        text = re.sub(r"```$", "", text).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, flags=re.DOTALL)
        if not match:
            raise
        return json.loads(match.group(0))


def parse_note_draft(text: str) -> NoteDraft:
    try:
        return NoteDraft.model_validate(extract_json(text))
    except Exception as exc:
        raise LLMError(f"Model returned invalid note JSON: {exc}") from exc


def make_client(api_key: str, base_url: str) -> OpenAI:
    base_url = base_url.strip()
    if base_url:
        return OpenAI(api_key=api_key, base_url=base_url)
    return OpenAI(api_key=api_key)


def call_note_model(config: JobConfig, messages: list[dict], max_tokens: int = 3000) -> NoteDraft:
    client = make_client(config.note_api_key, config.note_base_url)
    last_error: Exception | None = None
    working_messages = list(messages)
    for _attempt in range(2):
        response = client.chat.completions.create(
            model=config.note_model,
            messages=working_messages,
            response_format={"type": "json_object"},
            temperature=0.2,
            max_tokens=max_tokens,
        )
        text = response.choices[0].message.content or ""
        try:
            return parse_note_draft(text)
        except LLMError as exc:
            last_error = exc
            working_messages.append({"role": "assistant", "content": text})
            working_messages.append(
                {
                    "role": "user",
                    "content": (
                        "The previous answer was not valid against the requested JSON shape. "
                        "Return corrected strict JSON only, with no markdown fence."
                    ),
                }
            )
    raise LLMError(str(last_error) if last_error else "The model did not return a valid note draft.")


def generate_note_draft(
    config: JobConfig,
    duration: float | None,
    segments: list[TranscriptSegment],
) -> NoteDraft:
    system_prompt = (
        "You are a professional video content editor, course note writer, and knowledge management expert. "
        "You must write only from the transcript. Do not invent facts. "
        "Return strict JSON only. Preserve timestamps for chapter navigation and frame extraction."
    )
    user_prompt = build_transcript_prompt(
        config.original_filename,
        duration,
        config.note_language.value,
        config.frame_limit,
        segments,
        note_style=config.note_style.value,
        extras=config.extras,
    )
    if len(user_prompt) > MAX_SINGLE_PROMPT_CHARS:
        return generate_chunked_note_draft(config, duration, segments, system_prompt)

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]
    return call_note_model(config, messages)


def generate_chunked_note_draft(
    config: JobConfig,
    duration: float | None,
    segments: list[TranscriptSegment],
    system_prompt: str,
) -> NoteDraft:
    chunk_drafts: list[NoteDraft] = []
    chunks = chunk_segments(segments, MAX_CHUNK_TRANSCRIPT_CHARS)
    for index, chunk in enumerate(chunks, start=1):
        chunk_prompt = build_chunk_prompt(
            config.original_filename,
            duration,
            config.note_language.value,
            config.frame_limit,
            index,
            len(chunks),
            chunk,
            note_style=config.note_style.value,
            extras=config.extras,
        )
        chunk_drafts.append(
            call_note_model(
                config,
                [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": chunk_prompt},
                ],
                max_tokens=2200,
            )
        )

    reduce_prompt = build_reduce_prompt(config, duration, chunk_drafts)
    if len(reduce_prompt) > MAX_REDUCE_PROMPT_CHARS:
        reduce_prompt = build_reduce_prompt(config, duration, chunk_drafts, compact=True)
    return call_note_model(
        config,
        [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": reduce_prompt},
        ],
        max_tokens=3600,
    )


def build_chunk_prompt(
    original_filename: str,
    duration: float | None,
    note_language: str,
    frame_limit: int,
    chunk_index: int,
    chunk_count: int,
    segments: list[TranscriptSegment],
    note_style: str = NoteStyle.detailed.value,
    extras: str = "",
) -> str:
    transcript = "\n".join(render_transcript_lines(segments))
    duration_text = seconds_to_hhmmss(duration or 0) if duration else "unknown"
    style_guidance = build_style_guidance(note_style, extras)
    per_chunk_moments = max(1, min(3, frame_limit))
    return f"""
Video filename: {original_filename}
Video duration: {duration_text}
Transcript chunk: {chunk_index} of {chunk_count}
Target note language: {note_language}
{style_guidance}

Create compact professional notes for only this transcript chunk.
Use absolute timestamps exactly as shown. Do not invent facts from other chunks.
Choose at most {per_chunk_moments} key moments.

Transcript with timestamps:
{transcript}

{NOTE_SCHEMA_DESCRIPTION}
""".strip()


def build_reduce_prompt(
    config: JobConfig,
    duration: float | None,
    chunk_drafts: list[NoteDraft],
    compact: bool = False,
) -> str:
    duration_text = seconds_to_hhmmss(duration or 0) if duration else "unknown"
    if compact:
        partials = [compact_note_draft(draft) for draft in chunk_drafts]
    else:
        partials = [draft.model_dump() for draft in chunk_drafts]
    style_guidance = build_style_guidance(config.note_style.value, config.extras)
    return f"""
Video filename: {config.original_filename}
Video duration: {duration_text}
Target note language: {config.note_language.value}
{style_guidance}
Maximum final key moments: {config.frame_limit}

The full transcript was processed in chunks to avoid wasting tokens. Merge these partial notes into one coherent final video note.
Keep chapter timestamps absolute. Remove duplicate points. Keep the strongest key moments only.

Partial notes JSON:
{json.dumps(partials, ensure_ascii=False)}

{NOTE_SCHEMA_DESCRIPTION}
""".strip()


def compact_note_draft(draft: NoteDraft) -> dict:
    return {
        "title": draft.title[:120],
        "summary": draft.summary[:800],
        "chapters": [
            {
                "title": chapter.title[:120],
                "start_time": chapter.start_time,
                "end_time": chapter.end_time,
                "bullets": [bullet[:220] for bullet in chapter.bullets[:5]],
                "detail": chapter.detail[:500],
            }
            for chapter in draft.chapters[:10]
        ],
        "key_moments": [
            {
                "time": moment.time,
                "reason": moment.reason[:160],
                "chapter_index": moment.chapter_index,
            }
            for moment in draft.key_moments[:5]
        ],
        "key_takeaways": [item[:220] for item in draft.key_takeaways[:8]],
        "action_items": [item[:220] for item in draft.action_items[:8]],
    }
