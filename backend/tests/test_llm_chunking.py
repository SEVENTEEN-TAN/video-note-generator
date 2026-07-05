from backend.app import llm
from backend.app.llm import (
    build_chunk_prompt,
    build_reduce_prompt,
    build_transcript_prompt,
    chunk_segments,
    estimate_prompt_tokens,
    parse_note_draft,
)
from backend.app.models import Chapter, JobConfig, KeyMoment, NoteDraft, NoteLanguage, NoteStyle, TranscriptSegment, TranscriptionMode
from backend.app.task_debug_log import TaskDebugLog


def test_chunk_segments_splits_without_dropping_segments() -> None:
    segments = [TranscriptSegment(start=index, end=index + 1, text="x" * 100) for index in range(5)]
    chunks = chunk_segments(segments, max_chars=260)
    flattened = [segment for chunk in chunks for segment in chunk]
    assert flattened == segments
    assert len(chunks) > 1


def test_chunk_segments_prefers_large_time_gap() -> None:
    segments = [
        TranscriptSegment(start=0, end=5, text="a" * 80),
        TranscriptSegment(start=6, end=10, text="b" * 80),
        TranscriptSegment(start=120, end=125, text="c" * 80),
    ]

    chunks = chunk_segments(segments, max_chars=240)

    assert len(chunks) == 2
    assert [segment.text[0] for segment in chunks[0]] == ["a", "b"]
    assert [segment.text[0] for segment in chunks[1]] == ["c"]


def test_estimate_prompt_tokens_is_monotonic() -> None:
    short = estimate_prompt_tokens("hello")
    long = estimate_prompt_tokens("hello " * 100)

    assert short >= 1
    assert long > short


def test_note_style_and_extras_are_injected_into_prompts() -> None:
    segments = [TranscriptSegment(start=0, end=4, text="Explain the project goals and next steps.")]

    transcript_prompt = build_transcript_prompt(
        "lesson.mp4",
        4.0,
        "en",
        6,
        segments,
        note_style="academic",
        extras="Emphasize definitions and source caveats.",
    )
    chunk_prompt = build_chunk_prompt(
        "lesson.mp4",
        4.0,
        "en",
        6,
        1,
        2,
        segments,
        note_style="task_oriented",
        extras="Prioritize next steps.",
    )

    assert "Note style: academic." in transcript_prompt
    assert "Extra user instructions: Emphasize definitions and source caveats." in transcript_prompt
    assert "Note style: task_oriented." in chunk_prompt
    assert "Extra user instructions: Prioritize next steps." in chunk_prompt
    assert "Return only valid JSON with this shape:" in transcript_prompt


def test_note_style_and_extras_are_injected_into_reduce_prompt() -> None:
    config = JobConfig(
        transcription_mode=TranscriptionMode.local_faster_whisper,
        note_api_key="note-key",
        note_language=NoteLanguage.en,
        note_style=NoteStyle.meeting_minutes,
        extras="Capture decisions explicitly.",
        original_filename="meeting.mp4",
    )

    prompt = build_reduce_prompt(config, 4.0, [NoteDraft(title="Chunk", summary="Summary")])

    assert "Note style: meeting_minutes." in prompt
    assert "Extra user instructions: Capture decisions explicitly." in prompt
    assert "Return only valid JSON with this shape:" in prompt


def test_generate_note_draft_uses_chunked_path_for_long_transcript(monkeypatch) -> None:
    calls: list[int] = []

    def fake_generate_chunked_note_draft(config, duration, segments, system_prompt):
        calls.append(len(segments))
        return NoteDraft(
            title="长视频笔记",
            summary="summary",
            chapters=[],
            key_moments=[],
            key_takeaways=[],
            action_items=[],
            markdown_body="",
        )

    monkeypatch.setattr(llm, "generate_chunked_note_draft", fake_generate_chunked_note_draft)

    segments = [TranscriptSegment(start=index, end=index + 1, text="内容" * 500) for index in range(40)]
    config = JobConfig(
        transcription_mode=TranscriptionMode.local_faster_whisper,
        note_api_key="note-key",
        note_language=NoteLanguage.zh,
        original_filename="long.mp4",
    )

    draft = llm.generate_note_draft(config, duration=3600, segments=segments)

    assert draft.title == "长视频笔记"
    assert calls == [40]


def test_reduce_prompt_compacts_when_full_reduce_is_too_large(monkeypatch) -> None:
    captured_prompts: list[str] = []

    def fake_call_note_model(config, messages, max_tokens=3000):
        captured_prompts.append(messages[-1]["content"])
        return NoteDraft(
            title="merged",
            summary="summary",
            chapters=[],
            key_moments=[],
            key_takeaways=[],
            action_items=[],
            markdown_body="",
        )

    monkeypatch.setattr(llm, "call_note_model", fake_call_note_model)

    partials = [
        NoteDraft(
            title=f"part-{index}",
            summary="s" * 5000,
            chapters=[],
            key_moments=[],
            key_takeaways=["k" * 5000],
            action_items=[],
            markdown_body="m" * 5000,
        )
        for index in range(8)
    ]
    config = JobConfig(
        transcription_mode=TranscriptionMode.local_faster_whisper,
        note_api_key="note-key",
        note_language=NoteLanguage.zh,
        original_filename="long.mp4",
    )

    llm.reduce_note_drafts(config, duration=3600, partials=partials, system_prompt="system")

    assert captured_prompts
    assert "m" * 100 not in captured_prompts[-1]


def test_reduce_note_drafts_falls_back_to_deterministic_merge_when_model_reduce_fails(tmp_path, monkeypatch) -> None:
    calls: list[str] = []

    def fake_call_note_model(config, messages, **kwargs):
        calls.append(kwargs.get("debug_context", ""))
        raise llm.LLMError("Model returned invalid note JSON: truncated")

    monkeypatch.setattr(llm, "call_note_model", fake_call_note_model)

    partials = [
        NoteDraft(
            title="Chunk one",
            summary="Opening summary.",
            chapters=[Chapter(title="Opening", start_time=0, end_time=10, bullets=["First point"], detail="First detail")],
            key_moments=[KeyMoment(time=1, reason="Opening frame", chapter_index=0)],
            key_takeaways=["Shared takeaway", "First takeaway"],
            action_items=["Review the opening"],
        ),
        NoteDraft(
            title="Chunk two",
            summary="Closing summary.",
            chapters=[Chapter(title="Closing", start_time=11, end_time=20, bullets=["Second point"], detail="Second detail")],
            key_moments=[KeyMoment(time=12, reason="Closing frame", chapter_index=0)],
            key_takeaways=["Shared takeaway", "Second takeaway"],
            action_items=["Review the opening", "Review the closing"],
        ),
    ]
    config = JobConfig(
        transcription_mode=TranscriptionMode.local_faster_whisper,
        note_api_key="note-key",
        note_language=NoteLanguage.en,
        original_filename="long.mp4",
        frame_limit=2,
    )
    debug_log = TaskDebugLog(tmp_path)

    draft = llm.reduce_note_drafts(config, duration=20, partials=partials, system_prompt="system", debug_log=debug_log)

    assert calls == ["note-reduce"]
    assert draft.title == "Chunk one"
    assert "Opening summary." in draft.summary
    assert "Closing summary." in draft.summary
    assert [chapter.title for chapter in draft.chapters] == ["Opening", "Closing"]
    assert [moment.time for moment in draft.key_moments] == [1, 12]
    assert draft.recommended_frame_count == 2
    assert draft.key_takeaways == ["Shared takeaway", "First takeaway", "Second takeaway"]
    assert draft.action_items == ["Review the opening", "Review the closing"]

    log_text = (tmp_path / "debug.log").read_text(encoding="utf-8")
    assert "reduce_note_drafts" in log_text
    assert "fallback" in log_text


def test_generate_chunked_note_draft_falls_back_when_one_chunk_model_call_fails(tmp_path, monkeypatch) -> None:
    reduce_prompts: list[str] = []

    def fake_call_note_model(config, messages, **kwargs):
        context = kwargs.get("debug_context", "")
        if context == "note-chunk-2-of-3":
            raise llm.LLMError("Model returned invalid note JSON: truncated")
        if context == "note-reduce":
            reduce_prompts.append(messages[-1]["content"])
            return NoteDraft(title="merged", summary="merged summary")
        return NoteDraft(
            title=context,
            summary=f"summary for {context}",
            chapters=[Chapter(title=context, start_time=0, end_time=1)],
            key_moments=[KeyMoment(time=0, reason=context, chapter_index=0)],
        )

    monkeypatch.setattr(llm, "call_note_model", fake_call_note_model)
    monkeypatch.setattr(llm, "MAX_CHUNK_TRANSCRIPT_CHARS", 80)

    segments = [
        TranscriptSegment(start=0, end=1, text="first chunk content"),
        TranscriptSegment(start=2, end=3, text="second chunk content that must survive fallback"),
        TranscriptSegment(start=4, end=5, text="third chunk content"),
    ]
    config = JobConfig(
        transcription_mode=TranscriptionMode.local_faster_whisper,
        note_api_key="note-key",
        note_language=NoteLanguage.en,
        original_filename="long.mp4",
    )
    debug_log = TaskDebugLog(tmp_path)

    draft = llm.generate_chunked_note_draft(config, duration=5, segments=segments, system_prompt="system", debug_log=debug_log)

    assert draft.title == "merged"
    assert reduce_prompts
    assert "was skipped" in reduce_prompts[0]
    log_text = (tmp_path / "debug.log").read_text(encoding="utf-8")
    assert "generate_chunked_note_draft" in log_text
    assert "fallback" in log_text
    assert "note-chunk-2-of-3" in log_text


def test_parse_note_draft_strips_replacement_characters() -> None:
    draft = parse_note_draft(
        '{"title":"展��AI大��型","summary":"sum","chapters":[],"key_moments":[{"time":12.0,"reason":"展��AI大��型课程官网","chapter_index":0}],"key_takeaways":[],"action_items":[],"markdown_body":"展��AI大��型"}'
    )

    assert "�" not in draft.title
    assert "�" not in draft.key_moments[0].reason
    assert "�" not in draft.markdown_body



def test_generate_chunked_note_draft_binary_splits_on_moderation_failure(tmp_path, monkeypatch) -> None:
    """When a chunk fails, it should binary-split and retry each half."""
    call_log: list[tuple[str, list[TranscriptSegment]]] = []

    def fake_call_note_model(config, messages, **kwargs):
        context = kwargs.get("debug_context", "")
        if context == "note-reduce":
            return NoteDraft(title="merged", summary="merged")
        # Inspect the prompt to figure out which segments were passed.
        prompt_text = messages[-1]["content"]
        # Fail only the first call to a large chunk; succeed on the split halves.
        if "trigger moderation" in prompt_text:
            call_log.append((context, []))
            raise llm.LLMError("Error code: 400 - content_policy_violation")
        call_log.append((context, []))
        return NoteDraft(
            title=context,
            summary=f"summary for {context}",
            chapters=[Chapter(title=context, start_time=0, end_time=1)],
            key_moments=[KeyMoment(time=0, reason=context, chapter_index=0)],
        )

    monkeypatch.setattr(llm, "call_note_model", fake_call_note_model)
    monkeypatch.setattr(llm, "MAX_CHUNK_TRANSCRIPT_CHARS", 2000)
    monkeypatch.setattr(llm, "MIN_CHUNK_SEGMENTS_FOR_BINARY_RETRY", 3)

    segments = [
        TranscriptSegment(start=i, end=i + 1, text="trigger moderation" if i == 0 else f"clean line {i}")
        for i in range(12)
    ]
    config = JobConfig(
        transcription_mode=TranscriptionMode.local_faster_whisper,
        note_api_key="note-key",
        note_language=NoteLanguage.en,
        original_filename="long.mp4",
    )
    debug_log = TaskDebugLog(tmp_path)

    draft = llm.generate_chunked_note_draft(
        config,
        duration=12,
        segments=segments,
        system_prompt="system",
        debug_log=debug_log,
    )

    assert draft.title == "merged"
    # The initial chunk call should have happened, plus retry calls.
    assert len(call_log) >= 2
    log_text = (tmp_path / "debug.log").read_text(encoding="utf-8")
    assert "binary_split_retry" in log_text


def test_generate_chunked_note_draft_skips_after_minimum_size(tmp_path, monkeypatch) -> None:
    """When a chunk is too small to split, it should skip instead of retrying."""
    def fake_call_note_model(config, messages, **kwargs):
        context = kwargs.get("debug_context", "")
        if context == "note-reduce":
            return NoteDraft(title="merged", summary="merged")
        raise llm.LLMError("content_policy_violation")

    monkeypatch.setattr(llm, "call_note_model", fake_call_note_model)
    monkeypatch.setattr(llm, "MAX_CHUNK_TRANSCRIPT_CHARS", 200)
    monkeypatch.setattr(llm, "MIN_CHUNK_SEGMENTS_FOR_BINARY_RETRY", 3)

    segments = [
        TranscriptSegment(start=i, end=i + 1, text=f"line {i}")
        for i in range(4)
    ]
    config = JobConfig(
        transcription_mode=TranscriptionMode.local_faster_whisper,
        note_api_key="note-key",
        note_language=NoteLanguage.en,
        original_filename="long.mp4",
    )
    debug_log = TaskDebugLog(tmp_path)

    draft = llm.generate_chunked_note_draft(
        config,
        duration=4,
        segments=segments,
        system_prompt="system",
        debug_log=debug_log,
    )

    assert draft.title == "merged"
    log_text = (tmp_path / "debug.log").read_text(encoding="utf-8")
    assert "fallback_to_skipped_chunk" in log_text
    assert "binary_split_retry" not in log_text
