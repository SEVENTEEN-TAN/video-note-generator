from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from .models import ChapterQualityReport, QualityIssue, QualityReport, QualityScores, TranscriptPayload
from .time_utils import seconds_to_hhmmss


LOW_COVERAGE_TRANSCRIPT_CHARS = 900
LOW_COVERAGE_NOTE_CHARS = 180
LONG_CHAPTER_TRANSCRIPT_CHARS = 1800
LONG_CHAPTER_NOTE_CHARS = 360
IMAGE_PATTERN = re.compile(r"!\[[^\]]*\]\(([^)]+)\)")
HEADING_PATTERN = re.compile(r"^###\s+(.+?)\s*$")
TIME_RANGE_PATTERN = re.compile(r"`?(\d{2}:\d{2}:\d{2})\s+-\s+(\d{2}:\d{2}:\d{2})`?")
REFERENCE_TIME_PATTERN = re.compile(r"\d{2}:\d{2}:\d{2}\s+-\s+\d{2}:\d{2}:\d{2}")


@dataclass(frozen=True)
class NoteSection:
    index: int
    title: str
    start_time: float
    end_time: float
    body: str
    image_paths: list[str]
    has_reference_times: bool


@dataclass(frozen=True)
class QualityReportPaths:
    json_path: Path
    markdown_path: Path


def build_quality_report(job_dir: Path) -> QualityReport:
    note_text = _read_text(job_dir / "note.md", encoding="utf-8-sig")
    transcript = _read_transcript(job_dir / "transcript.json")
    sections = _parse_note_sections(note_text)
    chapter_reports: list[ChapterQualityReport] = []
    issues: list[QualityIssue] = []

    for section in sections:
        transcript_chars = _transcript_chars_for_range(transcript, section.start_time, section.end_time)
        note_chars = _visible_text_chars(section.body)
        section_issue_types: list[str] = []

        if _is_low_coverage(transcript_chars, note_chars):
            section_issue_types.append("low_chapter_coverage")
            issues.append(
                QualityIssue(
                    severity="warning",
                    type="low_chapter_coverage",
                    message="Chapter note is short compared with transcript coverage.",
                    chapter_index=section.index,
                )
            )

        if not section.image_paths:
            section_issue_types.append("missing_chapter_frame")
            issues.append(
                QualityIssue(
                    severity="warning",
                    type="missing_chapter_frame",
                    message="Chapter has no selected frame.",
                    chapter_index=section.index,
                )
            )

        if not section.has_reference_times:
            section_issue_types.append("missing_timestamp_reference")
            issues.append(
                QualityIssue(
                    severity="info",
                    type="missing_timestamp_reference",
                    message="Chapter has no explicit reference timestamp range.",
                    chapter_index=section.index,
                )
            )

        chapter_reports.append(
            ChapterQualityReport(
                chapter_index=section.index,
                title=section.title,
                start_time=section.start_time,
                end_time=section.end_time,
                transcript_chars=transcript_chars,
                note_chars=note_chars,
                selected_frame_count=len(section.image_paths),
                issues=section_issue_types,
            )
        )

    _append_duplicate_frame_issues(sections, issues)
    _append_generation_stability_issues(job_dir, issues)

    scores = _score_report(sections, chapter_reports, issues)
    return QualityReport(
        status=_status_from_scores(scores, issues),
        scores=scores,
        issues=issues,
        chapter_reports=chapter_reports,
    )


def write_quality_report(job_dir: Path, report: QualityReport) -> QualityReportPaths:
    review_dir = job_dir / "review"
    review_dir.mkdir(parents=True, exist_ok=True)
    json_path = review_dir / "quality_report.json"
    markdown_path = review_dir / "quality_report.md"
    json_path.write_text(report.model_dump_json(indent=2), encoding="utf-8")
    markdown_path.write_text(render_quality_report_markdown(report), encoding="utf-8")
    return QualityReportPaths(json_path=json_path, markdown_path=markdown_path)


def load_quality_report(job_dir: Path) -> QualityReport | None:
    path = job_dir / "review" / "quality_report.json"
    if not path.exists():
        return None
    try:
        return QualityReport.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def render_quality_report_markdown(report: QualityReport) -> str:
    lines = [
        "# Quality Report",
        "",
        f"- Status: `{report.status}`",
        f"- Coverage: `{report.scores.coverage:.2f}`",
        f"- Structure: `{report.scores.structure:.2f}`",
        f"- Frames: `{report.scores.frames:.2f}`",
        f"- Stability: `{report.scores.stability:.2f}`",
        "",
        "## Issues",
        "",
    ]
    if report.issues:
        for issue in report.issues:
            location = f" chapter {issue.chapter_index + 1}" if issue.chapter_index is not None else ""
            lines.append(f"- `{issue.severity}` `{issue.type}`{location}: {issue.message}")
    else:
        lines.append("- No measurable issues detected.")
    lines.extend(["", "## Chapter Coverage", ""])
    for chapter in report.chapter_reports:
        lines.append(
            f"- {chapter.chapter_index + 1}. {chapter.title} "
            f"`{seconds_to_hhmmss(chapter.start_time)} - {seconds_to_hhmmss(chapter.end_time)}` "
            f"transcript={chapter.transcript_chars} note={chapter.note_chars} frames={chapter.selected_frame_count}"
        )
    lines.append("")
    return "\n".join(lines)


def _read_text(path: Path, *, encoding: str) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding=encoding)


def _read_transcript(path: Path) -> TranscriptPayload:
    if not path.exists():
        return TranscriptPayload()
    return TranscriptPayload.model_validate_json(path.read_text(encoding="utf-8"))


def _parse_note_sections(note_text: str) -> list[NoteSection]:
    lines = note_text.splitlines()
    heading_indexes = [(index, match.group(1).strip()) for index, line in enumerate(lines) if (match := HEADING_PATTERN.match(line))]
    sections: list[NoteSection] = []
    for section_index, (line_index, title) in enumerate(heading_indexes):
        next_line_index = heading_indexes[section_index + 1][0] if section_index + 1 < len(heading_indexes) else len(lines)
        body_lines = lines[line_index + 1 : next_line_index]
        start_time, end_time = _find_section_time_range(body_lines)
        body = "\n".join(body_lines)
        sections.append(
            NoteSection(
                index=section_index,
                title=title,
                start_time=start_time,
                end_time=end_time,
                body=body,
                image_paths=IMAGE_PATTERN.findall(body),
                has_reference_times=bool(REFERENCE_TIME_PATTERN.search(body)),
            )
        )
    if sections:
        return sections
    return [
        NoteSection(
            index=0,
            title="全文",
            start_time=0,
            end_time=0,
            body=note_text,
            image_paths=IMAGE_PATTERN.findall(note_text),
            has_reference_times=bool(REFERENCE_TIME_PATTERN.search(note_text)),
        )
    ]


def _find_section_time_range(lines: list[str]) -> tuple[float, float]:
    for line in lines[:8]:
        match = TIME_RANGE_PATTERN.search(line)
        if match:
            return _hhmmss_to_seconds(match.group(1)), _hhmmss_to_seconds(match.group(2))
    return 0.0, 0.0


def _hhmmss_to_seconds(value: str) -> float:
    hours, minutes, seconds = [int(part) for part in value.split(":")]
    return float(hours * 3600 + minutes * 60 + seconds)


def _transcript_chars_for_range(transcript: TranscriptPayload, start_time: float, end_time: float) -> int:
    if end_time <= start_time:
        return len(transcript.text)
    return sum(len(segment.text) for segment in transcript.segments if segment.end >= start_time and segment.start <= end_time)


def _visible_text_chars(markdown: str) -> int:
    without_images = IMAGE_PATTERN.sub("", markdown)
    without_code_ticks = without_images.replace("`", "")
    return len("".join(char for char in without_code_ticks if not char.isspace()))


def _is_low_coverage(transcript_chars: int, note_chars: int) -> bool:
    if transcript_chars >= LONG_CHAPTER_TRANSCRIPT_CHARS:
        return note_chars < LONG_CHAPTER_NOTE_CHARS
    if transcript_chars >= LOW_COVERAGE_TRANSCRIPT_CHARS:
        return note_chars < LOW_COVERAGE_NOTE_CHARS
    return False


def _append_duplicate_frame_issues(sections: list[NoteSection], issues: list[QualityIssue]) -> None:
    seen: set[str] = set()
    duplicate_paths: set[str] = set()
    duplicate_chapter: dict[str, int] = {}
    for section in sections:
        for path in section.image_paths:
            if path in seen:
                duplicate_paths.add(path)
                duplicate_chapter.setdefault(path, section.index)
            else:
                seen.add(path)
    for path in sorted(duplicate_paths):
        issues.append(
            QualityIssue(
                severity="warning",
                type="duplicate_frame_reference",
                message="The same frame is referenced more than once.",
                chapter_index=duplicate_chapter.get(path),
                frame_ids=[path],
            )
        )


def _append_generation_stability_issues(job_dir: Path, issues: list[QualityIssue]) -> None:
    log_path = job_dir / "debug.log"
    if not log_path.exists():
        return
    instability_count = 0
    for line in log_path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        message = str(event.get("message") or "")
        stage = str(event.get("stage") or "")
        details = event.get("details") if isinstance(event.get("details"), dict) else {}
        finish_reason = str(details.get("finish_reason") or "")
        if message in {"invalid_json", "failed"} or "fallback" in message or finish_reason in {"length", "content_filter"}:
            instability_count += 1
        if stage == "reduce_note_drafts" and message == "fallback_to_deterministic_merge":
            instability_count += 1
    if instability_count:
        issues.append(
            QualityIssue(
                severity="warning",
                type="generation_instability",
                message=f"Generation had {instability_count} retry, fallback, or truncation signals.",
            )
        )


def _score_report(
    sections: list[NoteSection],
    chapters: list[ChapterQualityReport],
    issues: list[QualityIssue],
) -> QualityScores:
    chapter_count = max(1, len(chapters))
    low_coverage = sum("low_chapter_coverage" in chapter.issues for chapter in chapters)
    missing_frames = sum("missing_chapter_frame" in chapter.issues for chapter in chapters)
    missing_refs = sum("missing_timestamp_reference" in chapter.issues for chapter in chapters)
    duplicate_frames = sum(issue.type == "duplicate_frame_reference" for issue in issues)
    instability = sum(issue.type == "generation_instability" for issue in issues)
    coverage = _clamp01(1.0 - (low_coverage / chapter_count) * 0.7 - (missing_refs / chapter_count) * 0.2)
    structure = _clamp01(1.0 if sections else 0.0)
    frames = _clamp01(1.0 - (missing_frames / chapter_count) * 0.6 - min(0.4, duplicate_frames * 0.2))
    stability = _clamp01(1.0 - min(0.8, instability * 0.25))
    return QualityScores(coverage=coverage, structure=structure, frames=frames, stability=stability)


def _status_from_scores(scores: QualityScores, issues: list[QualityIssue]) -> str:
    if any(issue.severity == "error" for issue in issues) or min(scores.coverage, scores.frames, scores.stability) < 0.5:
        return "needs_attention"
    if issues or min(scores.coverage, scores.frames, scores.stability) < 0.8:
        return "review_recommended"
    return "ready"


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, round(value, 2)))
