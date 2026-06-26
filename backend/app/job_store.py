from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock

from .models import Artifact, JobPublicState, JobStatus, JobSummary
from .note_versions import load_note_version_index


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class JobStore:
    def __init__(self, outputs_root: Path) -> None:
        self.outputs_root = outputs_root
        self._lock = Lock()
        self._jobs: dict[str, JobPublicState] = {}

    def create(self, job_id: str) -> JobPublicState:
        now = _now_iso()
        state = JobPublicState(
            job_id=job_id,
            status=JobStatus.pending,
            step="等待处理",
            progress=0,
            artifacts=[],
            step_started_at=now,
            updated_at=now,
            stage_elapsed_seconds=0,
        )
        with self._lock:
            self._jobs[job_id] = state
        return state

    def get(self, job_id: str) -> JobPublicState | None:
        with self._lock:
            return self._jobs.get(job_id)

    def update(
        self,
        job_id: str,
        *,
        status: JobStatus | None = None,
        step: str | None = None,
        progress: int | None = None,
        error: str | None = None,
    ) -> None:
        with self._lock:
            state = self._jobs[job_id]
            now = _now_iso()
            old_step = state.step
            new_step = step if step is not None else old_step
            if new_step != old_step:
                state.step_started_at = now
            state.updated_at = now
            if state.step_started_at:
                started = datetime.fromisoformat(state.step_started_at)
                current = datetime.fromisoformat(now)
                state.stage_elapsed_seconds = max(0, (current - started).total_seconds())
            if status is not None:
                state.status = status
            if step is not None:
                state.step = step
            if progress is not None:
                state.progress = max(0, min(100, progress))
            if error is not None:
                state.error = error

    def refresh_artifacts(self, job_id: str) -> list[Artifact]:
        job_dir = self.outputs_root / job_id
        artifacts: list[Artifact] = []
        candidates = [
            ("audio.mp3", "原视频音频 MP3", "audio"),
            ("subtitles.srt", "字幕 SRT", "subtitle"),
            ("subtitles.vtt", "字幕 VTT", "subtitle"),
            ("subtitles.md", "字幕 Markdown", "markdown"),
            ("transcript.json", "转写 JSON", "json"),
            ("note.md", "视频笔记 Markdown", "markdown"),
            ("metadata.json", "任务元数据", "json"),
            ("download.zip", "完整结果 ZIP", "zip"),
        ]
        for path, label, kind in candidates:
            if (job_dir / path).exists():
                artifacts.append(
                    Artifact(label=label, path=path, kind=kind, asset_url=f"/api/jobs/{job_id}/assets/{path}")
                )
        frames_dir = job_dir / "frames"
        if frames_dir.exists():
            for frame_path in sorted(frames_dir.glob("*.jpg")):
                rel = frame_path.relative_to(job_dir).as_posix()
                artifacts.append(
                    Artifact(label=frame_path.stem, path=rel, kind="image", asset_url=f"/api/jobs/{job_id}/assets/{rel}")
                )
        with self._lock:
            state = self._jobs.get(job_id)
            if state:
                state.artifacts = artifacts
        return artifacts

    def load_from_disk(self, job_id: str) -> JobPublicState | None:
        job_dir = self.outputs_root / job_id
        if not job_dir.exists() or not job_dir.is_dir():
            return None

        metadata = self._read_metadata(job_dir)
        artifacts = self.refresh_artifacts(job_id)
        version_index = load_note_version_index(job_dir)
        timestamp = str(metadata.get("created_at") or _mtime_iso(job_dir))
        status = _infer_disk_job_status(job_dir, artifacts, version_index)
        state = JobPublicState(
            job_id=job_id,
            status=status,
            step="已从历史记录载入" if status == JobStatus.succeeded else "历史任务不完整",
            progress=100,
            error=None if status == JobStatus.succeeded else "历史任务缺少完整笔记输出，可能在上次生成中断。",
            artifacts=artifacts,
            step_started_at=timestamp,
            updated_at=timestamp,
            stage_elapsed_seconds=0,
        )
        with self._lock:
            self._jobs[job_id] = state
        return state

    def list_history(self) -> list[JobSummary]:
        if not self.outputs_root.exists():
            return []

        summaries = [self._summarize_job_dir(path) for path in self._iter_job_dirs()]
        return sorted(summaries, key=lambda item: item.created_at or "", reverse=True)

    def remove(self, job_id: str) -> None:
        with self._lock:
            self._jobs.pop(job_id, None)

    def _iter_job_dirs(self) -> list[Path]:
        return [
            path
            for path in self.outputs_root.iterdir()
            if path.is_dir() and not path.name.startswith(".")
        ]

    def _summarize_job_dir(self, job_dir: Path) -> JobSummary:
        metadata = self._read_metadata(job_dir)
        version_index = load_note_version_index(job_dir)
        artifacts = self.refresh_artifacts(job_dir.name)
        with self._lock:
            memory_state = self._jobs.get(job_dir.name)
        created_at = str(metadata.get("created_at") or _mtime_iso(job_dir))
        original_filename = str(metadata.get("original_filename") or job_dir.name)
        title = str(metadata.get("title") or original_filename)
        status = memory_state.status if memory_state else _infer_disk_job_status(job_dir, artifacts, version_index)
        return JobSummary(
            job_id=job_dir.name,
            title=title,
            original_filename=original_filename,
            created_at=created_at,
            status=status,
            duration_seconds=metadata.get("duration_seconds"),
            artifact_count=len(artifacts),
            note_version_count=len(version_index.versions),
            active_version_id=version_index.active_version_id,
        )

    def _read_metadata(self, job_dir: Path) -> dict:
        metadata_path = job_dir / "metadata.json"
        if not metadata_path.exists():
            return {}
        try:
            return json.loads(metadata_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}


def _mtime_iso(path: Path) -> str:
    return datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat()


def _infer_disk_job_status(job_dir: Path, artifacts: list[Artifact], version_index) -> JobStatus:
    artifact_paths = {artifact.path for artifact in artifacts}
    if "note.md" in artifact_paths:
        return JobStatus.succeeded
    for version in version_index.versions:
        if (job_dir / version.note_path).exists():
            return JobStatus.succeeded
    return JobStatus.failed
