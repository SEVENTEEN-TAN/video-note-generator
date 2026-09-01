from __future__ import annotations

import json

import pytest

from backend.app.job_state import load_job_state, write_job_state
from backend.app.job_store import JobStore
from backend.app.models import FailureContext, JobPublicState, JobStage, JobStatus


def _write_metadata(job_dir, *, created_at: str = "2026-08-01T00:00:00+00:00") -> None:
    job_dir.mkdir(parents=True, exist_ok=True)
    (job_dir / "metadata.json").write_text(
        json.dumps(
            {
                "job_id": job_dir.name,
                "created_at": created_at,
                "title": "Snapshot task",
                "original_filename": "snapshot.mp4",
            }
        ),
        encoding="utf-8",
    )


def _write_snapshot(
    job_dir,
    *,
    status: JobStatus,
    stage: JobStage,
    step: str,
    progress: int,
    state_revision: int = 5,
    updated_at: str = "2026-08-02T00:00:00+00:00",
    error: str | None = None,
    failure_context: FailureContext | None = None,
) -> None:
    write_job_state(
        job_dir,
        JobPublicState(
            job_id=job_dir.name,
            status=status,
            stage=stage,
            step=step,
            progress=progress,
            state_revision=state_revision,
            updated_at=updated_at,
            step_started_at=updated_at,
            error=error,
            failure_context=failure_context,
        ),
    )


def test_job_state_snapshot_excludes_dynamic_artifacts_and_credentials(tmp_path) -> None:
    job_id = "snapshot-fields"
    store = JobStore(tmp_path)
    created = store.create(job_id)
    created.artifacts = []
    created.artifact_revision = "derived"
    created.download_filename = "private.zip"
    store.update(
        job_id,
        status=JobStatus.running,
        stage=JobStage.transcribing,
        step="字幕生成",
        progress=35,
    )

    payload = json.loads((tmp_path / job_id / ".job-state.json").read_text(encoding="utf-8"))
    serialized = json.dumps(payload, ensure_ascii=False).casefold()

    assert payload["status"] == "running"
    assert payload["stage"] == "transcribing"
    assert "artifacts" not in payload
    assert "artifact_revision" not in payload
    assert "download_filename" not in payload
    assert "api_key" not in serialized
    assert "authorization" not in serialized


def test_job_state_revision_is_monotonic_and_survives_reload(tmp_path) -> None:
    job_id = "snapshot-revision"
    store = JobStore(tmp_path)

    assert store.create(job_id).state_revision == 1
    store.update(job_id, status=JobStatus.running, step="分析视频", progress=5)
    assert store.get(job_id).state_revision == 2
    store.update(job_id, stage=JobStage.transcribing, step="字幕生成", progress=35)
    assert store.get(job_id).state_revision == 3

    reloaded = JobStore(tmp_path).load_from_disk(job_id)

    assert reloaded is not None
    assert reloaded.state_revision == 3
    assert load_job_state(tmp_path / job_id).state_revision == 3


def test_snapshot_stage_and_step_take_priority_over_debug_inference(tmp_path) -> None:
    job_id = "snapshot-priority"
    job_dir = tmp_path / job_id
    _write_metadata(job_dir)
    (job_dir / ".note-review.pending").write_text("1", encoding="utf-8")
    (job_dir / "debug.log").write_text(
        json.dumps(
            {
                "ts": "2026-08-03T00:00:00+00:00",
                "stage": "regenerate_note_job",
                "message": "failed",
                "details": {"exception_message": "old failure"},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    _write_snapshot(
        job_dir,
        status=JobStatus.awaiting_note_review,
        stage=JobStage.awaiting_note_review,
        step="等待人工检查证据",
        progress=91,
        state_revision=7,
    )

    reloaded = JobStore(tmp_path).load_from_disk(job_id)

    assert reloaded is not None
    assert reloaded.status == JobStatus.awaiting_note_review
    assert reloaded.stage == JobStage.awaiting_note_review
    assert reloaded.step == "等待人工检查证据"
    assert reloaded.progress == 91
    assert reloaded.state_revision == 7


@pytest.mark.parametrize(
    ("marker_name", "marker_content", "expected_status", "expected_stage", "expected_step"),
    [
        (
            "subtitles.pending",
            "1",
            JobStatus.awaiting_subtitle_confirmation,
            JobStage.awaiting_subtitle_review,
            "等待确认字幕",
        ),
        (
            ".note-review.pending",
            "1",
            JobStatus.awaiting_note_review,
            JobStage.awaiting_note_review,
            "等待复核笔记",
        ),
        (
            ".cancelled",
            '{"progress": 37}',
            JobStatus.cancelled,
            JobStage.cancelled,
            "已取消",
        ),
    ],
)
def test_recovery_markers_override_active_snapshot(
    tmp_path,
    marker_name,
    marker_content,
    expected_status,
    expected_stage,
    expected_step,
) -> None:
    job_id = f"marker-{marker_name.replace('.', '-')}"
    job_dir = tmp_path / job_id
    _write_metadata(job_dir)
    _write_snapshot(
        job_dir,
        status=JobStatus.running,
        stage=JobStage.generating_note,
        step="生成笔记",
        progress=65,
    )
    (job_dir / marker_name).write_text(marker_content, encoding="utf-8")

    reloaded = JobStore(tmp_path).load_from_disk(job_id)

    assert reloaded is not None
    assert reloaded.status == expected_status
    assert reloaded.stage == expected_stage
    assert reloaded.step == expected_step
    assert reloaded.state_revision == 6
    if expected_status == JobStatus.cancelled:
        assert reloaded.progress == 37


def test_corrupt_snapshot_falls_back_to_legacy_and_is_rewritten(tmp_path) -> None:
    job_id = "corrupt-snapshot"
    job_dir = tmp_path / job_id
    _write_metadata(job_dir)
    (job_dir / "note.md").write_text("# Recovered note", encoding="utf-8")
    (job_dir / ".job-state.json").write_text("{broken", encoding="utf-8")

    reloaded = JobStore(tmp_path).load_from_disk(job_id)

    assert reloaded is not None
    assert reloaded.status == JobStatus.succeeded
    assert reloaded.state_revision == 1
    persisted = load_job_state(job_dir)
    assert persisted is not None
    assert persisted.job_id == job_id
    assert persisted.status == JobStatus.succeeded


def test_legacy_job_is_migrated_to_first_snapshot(tmp_path) -> None:
    job_id = "legacy-snapshot"
    job_dir = tmp_path / job_id
    _write_metadata(job_dir)
    (job_dir / "subtitles.md").write_text("subtitle", encoding="utf-8")
    (job_dir / "subtitles.pending").write_text("1", encoding="utf-8")

    reloaded = JobStore(tmp_path).load_from_disk(job_id)

    assert reloaded is not None
    assert reloaded.status == JobStatus.awaiting_subtitle_confirmation
    assert reloaded.state_revision == 1
    assert load_job_state(job_dir) is not None


def test_snapshot_with_mismatched_job_id_is_ignored(tmp_path) -> None:
    job_id = "snapshot-id"
    job_dir = tmp_path / job_id
    _write_metadata(job_dir)
    (job_dir / "note.md").write_text("# Legacy note", encoding="utf-8")
    payload = {
        "job_id": "different-job",
        "status": "failed",
        "stage": "failed",
        "step": "wrong snapshot",
        "progress": 100,
        "state_revision": 99,
    }
    (job_dir / ".job-state.json").write_text(json.dumps(payload), encoding="utf-8")

    reloaded = JobStore(tmp_path).load_from_disk(job_id)

    assert reloaded is not None
    assert reloaded.status == JobStatus.succeeded
    assert reloaded.state_revision == 1
    assert load_job_state(job_dir).job_id == job_id


def test_completed_finalization_promotes_review_snapshot_to_succeeded(tmp_path) -> None:
    job_id = "completed-finalization"
    job_dir = tmp_path / job_id
    _write_metadata(job_dir)
    _write_snapshot(
        job_dir,
        status=JobStatus.awaiting_note_review,
        stage=JobStage.awaiting_note_review,
        step="等待复核",
        progress=92,
    )
    review_dir = job_dir / "review"
    review_dir.mkdir()
    (review_dir / "finalization.json").write_text('{"status":"completed"}', encoding="utf-8")
    (job_dir / "download.zip").write_bytes(b"zip")

    reloaded = JobStore(tmp_path).load_from_disk(job_id)

    assert reloaded is not None
    assert reloaded.status == JobStatus.succeeded
    assert reloaded.stage == JobStage.completed
    assert reloaded.progress == 100
    assert reloaded.state_revision == 6


def test_missing_review_marker_is_repaired_only_when_loading_job(tmp_path) -> None:
    job_id = "repair-review-marker"
    job_dir = tmp_path / job_id
    _write_metadata(job_dir)
    _write_snapshot(
        job_dir,
        status=JobStatus.awaiting_note_review,
        stage=JobStage.awaiting_note_review,
        step="等待复核",
        progress=92,
    )

    history = JobStore(tmp_path).list_history()

    assert history[0].status == JobStatus.awaiting_note_review
    assert not (job_dir / ".note-review.pending").exists()

    reloaded = JobStore(tmp_path).load_from_disk(job_id)

    assert reloaded is not None
    assert reloaded.status == JobStatus.awaiting_note_review
    assert (job_dir / ".note-review.pending").exists()


def test_history_prefers_snapshot_status_error_context_and_timestamp(tmp_path) -> None:
    job_id = "snapshot-history"
    job_dir = tmp_path / job_id
    _write_metadata(job_dir, created_at="2026-08-01T00:00:00+00:00")
    (job_dir / "note.md").write_text("# Misleading completed artifact", encoding="utf-8")
    context = FailureContext(
        stage="note_model_call",
        context="note-reduce",
        summary="snapshot failure context",
    )
    _write_snapshot(
        job_dir,
        status=JobStatus.failed,
        stage=JobStage.failed,
        step="等待重试",
        progress=100,
        updated_at="2026-08-04T12:00:00+00:00",
        error="snapshot failure",
        failure_context=context,
    )

    summary = JobStore(tmp_path).list_history()[0]

    assert summary.status == JobStatus.failed
    assert summary.error == "snapshot failure"
    assert summary.failure_context == context
    assert summary.updated_at == "2026-08-04T12:00:00+00:00"


def test_refresh_artifacts_persists_new_failure_context(tmp_path) -> None:
    job_id = "failure-context-snapshot"
    job_dir = tmp_path / job_id
    _write_metadata(job_dir)
    store = JobStore(tmp_path)
    store.create(job_id)
    store.update(
        job_id,
        status=JobStatus.failed,
        stage=JobStage.failed,
        step="处理失败",
        progress=100,
        error="provider failure",
    )
    before_revision = store.get(job_id).state_revision
    (job_dir / "debug.log").write_text(
        json.dumps(
            {
                "ts": "2026-08-04T00:00:00+00:00",
                "level": "ERROR",
                "stage": "regenerate_note_job",
                "message": "failed",
                "details": {"exception_message": "provider failure"},
            }
        )
        + "\n",
        encoding="utf-8",
    )

    store.refresh_artifacts(job_id)

    state = store.get(job_id)
    persisted = load_job_state(job_dir)
    assert state is not None
    assert state.failure_context is not None
    assert state.state_revision == before_revision + 1
    assert persisted is not None
    assert persisted.failure_context == state.failure_context
    assert persisted.state_revision == state.state_revision
