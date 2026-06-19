from backend.app.markdown import render_note_markdown
from backend.app.models import Chapter, KeyMoment, NoteDraft


def test_render_note_markdown_inserts_frame_paths() -> None:
    draft = NoteDraft(
        title="Test Note",
        summary="Summary",
        chapters=[
            Chapter(
                title="Intro",
                start_time=0,
                end_time=10,
                bullets=["Point"],
                detail="Detail",
            )
        ],
        key_moments=[
            KeyMoment(time=3, reason="Opening shot", chapter_index=0, frame_path="frames/frame_001.jpg")
        ],
    )
    markdown = render_note_markdown(draft)
    assert "# Test Note" in markdown
    assert "![Opening shot](frames/frame_001.jpg)" in markdown
    assert "- 原始字幕：[subtitles.md](subtitles.md)" in markdown

