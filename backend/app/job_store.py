from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from threading import Lock

from .models import Artifact, JobPublicState, JobStatus


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
