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
    assert "JSON timestamp fields start_time, end_time, and time must be numeric seconds" in transcript_prompt
    assert "JSON timestamp fields start_time, end_time, and time must be numeric seconds" in chunk_prompt
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
    assert "JSON timestamp fields start_time, end_time, and time must be numeric seconds" in prompt
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


def test_compact_note_draft_preserves_bounded_markdown_excerpt() -> None:
    draft = NoteDraft(
        title="Skipped",
        summary="Skipped summary",
        markdown_body="## Transcript excerpt\n- [00:00:10 - 00:00:12] Important skipped content.\n" + "tail " * 500,
    )

    compact = llm.compact_note_draft(draft)

    assert "markdown_body" in compact
    assert "Important skipped content" in compact["markdown_body"]
    assert len(compact["markdown_body"]) <= 1000


def test_compact_note_draft_preserves_bounded_quote_times() -> None:
    draft = NoteDraft(
        title="Chunk",
        summary="Summary",
        chapters=[
            Chapter(
                title="Evidence",
                start_time=0,
                end_time=120,
                quote_times=[
                    "00:00:01 - 00:00:05",
                    "00:00:06 - 00:00:10",
                    "00:00:11 - 00:00:15",
                    "00:00:16 - 00:00:20",
                    "00:00:21 - 00:00:25",
                ],
            )
        ],
    )

    compact = llm.compact_note_draft(draft)

    quote_times = compact["chapters"][0]["quote_times"]
    assert quote_times == [
        "00:00:01 - 00:00:05",
        "00:00:06 - 00:00:10",
        "00:00:11 - 00:00:15",
    ]


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


def test_reduce_note_drafts_deterministic_merge_respects_frame_limit_24(monkeypatch) -> None:
    def fake_call_note_model(config, messages, **kwargs):
        raise llm.LLMError("Model returned invalid note JSON: truncated")

    monkeypatch.setattr(llm, "call_note_model", fake_call_note_model)

    partials = [
        NoteDraft(
            title=f"Chunk {chunk}",
            summary=f"Summary {chunk}.",
            key_moments=[
                KeyMoment(time=chunk * 10 + index, reason=f"moment {chunk}-{index}", chapter_index=0)
                for index in range(9)
            ],
        )
        for chunk in range(2)
    ]
    config = JobConfig(
        transcription_mode=TranscriptionMode.local_faster_whisper,
        note_api_key="note-key",
        note_language=NoteLanguage.en,
        original_filename="long.mp4",
        frame_limit=24,
    )

    draft = llm.reduce_note_drafts(config, duration=20, partials=partials, system_prompt="system")

    assert len(draft.key_moments) == 18
    assert draft.recommended_frame_count == 18


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


def test_chunked_note_generation_carries_prior_takeaways_and_actions(tmp_path, monkeypatch) -> None:
    chunk_prompts: dict[str, str] = {}

    def fake_call_note_model(config, messages, **kwargs):
        context = kwargs.get("debug_context", "")
        if context == "note-chunk-1-of-2":
            return NoteDraft(
                title="Chunk one",
                summary="Earlier summary.",
                key_takeaways=["Important earlier concept"],
                action_items=["Review the earlier derivation"],
            )
        if context == "note-chunk-2-of-2":
            chunk_prompts[context] = messages[-1]["content"]
            return NoteDraft(title="Chunk two", summary="Later summary.")
        if context == "note-reduce":
            return NoteDraft(title="Merged", summary="Merged summary.")
        raise AssertionError(f"unexpected context {context}")

    monkeypatch.setattr(llm, "call_note_model", fake_call_note_model)
    monkeypatch.setattr(llm, "MAX_CHUNK_TRANSCRIPT_CHARS", 80)

    segments = [
        TranscriptSegment(start=0, end=1, text="first chunk content"),
        TranscriptSegment(start=2, end=3, text="second chunk content"),
    ]
    config = JobConfig(
        transcription_mode=TranscriptionMode.local_faster_whisper,
        note_api_key="note-key",
        note_language=NoteLanguage.en,
        original_filename="long.mp4",
    )

    llm.generate_chunked_note_draft(
        config,
        duration=5,
        segments=segments,
        system_prompt="system",
        debug_log=TaskDebugLog(tmp_path),
    )

    prompt = chunk_prompts["note-chunk-2-of-2"]
    assert "Prior context (summaries, takeaways, and actions from earlier chunks)" in prompt
    assert "Earlier summary." in prompt
    assert "Important earlier concept" in prompt
    assert "Review the earlier derivation" in prompt


def test_prior_context_is_bounded_and_keeps_recent_chunks() -> None:
    drafts = [
        NoteDraft(
            title=f"Chunk {index}",
            summary=f"summary {index} " + ("x" * 300),
            key_takeaways=[f"takeaway {index} " + ("y" * 180)],
            action_items=[f"action {index} " + ("z" * 180)],
        )
        for index in range(60)
    ]

    context = llm._build_prior_context(drafts)

    assert len(context) <= llm.MAX_PRIOR_CONTEXT_CHARS
    assert "Chunk 59" in context
    assert "takeaway 59" in context
    assert "action 59" in context
    assert "Chunk 0" not in context


def test_prior_context_truncates_pathologically_long_titles() -> None:
    draft = NoteDraft(
        title="Chunk with useful prefix " + ("title overflow " * 500),
        summary="recent summary",
    )

    context = llm._build_prior_context([draft])

    assert len(context) <= llm.MAX_PRIOR_CONTEXT_CHARS
    assert "Chunk with useful prefix" in context
    assert "title overflow " * 20 not in context
    assert "recent summary" in context


def test_generate_chunked_note_draft_uses_note_language_for_skipped_chunk_fallback(tmp_path, monkeypatch) -> None:
    reduce_prompts: list[str] = []

    def fake_call_note_model(config, messages, **kwargs):
        context = kwargs.get("debug_context", "")
        if context == "note-reduce":
            reduce_prompts.append(messages[-1]["content"])
            return NoteDraft(title="merged", summary="merged summary")
        raise llm.LLMError("content_policy_violation")

    monkeypatch.setattr(llm, "call_note_model", fake_call_note_model)

    segments = [TranscriptSegment(start=10, end=20, text="这一小段触发了模型拒绝。")]
    config = JobConfig(
        transcription_mode=TranscriptionMode.local_faster_whisper,
        note_api_key="note-key",
        note_language=NoteLanguage.zh,
        original_filename="long.mp4",
    )

    draft = llm.generate_chunked_note_draft(
        config,
        duration=20,
        segments=segments,
        system_prompt="system",
        debug_log=TaskDebugLog(tmp_path),
    )

    assert draft.title == "merged"
    assert reduce_prompts
    assert "已跳过" in reduce_prompts[0]
    assert "was skipped" not in reduce_prompts[0]


def test_skipped_chunk_fallback_preserves_transcript_excerpt() -> None:
    segments = [
        TranscriptSegment(start=10, end=12, text="First important sentence from the skipped chunk."),
        TranscriptSegment(start=13, end=15, text="Second important sentence that should remain visible."),
    ]

    draft = llm.fallback_note_draft_from_chunk(2, 5, segments, NoteLanguage.en.value)

    assert "00:00:10 - 00:00:15" in draft.summary
    assert "First important sentence" in draft.markdown_body
    assert "Second important sentence" in draft.markdown_body


def test_skipped_chunk_fallback_includes_failure_reason() -> None:
    segments = [
        TranscriptSegment(start=10, end=12, text="First important sentence from the skipped chunk."),
    ]

    draft = llm.fallback_note_draft_from_chunk(
        2,
        5,
        segments,
        NoteLanguage.en.value,
        failure_reason="Error code: 400 - content_policy_violation with a very long provider payload " + "x" * 400,
    )

    assert "Reason: Error code: 400 - content_policy_violation" in draft.summary
    assert len(draft.summary) < 360


def test_parse_note_draft_strips_replacement_characters() -> None:
    draft = parse_note_draft(
        '{"title":"展��AI大��型","summary":"sum","chapters":[],"key_moments":[{"time":12.0,"reason":"展��AI大��型课程官网","chapter_index":0}],"key_takeaways":[],"action_items":[],"markdown_body":"展��AI大��型"}'
    )

    assert "�" not in draft.title
    assert "�" not in draft.key_moments[0].reason
    assert "�" not in draft.markdown_body


def test_parse_note_draft_ignores_trailing_text_with_braces() -> None:
    draft = parse_note_draft(
        'Here is the note JSON:\n{"title":"Demo","summary":"Summary","chapters":[],"key_moments":[]}\nDo not render {debug} in the final note.'
    )

    assert draft.title == "Demo"
    assert draft.summary == "Summary"


def test_parse_note_draft_skips_non_note_json_candidates() -> None:
    draft = parse_note_draft(
        'Example object: {"not_a_note": true}\nActual note:\n{"title":"Actual","summary":"Useful","chapters":[],"key_moments":[]}'
    )

    assert draft.title == "Actual"
    assert draft.summary == "Useful"


def test_parse_note_draft_accepts_provider_wrapped_note_json() -> None:
    draft = parse_note_draft(
        '{"note":{"title":"Wrapped","summary":"Useful","chapters":[],"key_moments":[]}}'
    )

    assert draft.title == "Wrapped"
    assert draft.summary == "Useful"


def test_parse_note_draft_accepts_provider_wrapped_note_json_string() -> None:
    draft = parse_note_draft(
        '{"output":"{\\"title\\":\\"String Wrapped\\",\\"summary\\":\\"Useful\\",\\"chapters\\":[],\\"key_moments\\":[]}"}'
    )

    assert draft.title == "String Wrapped"
    assert draft.summary == "Useful"


def test_parse_note_draft_accepts_provider_wrapped_note_json_array() -> None:
    draft = parse_note_draft(
        '{"data":[{"title":"Array In Wrapper","summary":"Useful","chapters":[],"key_moments":[]}]}'
    )

    assert draft.title == "Array In Wrapper"
    assert draft.summary == "Useful"


def test_parse_note_draft_accepts_embedded_provider_wrapped_note_json_string() -> None:
    draft = parse_note_draft(
        'Here is the note:\n{"output":"{\\"title\\":\\"Embedded Wrapped\\",\\"summary\\":\\"Useful\\",\\"chapters\\":[],\\"key_moments\\":[]}"}'
    )

    assert draft.title == "Embedded Wrapped"
    assert draft.summary == "Useful"


def test_parse_note_draft_accepts_single_item_array() -> None:
    draft = parse_note_draft(
        '[{"title":"Array Wrapped","summary":"Useful","chapters":[],"key_moments":[]}]'
    )

    assert draft.title == "Array Wrapped"
    assert draft.summary == "Useful"


def test_parse_note_draft_defaults_missing_summary_from_model() -> None:
    draft = parse_note_draft('{"title":"Sparse","chapters":[],"key_moments":[]}')

    assert draft.title == "Sparse"
    assert draft.summary == ""


def test_parse_note_draft_accepts_hhmmss_timestamps_from_model() -> None:
    draft = parse_note_draft(
        '{"title":"DenseNet","summary":"sum","chapters":[{"title":"Dense block","start_time":"02:36:59","end_time":"02:47:30"}],"key_moments":[{"time":"02:37:48","reason":"skip connection","chapter_index":0}],"recommended_frame_count":2}'
    )

    assert draft.chapters[0].start_time == 9419
    assert draft.chapters[0].end_time == 10050
    assert draft.key_moments[0].time == 9468


def test_parse_note_draft_accepts_mmss_timestamps_from_model() -> None:
    draft = parse_note_draft(
        '{"title":"CNN","summary":"sum","chapters":[{"title":"Convolution","start_time":"24:45","end_time":"26:01"}],"key_moments":[{"time":"25:18.5","reason":"local connection","chapter_index":0}],"recommended_frame_count":2}'
    )

    assert draft.chapters[0].start_time == 1485
    assert draft.chapters[0].end_time == 1561
    assert draft.key_moments[0].time == 1518.5


def test_parse_note_draft_accepts_chapter_time_ranges_from_model() -> None:
    draft = parse_note_draft(
        '{"title":"CNN","summary":"sum","chapters":[{"title":"Convolution","start_time":"24:45 - 26:01","end_time":"24:45 - 26:01"}],"key_moments":[],"recommended_frame_count":2}'
    )

    assert draft.chapters[0].start_time == 1485
    assert draft.chapters[0].end_time == 1561


def test_parse_note_draft_accepts_key_moment_time_ranges_from_model() -> None:
    draft = parse_note_draft(
        '{"title":"CNN","summary":"sum","chapters":[],"key_moments":[{"time":"24:45 - 26:01","reason":"local connection","chapter_index":0}],"recommended_frame_count":2}'
    )

    assert draft.key_moments[0].time == 1485


def test_parse_note_draft_accepts_fullwidth_colon_timestamps_from_model() -> None:
    draft = parse_note_draft(
        '{"title":"CNN","summary":"sum","chapters":[{"title":"Convolution","start_time":"24：45","end_time":"24：45 - 26：01"}],"key_moments":[{"time":"25：18.5","reason":"local connection","chapter_index":0}],"recommended_frame_count":2}'
    )

    assert draft.chapters[0].start_time == 1485
    assert draft.chapters[0].end_time == 1561
    assert draft.key_moments[0].time == 1518.5


def test_parse_note_draft_treats_null_default_fields_as_empty() -> None:
    draft = parse_note_draft(
        '{"title":"CNN","summary":"sum","chapters":[{"title":"Convolution","start_time":0,"end_time":10,"bullets":null,"detail":null,"quote_times":null}],"key_moments":null,"key_takeaways":null,"action_items":null,"markdown_body":null}'
    )

    assert draft.chapters[0].bullets == []
    assert draft.chapters[0].detail == ""
    assert draft.chapters[0].quote_times == []
    assert draft.key_moments == []
    assert draft.key_takeaways == []
    assert draft.action_items == []
    assert draft.markdown_body == ""
    assert draft.recommended_frame_count == 1


def test_parse_note_draft_wraps_string_list_fields() -> None:
    draft = parse_note_draft(
        '{"title":"CNN","summary":"sum","chapters":[{"title":"Convolution","start_time":0,"end_time":10,"bullets":"single bullet","quote_times":"00:00:01 - 00:00:02"}],"key_moments":[],"key_takeaways":"single takeaway","action_items":"single action"}'
    )

    assert draft.chapters[0].bullets == ["single bullet"]
    assert draft.chapters[0].quote_times == ["00:00:01 - 00:00:02"]
    assert draft.key_takeaways == ["single takeaway"]
    assert draft.action_items == ["single action"]


def test_parse_note_draft_wraps_single_object_note_lists() -> None:
    draft = parse_note_draft(
        '{"title":"CNN","summary":"sum","chapters":{"title":"Only chapter","start_time":0,"end_time":10},"key_moments":{"time":3,"reason":"single frame","chapter_index":0}}'
    )

    assert len(draft.chapters) == 1
    assert draft.chapters[0].title == "Only chapter"
    assert len(draft.key_moments) == 1
    assert draft.key_moments[0].reason == "single frame"


def test_parse_note_draft_defaults_missing_chapter_times_from_model() -> None:
    draft = parse_note_draft(
        '{"title":"Opening","summary":"sum","chapters":[{"title":"Course opening"}],"key_moments":[]}'
    )

    assert draft.chapters[0].start_time == 0
    assert draft.chapters[0].end_time == 0


def test_parse_note_draft_treats_zero_recommended_frame_count_as_missing() -> None:
    draft = parse_note_draft(
        '{"title":"Ending","summary":"sum","chapters":[],"key_moments":[],"recommended_frame_count":0}'
    )

    assert draft.recommended_frame_count == 1


def test_parse_note_draft_accepts_recommended_frame_count_up_to_product_limit() -> None:
    draft = parse_note_draft(
        '{"title":"Frames","summary":"sum","chapters":[],"key_moments":[],"recommended_frame_count":24}'
    )

    assert draft.recommended_frame_count == 24


def test_parse_note_draft_fallback_frame_count_uses_product_limit() -> None:
    moments = ",".join(
        f'{{"time":{index},"reason":"moment {index}","chapter_index":0}}'
        for index in range(18)
    )

    draft = parse_note_draft(
        f'{{"title":"Frames","summary":"sum","chapters":[],"key_moments":[{moments}]}}'
    )

    assert draft.recommended_frame_count == 18


def test_parse_note_draft_treats_empty_recommended_frame_count_strings_as_missing() -> None:
    zero_string = parse_note_draft(
        '{"title":"Ending","summary":"sum","chapters":[],"key_moments":[{"time":2,"reason":"frame"}],"recommended_frame_count":"0"}'
    )
    blank_string = parse_note_draft(
        '{"title":"Ending","summary":"sum","chapters":[],"key_moments":[],"recommended_frame_count":""}'
    )

    assert zero_string.recommended_frame_count == 1
    assert blank_string.recommended_frame_count == 1


def test_parse_note_draft_accepts_text_recommended_frame_count() -> None:
    draft = parse_note_draft(
        '{"title":"Frames","summary":"sum","chapters":[],"key_moments":[],"recommended_frame_count":"about 6 frames"}'
    )

    assert draft.recommended_frame_count == 6


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


def test_generate_chunked_note_draft_uses_distinct_debug_contexts_for_split_retries(tmp_path, monkeypatch) -> None:
    contexts: list[str] = []

    def fake_call_note_model(config, messages, **kwargs):
        context = kwargs.get("debug_context", "")
        if context == "note-reduce":
            return NoteDraft(title="merged", summary="merged")
        contexts.append(context)
        if "trigger moderation" in messages[-1]["content"]:
            raise llm.LLMError("content_policy_violation")
        return NoteDraft(title=context, summary=context)

    monkeypatch.setattr(llm, "call_note_model", fake_call_note_model)
    monkeypatch.setattr(llm, "MAX_CHUNK_TRANSCRIPT_CHARS", 2000)
    monkeypatch.setattr(llm, "MIN_CHUNK_SEGMENTS_FOR_BINARY_RETRY", 3)

    segments = [
        TranscriptSegment(start=i, end=i + 1, text="trigger moderation" if i == 0 else f"clean line {i}")
        for i in range(6)
    ]
    config = JobConfig(
        transcription_mode=TranscriptionMode.local_faster_whisper,
        note_api_key="note-key",
        note_language=NoteLanguage.en,
        original_filename="long.mp4",
    )

    llm.generate_chunked_note_draft(config, duration=6, segments=segments, system_prompt="system", debug_log=TaskDebugLog(tmp_path))

    assert contexts[0] == "note-chunk-1-of-1"
    assert "note-chunk-1-of-1-left" in contexts
    assert "note-chunk-1-of-1-right" in contexts
    assert len(set(contexts)) == len(contexts)


def test_generate_chunked_note_draft_passes_left_split_summary_to_right_split(tmp_path, monkeypatch) -> None:
    right_prompts: list[str] = []

    def fake_call_note_model(config, messages, **kwargs):
        context = kwargs.get("debug_context", "")
        if context == "note-reduce":
            return NoteDraft(title="merged", summary="merged")
        if context == "note-chunk-1-of-1":
            raise llm.LLMError("content_policy_violation")
        if context == "note-chunk-1-of-1-right":
            right_prompts.append(messages[-1]["content"])
            return NoteDraft(title="Right half", summary="Right half summary.")
        return NoteDraft(title="Left half", summary="Left half summary.")

    monkeypatch.setattr(llm, "call_note_model", fake_call_note_model)
    monkeypatch.setattr(llm, "MAX_CHUNK_TRANSCRIPT_CHARS", 2000)
    monkeypatch.setattr(llm, "MIN_CHUNK_SEGMENTS_FOR_BINARY_RETRY", 3)

    segments = [
        TranscriptSegment(start=i, end=i + 1, text=f"line {i}")
        for i in range(6)
    ]
    config = JobConfig(
        transcription_mode=TranscriptionMode.local_faster_whisper,
        note_api_key="note-key",
        note_language=NoteLanguage.en,
        original_filename="long.mp4",
    )

    llm.generate_chunked_note_draft(config, duration=6, segments=segments, system_prompt="system", debug_log=TaskDebugLog(tmp_path))

    assert right_prompts
    assert "Left half summary." in right_prompts[0]


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
