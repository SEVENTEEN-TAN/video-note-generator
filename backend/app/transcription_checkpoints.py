"""Durable, atomic checkpoints for chunked transcription jobs."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict

from .models import TranscriptPayload, TranscriptSegment
from .transcription_plans import TranscriptionExecutionPlan, plan_fingerprint


CHECKPOINT_DIR_NAME = "transcription_checkpoints"
MANIFEST_NAME = "manifest.json"
RESULTS_DIR_NAME = "results"


class ChunkSpec(BaseModel):
    """A generated audio chunk and its absolute position in the source."""

    model_config = ConfigDict(frozen=True)

    index: int
    start: float
    end: float
    path: Path


def atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    """Write JSON through a same-directory temporary file and replace."""

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f"{path.suffix}.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    temporary.replace(path)


def _relative_path(path: Path, root: Path) -> str:
    return os.path.relpath(path.resolve(), root.resolve())


def _file_signature(path: Path) -> dict[str, Any]:
    stat = path.stat()
    return {
        "size": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
    }


def _chunk_manifest(chunk: ChunkSpec, root: Path) -> dict[str, Any]:
    return {
        "index": chunk.index,
        "start": chunk.start,
        "end": chunk.end,
        "path": _relative_path(chunk.path, root),
        **_file_signature(chunk.path),
    }


class TranscriptionCheckpointSession:
    """A checkpoint manifest plus one atomic result file per chunk."""

    def __init__(
        self,
        *,
        work_dir: Path,
        source_path: Path,
        plan: TranscriptionExecutionPlan,
        chunks: list[ChunkSpec],
    ) -> None:
        self.work_dir = work_dir.resolve()
        self.source_path = source_path.resolve()
        self.plan = plan
        self.chunks = sorted(chunks, key=lambda chunk: chunk.index)
        self._chunks_by_index = {chunk.index: chunk for chunk in self.chunks}
        if len(self._chunks_by_index) != len(self.chunks):
            raise ValueError("Chunk indices must be unique.")
        if any(chunk.index < 0 for chunk in self.chunks):
            raise ValueError("Chunk indices must be non-negative.")

        self.checkpoint_dir = self.work_dir / CHECKPOINT_DIR_NAME
        self.manifest_path = self.checkpoint_dir / MANIFEST_NAME
        self.results_dir = self.checkpoint_dir / RESULTS_DIR_NAME
        self._manifest = self._build_manifest()
        self._open()

    def _build_manifest(self) -> dict[str, Any]:
        return {
            "version": 1,
            "source": {
                "path": _relative_path(self.source_path, self.work_dir),
                **_file_signature(self.source_path),
            },
            "plan_fingerprint": plan_fingerprint(self.plan),
            "chunks": [
                _chunk_manifest(chunk, self.work_dir)
                for chunk in self.chunks
            ],
        }

    def _open(self) -> None:
        previous: dict[str, Any] | None = None
        try:
            previous = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        except (FileNotFoundError, OSError, TypeError, ValueError):
            pass

        if previous != self._manifest:
            self._clear_results()
            atomic_write_json(self.manifest_path, self._manifest)

    def _clear_results(self) -> None:
        if not self.results_dir.exists():
            return
        for result_path in self.results_dir.glob("*.json"):
            try:
                result_path.unlink()
            except FileNotFoundError:
                continue

    def _result_path(self, index: int) -> Path:
        if index not in self._chunks_by_index:
            raise ValueError(f"Unknown chunk index: {index}")
        return self.results_dir / f"chunk_{index:04d}.json"

    def completed_indices(self) -> set[int]:
        completed: set[int] = set()
        for index in self._chunks_by_index:
            if self.load_result(index) is not None:
                completed.add(index)
        return completed

    def write_result(self, index: int, payload: TranscriptPayload) -> Path:
        result_path = self._result_path(index)
        validated = TranscriptPayload.model_validate(payload)
        atomic_write_json(result_path, validated.model_dump(mode="json"))
        return result_path

    def load_result(self, index: int) -> TranscriptPayload | None:
        result_path = self._result_path(index)
        try:
            contents = result_path.read_text(encoding="utf-8")
            return TranscriptPayload.model_validate_json(contents)
        except (FileNotFoundError, OSError, UnicodeDecodeError, ValueError):
            return None

    def merge_results(self) -> TranscriptPayload:
        missing = sorted(set(self._chunks_by_index) - self.completed_indices())
        if missing:
            raise ValueError(f"Cannot merge incomplete transcription chunks: {missing}")

        segments: list[TranscriptSegment] = []
        texts: list[str] = []
        for chunk in self.chunks:
            result = self.load_result(chunk.index)
            if result is None:
                raise ValueError(f"Chunk result became unavailable: {chunk.index}")
            if result.text.strip():
                texts.append(result.text.strip())
            segments.extend(
                TranscriptSegment(
                    start=segment.start + chunk.start,
                    end=segment.end + chunk.start,
                    text=segment.text,
                )
                for segment in result.segments
            )

        return TranscriptPayload(text=" ".join(texts), segments=segments)


def open_checkpoint_session(
    work_dir: Path,
    source_path: Path,
    plan: TranscriptionExecutionPlan,
    chunks: list[ChunkSpec],
) -> TranscriptionCheckpointSession:
    return TranscriptionCheckpointSession(
        work_dir=work_dir,
        source_path=source_path,
        plan=plan,
        chunks=chunks,
    )
