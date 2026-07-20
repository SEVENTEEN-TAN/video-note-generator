from __future__ import annotations

import hashlib
import re
import shutil
from collections import defaultdict
from pathlib import Path

from .frame_candidates import load_frame_candidate_index
from .models import FrameCandidate, ReviewDraft
from .note_versions import get_note_version, load_note_version_index, resolve_job_relative_path
from .review_drafts import load_review_draft
from .time_utils import seconds_to_hhmmss


NOTE_REVIEW_PENDING_MARKER = ".note-review.pending"
IMAGE_LINE_PATTERN = re.compile(r"^\s*!\[[^\]]*]\([^)]+\)\s*$")
HEADING_PATTERN = re.compile(r"^###\s+")
TIME_RANGE_PATTERN = re.compile(r"`?\d{2}:\d{2}:\d{2}\s+-\s+\d{2}:\d{2}:\d{2}`?")


def mark_note_review_pending(job_dir: Path) -> None:
    (job_dir / NOTE_REVIEW_PENDING_MARKER).write_text("1", encoding="utf-8")


def is_note_review_pending(job_dir: Path) -> bool:
    return (job_dir / NOTE_REVIEW_PENDING_MARKER).exists()


def finalize_reviewed_note(job_dir: Path, version_id: str | None = None) -> None:
    marker = job_dir / NOTE_REVIEW_PENDING_MARKER
    if not marker.exists():
        raise PermissionError("note review is not pending.")
    review_draft = load_review_draft(job_dir, version_id)
    selected = _selected_candidates_from_review_draft(job_dir, review_draft) if review_draft else _selected_candidates(job_dir)
    if not selected:
        raise ValueError("No selected frame candidates.")
    frame_map = _copy_selected_frames(job_dir, selected)
    source_note = (job_dir / "note.md").read_text(encoding="utf-8-sig")
    if review_draft is not None:
        source_hash = hashlib.sha256(source_note.encode("utf-8")).hexdigest()
        if review_draft.source_note_sha256 != source_hash:
            raise ValueError("The note changed after the review draft was created. Reload the review draft before finalizing.")
    final_note = (
        _render_note_with_review_draft(source_note, review_draft, selected, frame_map)
        if review_draft
        else _render_note_with_selected_frames(source_note, selected, frame_map)
    )
    (job_dir / "note.md").write_text(final_note, encoding="utf-8-sig")
    _sync_active_note_version(job_dir, final_note)
    marker.unlink()


def _selected_candidates(job_dir: Path) -> list[FrameCandidate]:
    index = load_frame_candidate_index(job_dir)
    if index is None:
        raise FileNotFoundError("Frame candidates are not available.")
    return sorted(
        [candidate for candidate in index.candidates if candidate.selected and not candidate.rejected],
        key=lambda candidate: (candidate.chapter_index, candidate.time, candidate.id),
    )


def _selected_candidates_from_review_draft(job_dir: Path, draft: ReviewDraft | None) -> list[FrameCandidate]:
    if draft is None:
        return _selected_candidates(job_dir)
    index = load_frame_candidate_index(job_dir)
    if index is None:
        raise FileNotFoundError("Frame candidates are not available.")
    candidate_by_id = {candidate.id: candidate for candidate in index.candidates}
    selected_ids: list[str] = []
    for paragraph in draft.paragraphs:
        selected_ids.extend(paragraph.selected_frame_ids)
    missing_ids = [candidate_id for candidate_id in selected_ids if candidate_id not in candidate_by_id]
    if missing_ids:
        raise FileNotFoundError(f"Selected frame candidate is missing: {missing_ids[0]}")
    return sorted(
        [candidate_by_id[candidate_id] for candidate_id in selected_ids],
        key=lambda candidate: (candidate.chapter_index, candidate.time, candidate.id),
    )


def _copy_selected_frames(job_dir: Path, selected: list[FrameCandidate]) -> dict[str, str]:
    temp_frames = job_dir / "frames.finalizing"
    if temp_frames.exists():
        shutil.rmtree(temp_frames)
    temp_frames.mkdir(parents=True)
    frame_map: dict[str, str] = {}
    for index, candidate in enumerate(selected, start=1):
        source_path = resolve_job_relative_path(job_dir, candidate.path)
        if not source_path.exists() or not source_path.is_file():
            raise FileNotFoundError(f"Selected frame is missing: {candidate.id}")
        frame_rel = f"frames/frame_{index:03d}.jpg"
        shutil.copyfile(source_path, job_dir / "frames.finalizing" / f"frame_{index:03d}.jpg")
        frame_map[candidate.id] = frame_rel

    root_frames = job_dir / "frames"
    if root_frames.exists():
        shutil.rmtree(root_frames)
    temp_frames.replace(root_frames)
    return frame_map


def _render_note_with_selected_frames(
    note_text: str,
    selected: list[FrameCandidate],
    frame_map: dict[str, str],
) -> str:
    by_chapter: dict[int, list[FrameCandidate]] = defaultdict(list)
    for candidate in selected:
        by_chapter[candidate.chapter_index].append(candidate)

    rendered: list[str] = []
    current_chapter = -1
    inserted_chapters: set[int] = set()
    for line in note_text.splitlines():
        if HEADING_PATTERN.match(line):
            current_chapter += 1
        if _is_existing_frame_line(line):
            continue
        rendered.append(line)
        if current_chapter >= 0 and current_chapter not in inserted_chapters and TIME_RANGE_PATTERN.search(line):
            rendered.extend(_candidate_markdown_lines(by_chapter.get(current_chapter, []), frame_map))
            inserted_chapters.add(current_chapter)
    return "\n".join(rendered).rstrip() + "\n"


def _render_note_with_review_draft(
    note_text: str,
    draft: ReviewDraft,
    selected: list[FrameCandidate],
    frame_map: dict[str, str],
) -> str:
    by_chapter: dict[int, list[FrameCandidate]] = defaultdict(list)
    for candidate in selected:
        by_chapter[candidate.chapter_index].append(candidate)
    paragraphs_by_chapter = {paragraph.chapter_index: paragraph for paragraph in draft.paragraphs}

    rendered: list[str] = []
    current_chapter = -1
    inserted_chapters: set[int] = set()
    skipping_old_body = False
    for line in note_text.splitlines():
        if HEADING_PATTERN.match(line):
            current_chapter += 1
            skipping_old_body = False
            rendered.append(line)
            continue
        if current_chapter >= 0 and current_chapter in paragraphs_by_chapter:
            paragraph = paragraphs_by_chapter[current_chapter]
            if _is_existing_frame_line(line):
                continue
            if current_chapter not in inserted_chapters and TIME_RANGE_PATTERN.search(line):
                rendered.append(line)
                rendered.extend(_candidate_markdown_lines(by_chapter.get(current_chapter, []), frame_map))
                body = paragraph.body.strip()
                if body:
                    rendered.extend(["", body, ""])
                inserted_chapters.add(current_chapter)
                skipping_old_body = True
                continue
            if skipping_old_body:
                continue
        if _is_existing_frame_line(line):
            continue
        rendered.append(line)
    return "\n".join(rendered).rstrip() + "\n"


def _is_existing_frame_line(line: str) -> bool:
    if IMAGE_LINE_PATTERN.match(line):
        return True
    stripped = line.strip()
    return stripped.startswith(">") and ("关键帧" in stripped or "Key frame" in stripped)


def _candidate_markdown_lines(candidates: list[FrameCandidate], frame_map: dict[str, str]) -> list[str]:
    lines: list[str] = []
    for candidate in candidates:
        frame_path = frame_map[candidate.id]
        reason = candidate.reason.replace("]", ")").strip() or "Selected frame"
        lines.extend(
            [
                "",
                f"![{reason}]({frame_path})",
                "",
                f"> 关键帧：`{seconds_to_hhmmss(candidate.time)}`：{reason}",
                "",
            ]
        )
    return lines


def _sync_active_note_version(job_dir: Path, final_note: str) -> None:
    index = load_note_version_index(job_dir)
    if not index.active_version_id:
        return
    version = get_note_version(index, index.active_version_id)
    if not version:
        return
    try:
        note_path = resolve_job_relative_path(job_dir, version.note_path)
        frame_dir = resolve_job_relative_path(job_dir, version.frame_dir)
    except ValueError:
        return
    note_path.parent.mkdir(parents=True, exist_ok=True)
    note_path.write_text(final_note, encoding="utf-8-sig")
    root_frames = job_dir / "frames"
    if root_frames.exists():
        if frame_dir.exists():
            shutil.rmtree(frame_dir)
        shutil.copytree(root_frames, frame_dir)
