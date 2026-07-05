from __future__ import annotations

import json
import re

from openai import OpenAI

from .models import Chapter, JobConfig, KeyMoment, NoteDraft, NoteStyle, TranscriptSegment
from .task_debug_log import TaskDebugLog
from .time_utils import seconds_to_hhmmss


class LLMError(RuntimeError):
    pass


MAX_SINGLE_PROMPT_CHARS = 24_000
MAX_CHUNK_TRANSCRIPT_CHARS = 12_000
MAX_REDUCE_PROMPT_CHARS = 24_000
LARGE_TRANSCRIPT_GAP_SECONDS = 45
MIN_CHUNK_SEGMENTS_FOR_BINARY_RETRY = 6
MAX_FALLBACK_LIST_ITEMS = 24


def estimate_prompt_tokens(text: str) -> int:
    if not text:
        return 0
    ascii_chars = sum(1 for char in text if ord(char) < 128)
    non_ascii_chars = len(text) - ascii_chars
    return max(1, (ascii_chars + 3) // 4 + non_ascii_chars)


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
  "recommended_frame_count": 6,
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
Choose key moments that can work as visual illustrations.
Also estimate a sensible recommended_frame_count between 1 and {frame_limit}.
Prefer fewer high-signal frames over repetitive frames.
Keep key_moments length <= {frame_limit}.
{NOTE_SCHEMA_DESCRIPTION}
""".strip()


def render_transcript_lines(segments: list[TranscriptSegment]) -> list[str]:
    return [
        f"[{seconds_to_hhmmss(segment.start)} - {seconds_to_hhmmss(segment.end)}] {segment.text}"
        for segment in segments
    ]


def chunk_segments(segments: list[TranscriptSegment], max_chars: int = MAX_CHUNK_TRANSCRIPT_CHARS) -> list[list[TranscriptSegment]]:
    chunks: list[list[TranscriptSegment]] = []
    current: list[TranscriptSegment] = []
    current_chars = 0
    for segment in segments:
        line_chars = len(segment.text) + 32
        has_large_gap = bool(current and segment.start - current[-1].end >= LARGE_TRANSCRIPT_GAP_SECONDS)
        would_exceed = bool(current and current_chars + line_chars > max_chars)
        if has_large_gap or would_exceed:
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


def _sanitize_text(value: str) -> str:
    return re.sub(r"�+", "", value).strip()


def sanitize_note_draft(draft: NoteDraft) -> NoteDraft:
    return draft.model_copy(
        update={
            "title": _sanitize_text(draft.title),
            "summary": _sanitize_text(draft.summary),
            "chapters": [
                chapter.model_copy(
                    update={
                        "title": _sanitize_text(chapter.title),
                        "bullets": [_sanitize_text(bullet) for bullet in chapter.bullets],
                        "detail": _sanitize_text(chapter.detail),
                        "quote_times": [_sanitize_text(item) for item in chapter.quote_times],
                    }
                )
                for chapter in draft.chapters
            ],
            "key_moments": [
                moment.model_copy(update={"reason": _sanitize_text(moment.reason)})
                for moment in draft.key_moments
            ],
            "key_takeaways": [_sanitize_text(item) for item in draft.key_takeaways],
            "action_items": [_sanitize_text(item) for item in draft.action_items],
            "markdown_body": _sanitize_text(draft.markdown_body),
        }
    )


def parse_note_draft(text: str) -> NoteDraft:
    try:
        draft = sanitize_note_draft(NoteDraft.model_validate(extract_json(text)))
        if draft.recommended_frame_count is not None:
            return draft
        fallback = min(max(len(draft.key_moments), 1), 12)
        return draft.model_copy(update={"recommended_frame_count": fallback})
    except Exception as exc:
        raise LLMError(f"Model returned invalid note JSON: {exc}") from exc


def make_client(api_key: str, base_url: str) -> OpenAI:
    base_url = base_url.strip()
    if base_url:
        return OpenAI(api_key=api_key, base_url=base_url)
    return OpenAI(api_key=api_key)


def _safe_debug_context(value: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9._-]+", "-", value.strip()).strip("-")
    return safe or "note"


def _find_json_decode_error(exc: BaseException) -> json.JSONDecodeError | None:
    current: BaseException | None = exc
    seen: set[int] = set()
    while current and id(current) not in seen:
        seen.add(id(current))
        if isinstance(current, json.JSONDecodeError):
            return current
        current = current.__cause__ or current.__context__
    return None


def _json_error_details(text: str, exc: BaseException) -> dict:
    decode_error = _find_json_decode_error(exc)
    if not decode_error:
        return {}
    start = max(0, decode_error.pos - 300)
    end = min(len(text), decode_error.pos + 300)
    return {
        "json_error_message": decode_error.msg,
        "json_error_line": decode_error.lineno,
        "json_error_column": decode_error.colno,
        "json_error_char": decode_error.pos,
        "error_context": text[start:end],
    }


def call_note_model(
    config: JobConfig,
    messages: list[dict],
    max_tokens: int = 3000,
    debug_log: TaskDebugLog | None = None,
    debug_context: str = "note",
) -> NoteDraft:
    client = make_client(config.note_api_key, config.note_base_url)
    last_error: Exception | None = None
    working_messages = list(messages)
    for attempt in range(1, 3):
        if debug_log:
            debug_log.event(
                "note_model_call",
                "requesting",
                context=debug_context,
                attempt=attempt,
                note_base_url=config.note_base_url,
                note_model=config.note_model,
                message_count=len(working_messages),
                message_chars=sum(len(str(message.get("content") or "")) for message in working_messages),
                max_tokens=max_tokens,
            )
        response = client.chat.completions.create(
            model=config.note_model,
            messages=working_messages,
            response_format={"type": "json_object"},
            temperature=0.2,
            max_tokens=max_tokens,
        )
        text = response.choices[0].message.content or ""
        response_file = ""
        if debug_log:
            response_file = f"{_safe_debug_context(debug_context)}-model-response-attempt-{attempt}.txt"
            debug_log.write_debug_text(response_file, text)
            debug_log.event(
                "note_model_call",
                "response_received",
                context=debug_context,
                attempt=attempt,
                response_file=f"debug/{response_file}",
                response_length=len(text),
            )
        try:
            return parse_note_draft(text)
        except LLMError as exc:
            last_error = exc
            if debug_log:
                debug_log.event(
                    "note_model_call",
                    "invalid_json",
                    context=debug_context,
                    attempt=attempt,
                    response_file=f"debug/{response_file}" if response_file else "",
                    response_length=len(text),
                    error=str(exc),
                    **_json_error_details(text, exc),
                )
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
    if debug_log:
        debug_log.event("note_model_call", "failed", context=debug_context, error=str(last_error or "unknown"))
    raise LLMError(str(last_error) if last_error else "The model did not return a valid note draft.")


def call_json_model(config: JobConfig, messages: list[dict], max_tokens: int = 3000) -> dict:
    client = make_client(config.note_api_key, config.note_base_url)
    response = client.chat.completions.create(
        model=config.note_model,
        messages=messages,
        response_format={"type": "json_object"},
        temperature=0.1,
        max_tokens=max_tokens,
    )
    text = response.choices[0].message.content or ""
    try:
        return extract_json(text)
    except Exception as exc:
        raise LLMError(f"Model returned invalid correction JSON: {exc}") from exc


def generate_note_draft(
    config: JobConfig,
    duration: float | None,
    segments: list[TranscriptSegment],
    debug_log: TaskDebugLog | None = None,
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
    if len(user_prompt) > MAX_SINGLE_PROMPT_CHARS or estimate_prompt_tokens(user_prompt) > MAX_SINGLE_PROMPT_CHARS // 4:
        if debug_log:
            return generate_chunked_note_draft(config, duration, segments, system_prompt, debug_log=debug_log)
        return generate_chunked_note_draft(config, duration, segments, system_prompt)

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]
    if debug_log:
        return call_note_model(config, messages, debug_log=debug_log, debug_context="note")
    return call_note_model(config, messages)


def generate_chunked_note_draft(
    config: JobConfig,
    duration: float | None,
    segments: list[TranscriptSegment],
    system_prompt: str,
    debug_log: TaskDebugLog | None = None,
) -> NoteDraft:
    chunks = chunk_segments(segments, MAX_CHUNK_TRANSCRIPT_CHARS)
    chunk_drafts: list[NoteDraft] = []
    for index, chunk in enumerate(chunks, start=1):
        prior_context = _build_prior_context(chunk_drafts)
        chunk_drafts.extend(
            _transcribe_note_chunk_with_retry(
                config=config,
                duration=duration,
                system_prompt=system_prompt,
                chunk=chunk,
                chunk_index=index,
                chunk_count=len(chunks),
                prior_context=prior_context,
                debug_log=debug_log,
            )
        )
    if debug_log:
        return reduce_note_drafts(config, duration, chunk_drafts, system_prompt, debug_log=debug_log)
    return reduce_note_drafts(config, duration, chunk_drafts, system_prompt)



def _build_prior_context(completed_drafts: list[NoteDraft]) -> str:
    """Build a compact summary of earlier chunk outputs for context continuity."""
    if not completed_drafts:
        return ""
    lines: list[str] = []
    for draft in completed_drafts:
        title = (draft.title or "").strip()
        summary = (draft.summary or "").strip()
        if summary:
            lines.append(f"- {title}: {summary[:200]}")
    return "\n".join(lines)

def _transcribe_note_chunk_with_retry(
    *,
    config: JobConfig,
    duration: float | None,
    system_prompt: str,
    chunk: list[TranscriptSegment],
    chunk_index: int,
    chunk_count: int,
    prior_context: str = "",
    debug_log: TaskDebugLog | None = None,
) -> list[NoteDraft]:
    """Transcribe one chunk; on failure, binary-split and retry each half.

    Content moderation rejections are often triggered by a few sentences.
    Splitting the chunk into halves lets the clean half through while
    keeping the offending half isolated.
    """
    debug_context = f"note-chunk-{chunk_index}-of-{chunk_count}"
    kwargs: dict[str, object] = {"max_tokens": 2200}
    if debug_log:
        kwargs["debug_log"] = debug_log
        kwargs["debug_context"] = debug_context
    try:
        chunk_prompt = build_chunk_prompt(
            config.original_filename,
            duration,
            config.note_language.value,
            config.frame_limit,
            chunk_index,
            chunk_count,
            chunk,
            note_style=config.note_style.value,
            extras=config.extras,
            prior_context=prior_context,
        )
        return [
            call_note_model(
                config,
                [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": chunk_prompt},
                ],
                **kwargs,
            )
        ]
    except LLMError as exc:
        if len(chunk) >= MIN_CHUNK_SEGMENTS_FOR_BINARY_RETRY * 2:
            if debug_log:
                debug_log.event(
                    "generate_chunked_note_draft",
                    "binary_split_retry",
                    context=debug_context,
                    segment_count=len(chunk),
                    error=str(exc),
                )
            midpoint = len(chunk) // 2
            left = chunk[:midpoint]
            right = chunk[midpoint:]
            results: list[NoteDraft] = []
            results.extend(
                _transcribe_note_chunk_with_retry(
                    config=config,
                    duration=duration,
                    system_prompt=system_prompt,
                    chunk=left,
                    chunk_index=chunk_index,
                    chunk_count=chunk_count,
                    prior_context=prior_context,
                    debug_log=debug_log,
                )
            )
            results.extend(
                _transcribe_note_chunk_with_retry(
                    config=config,
                    duration=duration,
                    system_prompt=system_prompt,
                    chunk=right,
                    chunk_index=chunk_index,
                    chunk_count=chunk_count,
                    prior_context=prior_context,
                    debug_log=debug_log,
                )
            )
            return results
        if debug_log:
            debug_log.event(
                "generate_chunked_note_draft",
                "fallback_to_skipped_chunk",
                context=debug_context,
                chunk_index=chunk_index,
                segment_count=len(chunk),
                error=str(exc),
            )
        return [fallback_note_draft_from_chunk(chunk_index, chunk_count, chunk)]


def fallback_note_draft_from_chunk(
    chunk_index: int,
    chunk_count: int,
    segments: list[TranscriptSegment],
) -> NoteDraft:
    if not segments:
        return NoteDraft(title=f"Transcript chunk {chunk_index} of {chunk_count}", summary="")

    start_time = segments[0].start
    end_time = segments[-1].end
    summary = f"Chunk {chunk_index}/{chunk_count} ({seconds_to_hhmmss(start_time)} - {seconds_to_hhmmss(end_time)}) was skipped because the note model rejected it."
    return NoteDraft(
        title=f"Transcript chunk {chunk_index} of {chunk_count}",
        summary=summary,
        chapters=[],
        key_moments=[],
        recommended_frame_count=1,
        key_takeaways=[],
        action_items=[],
    )


def reduce_note_drafts(
    config: JobConfig,
    duration: float | None,
    partials: list[NoteDraft],
    system_prompt: str,
    debug_log: TaskDebugLog | None = None,
) -> NoteDraft:
    reduce_prompt = build_reduce_prompt(config, duration, partials)
    if len(reduce_prompt) > MAX_REDUCE_PROMPT_CHARS or estimate_prompt_tokens(reduce_prompt) > MAX_REDUCE_PROMPT_CHARS // 4:
        reduce_prompt = build_reduce_prompt(config, duration, partials, compact=True)
    kwargs = {"max_tokens": 3600}
    if debug_log:
        kwargs["debug_log"] = debug_log
        kwargs["debug_context"] = "note-reduce"
    try:
        return call_note_model(
            config,
            [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": reduce_prompt},
            ],
            **kwargs,
        )
    except LLMError as exc:
        if debug_log:
            debug_log.event(
                "reduce_note_drafts",
                "fallback_to_deterministic_merge",
                partial_count=len(partials),
                error=str(exc),
            )
        return merge_partial_note_drafts(config, partials)


def merge_partial_note_drafts(config: JobConfig, partials: list[NoteDraft]) -> NoteDraft:
    frame_limit = max(1, min(config.frame_limit, 12))
    if not partials:
        return NoteDraft(
            title=config.original_filename,
            summary="",
            recommended_frame_count=1,
        )

    chapters = []
    key_moments = []
    summaries: list[str] = []
    takeaways: list[str] = []
    action_items: list[str] = []
    markdown_parts: list[str] = []

    for draft in partials:
        if draft.summary.strip():
            summaries.append(draft.summary.strip())
        chapter_offset = len(chapters)
        chapters.extend(draft.chapters)
        for moment in draft.key_moments:
            if len(key_moments) >= frame_limit:
                break
            chapter_index = moment.chapter_index
            if chapter_index is not None:
                chapter_index += chapter_offset
            key_moments.append(moment.model_copy(update={"chapter_index": chapter_index}))
        takeaways.extend(draft.key_takeaways)
        action_items.extend(draft.action_items)
        if draft.markdown_body.strip():
            markdown_parts.append(draft.markdown_body.strip())

    title = next((draft.title.strip() for draft in partials if draft.title.strip()), config.original_filename)
    summary = "\n\n".join(_dedupe_text(summaries))
    recommended_frame_count = min(max(len(key_moments), 1), frame_limit)
    return NoteDraft(
        title=title,
        summary=summary,
        chapters=chapters,
        key_moments=key_moments,
        recommended_frame_count=recommended_frame_count,
        key_takeaways=_dedupe_text(takeaways, MAX_FALLBACK_LIST_ITEMS),
        action_items=_dedupe_text(action_items, MAX_FALLBACK_LIST_ITEMS),
        markdown_body="\n\n".join(_dedupe_text(markdown_parts)),
    )


def _dedupe_text(items: list[str], limit: int | None = None) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for item in items:
        cleaned = item.strip()
        if not cleaned:
            continue
        fingerprint = re.sub(r"\s+", " ", cleaned).casefold()
        if fingerprint in seen:
            continue
        seen.add(fingerprint)
        result.append(cleaned)
        if limit is not None and len(result) >= limit:
            break
    return result


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
    prior_context: str = "",
) -> str:
    transcript = "\n".join(render_transcript_lines(segments))
    duration_text = seconds_to_hhmmss(duration or 0) if duration else "unknown"
    style_guidance = build_style_guidance(note_style, extras)
    per_chunk_moments = max(1, min(3, frame_limit))
    context_block = f"\nPrior context (summaries of earlier chunks):\n{prior_context}\n" if prior_context else ""
    return f"""
Video filename: {original_filename}
Video duration: {duration_text}
Transcript chunk: {chunk_index} of {chunk_count}
Target note language: {note_language}
{style_guidance}
{context_block}

Create compact professional notes for only this transcript chunk.
Use absolute timestamps exactly as shown. Do not invent facts from other chunks.
Do not repeat content already covered in prior context. Build on it instead.
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
