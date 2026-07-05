from __future__ import annotations

import json
import re

from openai import BadRequestError, OpenAI, OpenAIError

from .models import Chapter, JobConfig, KeyMoment, NoteDraft, NoteLanguage, NoteStyle, TranscriptSegment
from .task_debug_log import TaskDebugLog
from .time_utils import seconds_to_hhmmss


class LLMError(RuntimeError):
    pass


def _is_content_policy_rejection(exc: BadRequestError) -> bool:
    body = getattr(exc, "body", None)
    if isinstance(body, dict):
        error = body.get("error")
        if isinstance(error, dict) and error.get("code") == "content_policy_violation":
            return True
        if body.get("code") == "content_policy_violation":
            return True
    return "content_policy_violation" in str(exc)


def _is_response_format_unsupported(exc: BadRequestError) -> bool:
    body = getattr(exc, "body", None)
    parts = [str(exc)]
    if isinstance(body, dict):
        error = body.get("error")
        if isinstance(error, dict):
            parts.extend(str(error.get(field) or "") for field in ("code", "message", "type"))
        parts.extend(str(body.get(field) or "") for field in ("code", "message", "type"))
    normalized = " ".join(parts).casefold()
    return "response_format" in normalized and any(
        marker in normalized
        for marker in ("not support", "unsupported", "unknown parameter", "invalid parameter", "unrecognized")
    )


def _log_note_api_error(debug_log: TaskDebugLog, debug_context: str, attempt: int, exc: OpenAIError) -> None:
    response = getattr(exc, "response", None)
    debug_log.event(
        "note_model_call",
        "api_error",
        context=debug_context,
        attempt=attempt,
        exception_type=type(exc).__name__,
        exception_message=str(exc),
        status_code=getattr(response, "status_code", None),
        body=getattr(exc, "body", None),
    )


MAX_SINGLE_PROMPT_CHARS = 24_000
MAX_CHUNK_TRANSCRIPT_CHARS = 12_000
MAX_REDUCE_PROMPT_CHARS = 24_000
LARGE_TRANSCRIPT_GAP_SECONDS = 45
MIN_CHUNK_SEGMENTS_FOR_BINARY_RETRY = 6
MAX_FALLBACK_LIST_ITEMS = 24
MAX_COMPACT_MARKDOWN_LINES = 8
MAX_COMPACT_MARKDOWN_LINE_CHARS = 90
MAX_PRIOR_CONTEXT_CHARS = 4_000
MAX_PRIOR_CONTEXT_TITLE_CHARS = 120
JSON_WRAPPER_KEYS = ("note", "draft", "data", "result", "output")


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

TIMESTAMP_FIELD_INSTRUCTION = (
    "JSON timestamp fields start_time, end_time, and time must be numeric seconds from video start, "
    'for example 9419.0, not "02:36:59". Use display ranges like "00:00:03 - 00:00:08" only in quote_times.'
)


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
{TIMESTAMP_FIELD_INSTRUCTION}
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
    for candidate in _json_dict_candidates(text):
        return candidate
    raise ValueError("Model did not return a JSON object.")


def _normalize_json_text(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?", "", text, flags=re.IGNORECASE).strip()
        text = re.sub(r"```$", "", text).strip()
    return text


def _json_dict_candidates(text: str):
    text = _normalize_json_text(text)
    try:
        value = json.loads(text)
    except json.JSONDecodeError as exc:
        original_error = exc
    else:
        yield from _json_value_dict_candidates(value)
        return

    found = False
    decoder = json.JSONDecoder()
    for match in re.finditer(r"\{", text):
        try:
            value, _end = decoder.raw_decode(text[match.start() :])
        except json.JSONDecodeError:
            continue
        yielded = False
        for candidate in _json_value_dict_candidates(value):
            found = True
            yielded = True
            yield candidate
        if yielded:
            continue
    if not found:
        raise original_error


def _json_value_dict_candidates(value):
    if isinstance(value, dict):
        yield value
        yield from _wrapped_json_dict_candidates(value)
    elif isinstance(value, list):
        for item in value:
            yield from _json_value_dict_candidates(item)


def _wrapped_json_dict_candidates(value: dict):
    for key in JSON_WRAPPER_KEYS:
        nested = value.get(key)
        if isinstance(nested, dict):
            yield nested
            yield from _wrapped_json_dict_candidates(nested)
        elif isinstance(nested, list):
            yield from _json_value_dict_candidates(nested)
        elif isinstance(nested, str):
            yield from _json_dict_candidates(nested)


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
        last_error: Exception | None = None
        for candidate in _json_dict_candidates(text):
            try:
                return _validate_note_draft(candidate)
            except Exception as exc:
                last_error = exc
        if last_error:
            raise last_error
        raise ValueError("Model did not return a JSON object.")
    except Exception as exc:
        raise LLMError(f"Model returned invalid note JSON: {exc}") from exc


def _validate_note_draft(payload: dict) -> NoteDraft:
    draft = sanitize_note_draft(NoteDraft.model_validate(payload))
    if draft.recommended_frame_count is not None:
        return draft
    fallback = min(max(len(draft.key_moments), 1), 24)
    return draft.model_copy(update={"recommended_frame_count": fallback})


def make_client(api_key: str, base_url: str) -> OpenAI:
    base_url = base_url.strip()
    if base_url:
        return OpenAI(api_key=api_key, base_url=base_url, timeout=60.0, max_retries=0)
    return OpenAI(api_key=api_key, timeout=60.0, max_retries=0)


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


def _json_retry_instruction(text: str, exc: BaseException) -> str:
    instruction = (
        "The previous answer was not valid against the requested JSON shape. "
        "Return corrected strict JSON only, with no markdown fence."
    )
    details = _json_error_details(text, exc)
    if not details:
        return instruction
    error_context = str(details.get("error_context") or "").strip()
    context_suffix = f" Near: {error_context[:500]}" if error_context else ""
    return (
        f"{instruction} JSON parse error: {details['json_error_message']} "
        f"at line {details['json_error_line']}, column {details['json_error_column']}."
        f"{context_suffix}"
    )


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
    use_response_format = True
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
        while True:
            request_kwargs = {
                "model": config.note_model,
                "messages": working_messages,
                "temperature": 0.2,
                "max_tokens": max_tokens,
            }
            if use_response_format:
                request_kwargs["response_format"] = {"type": "json_object"}
            try:
                response = client.chat.completions.create(**request_kwargs)
                break
            except BadRequestError as exc:
                if debug_log:
                    _log_note_api_error(debug_log, debug_context, attempt, exc)
                if _is_content_policy_rejection(exc):
                    raise LLMError(str(exc)) from exc
                if use_response_format and _is_response_format_unsupported(exc):
                    use_response_format = False
                    if debug_log:
                        debug_log.event(
                            "note_model_call",
                            "response_format_fallback",
                            context=debug_context,
                            attempt=attempt,
                            reason=str(exc),
                        )
                    continue
                raise
            except OpenAIError as exc:
                if debug_log:
                    _log_note_api_error(debug_log, debug_context, attempt, exc)
                raise
        choice = response.choices[0]
        text = choice.message.content or ""
        finish_reason = getattr(choice, "finish_reason", None)
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
                finish_reason=finish_reason,
            )
        if isinstance(finish_reason, str) and finish_reason.casefold() == "content_filter":
            raise LLMError("Model response was filtered by content policy (finish_reason=content_filter).")
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
                    "content": _json_retry_instruction(text, exc),
                }
            )
    if debug_log:
        debug_log.event("note_model_call", "failed", context=debug_context, error=str(last_error or "unknown"))
    raise LLMError(str(last_error) if last_error else "The model did not return a valid note draft.")


def call_json_model(config: JobConfig, messages: list[dict], max_tokens: int = 3000) -> dict:
    client = make_client(config.note_api_key, config.note_base_url)
    request_kwargs = {
        "model": config.note_model,
        "messages": messages,
        "response_format": {"type": "json_object"},
        "temperature": 0.1,
        "max_tokens": max_tokens,
    }
    try:
        response = client.chat.completions.create(**request_kwargs)
    except BadRequestError as exc:
        if not _is_response_format_unsupported(exc):
            raise
        request_kwargs.pop("response_format", None)
        response = client.chat.completions.create(**request_kwargs)
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



def generate_chunked_note_draft_with_chunks(
    config: JobConfig,
    duration: float | None,
    segments: list[TranscriptSegment],
    system_prompt: str,
    debug_log: TaskDebugLog | None = None,
) -> tuple[NoteDraft, list[list[TranscriptSegment]], list[NoteDraft]]:
    """Like generate_chunked_note_draft but also returns chunk segments and drafts."""
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
        reduced = reduce_note_drafts(config, duration, chunk_drafts, system_prompt, debug_log=debug_log)
    else:
        reduced = reduce_note_drafts(config, duration, chunk_drafts, system_prompt)
    return reduced, chunks, chunk_drafts


def _build_prior_context(completed_drafts: list[NoteDraft]) -> str:
    """Build a compact summary of earlier chunk outputs for context continuity."""
    if not completed_drafts:
        return ""
    lines: list[str] = []
    for draft in completed_drafts:
        title = (draft.title or "").strip()[:MAX_PRIOR_CONTEXT_TITLE_CHARS]
        summary = (draft.summary or "").strip()
        parts: list[str] = []
        if summary:
            parts.append(f"summary: {summary[:200]}")
        takeaways = [item.strip()[:120] for item in draft.key_takeaways[:3] if item.strip()]
        if takeaways:
            parts.append(f"takeaways: {'; '.join(takeaways)}")
        action_items = [item.strip()[:120] for item in draft.action_items[:3] if item.strip()]
        if action_items:
            parts.append(f"actions: {'; '.join(action_items)}")
        if parts:
            lines.append(f"- {title or 'Previous chunk'}: {' | '.join(parts)}")
    selected: list[str] = []
    total = 0
    for line in reversed(lines):
        extra = len(line) + (1 if selected else 0)
        if selected and total + extra > MAX_PRIOR_CONTEXT_CHARS:
            break
        selected.append(line)
        total += extra
    selected.reverse()
    return "\n".join(selected)


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
    debug_suffix: str = "",
) -> list[NoteDraft]:
    """Transcribe one chunk; on failure, binary-split and retry each half.

    Content moderation rejections are often triggered by a few sentences.
    Splitting the chunk into halves lets the clean half through while
    keeping the offending half isolated.
    """
    debug_context = f"note-chunk-{chunk_index}-of-{chunk_count}{debug_suffix}"
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
            left_results = _transcribe_note_chunk_with_retry(
                config=config,
                duration=duration,
                system_prompt=system_prompt,
                chunk=left,
                chunk_index=chunk_index,
                chunk_count=chunk_count,
                prior_context=prior_context,
                debug_log=debug_log,
                debug_suffix=f"{debug_suffix}-left",
            )
            results.extend(left_results)
            right_prior_context = "\n".join(
                item for item in (prior_context, _build_prior_context(left_results)) if item
            )
            results.extend(
                _transcribe_note_chunk_with_retry(
                    config=config,
                    duration=duration,
                    system_prompt=system_prompt,
                    chunk=right,
                    chunk_index=chunk_index,
                    chunk_count=chunk_count,
                    prior_context=right_prior_context,
                    debug_log=debug_log,
                    debug_suffix=f"{debug_suffix}-right",
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
        return [
            fallback_note_draft_from_chunk(
                chunk_index,
                chunk_count,
                chunk,
                config.note_language.value,
                failure_reason=str(exc),
            )
        ]


def fallback_note_draft_from_chunk(
    chunk_index: int,
    chunk_count: int,
    segments: list[TranscriptSegment],
    note_language: str = NoteLanguage.en.value,
    failure_reason: str = "",
) -> NoteDraft:
    use_chinese = note_language == NoteLanguage.zh.value or (
        note_language == NoteLanguage.follow.value and any(re.search(r"[\u4e00-\u9fff]", segment.text) for segment in segments)
    )
    title = f"转写分块 {chunk_index}/{chunk_count}" if use_chinese else f"Transcript chunk {chunk_index} of {chunk_count}"
    if not segments:
        return NoteDraft(title=title, summary="")

    start_time = segments[0].start
    end_time = segments[-1].end
    time_range = f"{seconds_to_hhmmss(start_time)} - {seconds_to_hhmmss(end_time)}"
    reason = _summarize_fallback_failure_reason(failure_reason)
    if use_chinese:
        summary = f"分块 {chunk_index}/{chunk_count}（{time_range}）已跳过，因为笔记模型拒绝了这段内容。"
        if reason:
            summary += f"原因：{reason}。"
    else:
        summary = f"Chunk {chunk_index}/{chunk_count} ({time_range}) was skipped because the note model rejected it."
        if reason:
            summary += f" Reason: {reason}."
    markdown_body = _fallback_transcript_excerpt(segments, use_chinese=use_chinese)
    return NoteDraft(
        title=title,
        summary=summary,
        chapters=[],
        key_moments=[],
        recommended_frame_count=1,
        key_takeaways=[],
        action_items=[],
        markdown_body=markdown_body,
    )


def _summarize_fallback_failure_reason(reason: str) -> str:
    reason = re.sub(r"\s+", " ", _sanitize_text(reason)).strip()
    if len(reason) > 180:
        return f"{reason[:177]}..."
    return reason


def _fallback_transcript_excerpt(segments: list[TranscriptSegment], *, use_chinese: bool) -> str:
    heading = "## 原转录摘录" if use_chinese else "## Transcript excerpt"
    lines = []
    for segment in segments[:6]:
        text = _sanitize_text(segment.text)
        if len(text) > 180:
            text = f"{text[:177]}..."
        lines.append(f"- [{seconds_to_hhmmss(segment.start)} - {seconds_to_hhmmss(segment.end)}] {text}")
    if len(segments) > 6:
        remaining = len(segments) - 6
        lines.append(f"- ... 还有 {remaining} 段转录未展开" if use_chinese else f"- ... {remaining} more transcript segments omitted")
    return "\n".join([heading, *lines])


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
    frame_limit = max(1, min(config.frame_limit, 24))
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
    context_block = (
        f"\nPrior context (summaries, takeaways, and actions from earlier chunks):\n{prior_context}\n"
        if prior_context
        else ""
    )
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
{TIMESTAMP_FIELD_INSTRUCTION}

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
{TIMESTAMP_FIELD_INSTRUCTION}

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
                "quote_times": [quote_time[:80] for quote_time in chapter.quote_times[:3]],
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
        "markdown_body": _compact_markdown_body(draft.markdown_body),
    }


def _compact_markdown_body(markdown_body: str) -> str:
    compact_lines = []
    for line in markdown_body.splitlines()[:MAX_COMPACT_MARKDOWN_LINES]:
        stripped = line.strip()
        if len(stripped) > MAX_COMPACT_MARKDOWN_LINE_CHARS:
            stripped = f"{stripped[: MAX_COMPACT_MARKDOWN_LINE_CHARS - 3]}..."
        if stripped:
            compact_lines.append(stripped)
    return "\n".join(compact_lines)
