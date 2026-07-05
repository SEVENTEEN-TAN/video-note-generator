from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, Field

from .llm import (
    LLMError,
    build_chunk_prompt,
    call_note_model,
    chunk_segments,
    generate_note_draft,
    reduce_note_drafts,
    _build_prior_context,
)
from .models import JobConfig, NoteDraft, TranscriptSegment


CHUNKS_DIR_NAME = "note_chunks"
CHUNK_INDEX_NAME = "index.json"


class NoteChunkMeta(BaseModel):
    id: str
    index: int
    total: int
    label: str
    start_time: float
    end_time: float
    segment_start: int
    segment_end: int
    status: str = "succeeded"
    title: str = ""


class NoteChunkIndex(BaseModel):
    chunks: list[NoteChunkMeta] = Field(default_factory=list)
    total_segments: int = 0


def chunks_dir(job_dir: Path) -> Path:
    return job_dir / CHUNKS_DIR_NAME


def chunk_index_path(job_dir: Path) -> Path:
    return chunks_dir(job_dir) / CHUNK_INDEX_NAME


def save_note_chunks(
    job_dir: Path,
    segments: list[TranscriptSegment],
    chunk_segment_lists: list[list[TranscriptSegment]],
    chunk_drafts: list[NoteDraft],
) -> NoteChunkIndex:
    """Persist chunk metadata and individual drafts after generation."""
    out_dir = chunks_dir(job_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    # Track segment index boundaries
    seg_offset = 0
    metas: list[NoteChunkMeta] = []
    for index, (chunk_segs, draft) in enumerate(zip(chunk_segment_lists, chunk_drafts), start=1):
        chunk_id = f"chunk_{index:03d}"
        meta = NoteChunkMeta(
            id=chunk_id,
            index=index,
            total=len(chunk_segment_lists),
            label=f"Chunk {index}/{len(chunk_segment_lists)}",
            start_time=chunk_segs[0].start if chunk_segs else 0,
            end_time=chunk_segs[-1].end if chunk_segs else 0,
            segment_start=seg_offset,
            segment_end=seg_offset + len(chunk_segs) - 1,
            status="skipped" if "was skipped" in (draft.summary or "") else "succeeded",
            title=(draft.title or "").strip(),
        )
        metas.append(meta)
        draft_path = out_dir / f"{chunk_id}.json"
        draft_path.write_text(
            json.dumps(draft.model_dump(mode="json"), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        seg_offset += len(chunk_segs)

    index = NoteChunkIndex(chunks=metas, total_segments=len(segments))
    chunk_index_path(job_dir).write_text(
        json.dumps(index.model_dump(mode="json"), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return index


def load_note_chunk_index(job_dir: Path) -> NoteChunkIndex | None:
    path = chunk_index_path(job_dir)
    if not path.exists():
        return None
    try:
        return NoteChunkIndex.model_validate(json.loads(path.read_text(encoding="utf-8")))
    except Exception:
        return None


def load_chunk_draft(job_dir: Path, chunk_id: str) -> NoteDraft | None:
    path = chunks_dir(job_dir) / f"{chunk_id}.json"
    if not path.exists():
        return None
    return NoteDraft.model_validate(json.loads(path.read_text(encoding="utf-8")))


def load_all_chunk_drafts(job_dir: Path, index: NoteChunkIndex) -> list[NoteDraft]:
    drafts: list[NoteDraft] = []
    for meta in index.chunks:
        draft = load_chunk_draft(job_dir, meta.id)
        if draft:
            drafts.append(draft)
    return drafts


def regenerate_chunk_and_reduce(
    job_dir: Path,
    config: JobConfig,
    duration: float | None,
    segments: list[TranscriptSegment],
    chunk_id: str,
    system_prompt: str,
) -> NoteDraft:
    """Regenerate one chunk, save it, then re-reduce all chunks."""
    index = load_note_chunk_index(job_dir)
    if not index:
        raise ValueError("Note chunk index not found.")

    meta = next((m for m in index.chunks if m.id == chunk_id), None)
    if not meta:
        raise ValueError(f"Chunk '{chunk_id}' not found.")

    # Re-split segments to get the same boundary, then pick the target chunk
    chunk_lists = chunk_segments(segments)
    target_chunk = chunk_lists[meta.index - 1]

    # Build prior context from earlier chunks
    prior_drafts: list[NoteDraft] = []
    for earlier in index.chunks:
        if earlier.index >= meta.index:
            break
        draft = load_chunk_draft(job_dir, earlier.id)
        if draft:
            prior_drafts.append(draft)
    prior_context = _build_prior_context(prior_drafts)

    # Generate new draft for this chunk
    chunk_prompt = build_chunk_prompt(
        config.original_filename,
        duration,
        config.note_language.value,
        config.frame_limit,
        meta.index,
        meta.total,
        target_chunk,
        note_style=config.note_style.value,
        extras=config.extras,
        prior_context=prior_context,
    )
    try:
        new_draft = call_note_model(
            config,
            [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": chunk_prompt},
            ],
            max_tokens=2200,
        )
        new_status = "succeeded"
    except LLMError:
        new_draft = NoteDraft(
            title=f"Transcript chunk {meta.index} of {meta.total}",
            summary=f"Chunk {meta.index}/{meta.total} was skipped because the note model rejected it.",
            chapters=[],
            key_moments=[],
            recommended_frame_count=1,
            key_takeaways=[],
            action_items=[],
        )
        new_status = "skipped"

    # Save the new draft
    draft_path = chunks_dir(job_dir) / f"{chunk_id}.json"
    draft_path.write_text(
        json.dumps(new_draft.model_dump(mode="json"), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    # Update index
    meta.status = new_status
    meta.title = (new_draft.title or "").strip()
    chunk_index_path(job_dir).write_text(
        json.dumps(index.model_dump(mode="json"), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    # Reload all drafts and re-reduce
    all_drafts = load_all_chunk_drafts(job_dir, index)
    return reduce_note_drafts(config, duration, all_drafts, system_prompt)

