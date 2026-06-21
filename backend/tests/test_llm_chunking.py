from backend.app import llm
from backend.app.llm import (
    build_chunk_prompt,
    build_reduce_prompt,
    build_transcript_prompt,
    chunk_segments,
    estimate_prompt_tokens,
    parse_note_draft,
)
from backend.app.models import JobConfig, NoteDraft, NoteLanguage, NoteStyle, TranscriptSegment, TranscriptionMode


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


def test_parse_note_draft_strips_replacement_characters() -> None:
    draft = parse_note_draft(
        '{"title":"展��AI大��型","summary":"sum","chapters":[],"key_moments":[{"time":12.0,"reason":"展��AI大��型课程官网","chapter_index":0}],"key_takeaways":[],"action_items":[],"markdown_body":"展��AI大��型"}'
    )

    assert "�" not in draft.title
    assert "�" not in draft.key_moments[0].reason
    assert "�" not in draft.markdown_body
