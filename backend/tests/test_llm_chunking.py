from backend.app.llm import build_chunk_prompt, build_reduce_prompt, build_transcript_prompt, chunk_segments
from backend.app.models import JobConfig, NoteDraft, NoteLanguage, NoteStyle, TranscriptSegment, TranscriptionMode


def test_chunk_segments_splits_without_dropping_segments() -> None:
    segments = [TranscriptSegment(start=index, end=index + 1, text="x" * 100) for index in range(5)]
    chunks = chunk_segments(segments, max_chars=260)
    flattened = [segment for chunk in chunks for segment in chunk]
    assert flattened == segments
    assert len(chunks) > 1


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
