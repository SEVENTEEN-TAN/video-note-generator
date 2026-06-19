from __future__ import annotations

from .models import KeyMoment, NoteDraft
from .time_utils import seconds_to_hhmmss


def key_moments_for_chapter(
    key_moments: list[KeyMoment],
    chapter_index: int,
    chapter_start: float,
    chapter_end: float,
) -> list[KeyMoment]:
    matches: list[KeyMoment] = []
    for moment in key_moments:
        if moment.chapter_index == chapter_index or chapter_start <= moment.time <= chapter_end:
            matches.append(moment)
    return matches


def render_note_markdown(draft: NoteDraft, transcript_filename: str = "subtitles.md") -> str:
    lines: list[str] = [
        f"# {draft.title}",
        "",
        "## 摘要",
        "",
        draft.summary.strip(),
        "",
        "## 目录",
        "",
    ]

    for index, chapter in enumerate(draft.chapters, start=1):
        lines.append(
            f"{index}. [{chapter.title}](#{slugify(chapter.title)}) "
            f"`{seconds_to_hhmmss(chapter.start_time)} - {seconds_to_hhmmss(chapter.end_time)}`"
        )

    lines.extend(["", "## 分章节笔记", ""])
    for index, chapter in enumerate(draft.chapters):
        lines.extend(
            [
                f"### {chapter.title}",
                "",
                f"`{seconds_to_hhmmss(chapter.start_time)} - {seconds_to_hhmmss(chapter.end_time)}`",
                "",
            ]
        )
        for moment in key_moments_for_chapter(
            draft.key_moments,
            index,
            chapter.start_time,
            chapter.end_time,
        ):
            if moment.frame_path:
                lines.extend(
                    [
                        f"![{moment.reason}]({moment.frame_path})",
                        "",
                        f"> 关键帧：`{seconds_to_hhmmss(moment.time)}`，{moment.reason}",
                        "",
                    ]
                )
        if chapter.bullets:
            for bullet in chapter.bullets:
                lines.append(f"- {bullet}")
            lines.append("")
        if chapter.detail:
            lines.extend([chapter.detail.strip(), ""])
        if chapter.quote_times:
            lines.append("参考时间：")
            for quote_time in chapter.quote_times:
                lines.append(f"- `{quote_time}`")
            lines.append("")

    if draft.key_takeaways:
        lines.extend(["## 关键结论", ""])
        for takeaway in draft.key_takeaways:
            lines.append(f"- {takeaway}")
        lines.append("")

    if draft.action_items:
        lines.extend(["## 可行动清单", ""])
        for action_item in draft.action_items:
            lines.append(f"- [ ] {action_item}")
        lines.append("")

    if draft.markdown_body:
        lines.extend(["## 补充笔记", "", draft.markdown_body.strip(), ""])

    lines.extend(
        [
            "## 附录",
            "",
            f"- 原始字幕：[{transcript_filename}]({transcript_filename})",
            "",
        ]
    )
    return "\n".join(lines)


def slugify(value: str) -> str:
    return value.strip().lower().replace(" ", "-")

