from __future__ import annotations

from backend.app import job_store
from backend.app.job_store import JobStore
from backend.app.models import FailureContext, JobStage, JobStatus


def test_job_store_tracks_step_timing(tmp_path, monkeypatch) -> None:
    timestamps = iter(
        [
            "2026-06-20T00:00:00+00:00",
            "2026-06-20T00:00:01+00:00",
            "2026-06-20T00:00:02+00:00",
            "2026-06-20T00:00:03+00:00",
        ]
    )
    monkeypatch.setattr(job_store, "_now_iso", lambda: next(timestamps))

    store = JobStore(tmp_path)
    job_id = "timed-job"
    store.create(job_id)

    store.update(job_id, step="字幕生成中", progress=35)
    first = store.get(job_id)

    assert first is not None
    assert first.step == "字幕生成中"
    assert first.step_started_at == "2026-06-20T00:00:01+00:00"
    assert first.updated_at == "2026-06-20T00:00:01+00:00"
    assert first.stage_elapsed_seconds == 0

    first_started_at = first.step_started_at

    store.update(job_id, step="字幕生成中", progress=40)
    second = store.get(job_id)

    assert second is not None
    assert second.step_started_at == first_started_at
    assert second.updated_at == "2026-06-20T00:00:02+00:00"
    assert second.stage_elapsed_seconds == 1

    store.update(job_id, step="笔记生成中", progress=60)
    third = store.get(job_id)

    assert third is not None
    assert third.step == "笔记生成中"
    assert third.step_started_at == "2026-06-20T00:00:03+00:00"
    assert third.updated_at == "2026-06-20T00:00:03+00:00"
    assert third.stage_elapsed_seconds == 0


def test_job_store_clears_stale_failure_context_when_job_restarts(tmp_path) -> None:
    store = JobStore(tmp_path)
    job_id = "retry-job"
    state = store.create(job_id)
    state.status = JobStatus.failed
    state.error = "previous failure"
    state.failure_context = FailureContext(context="note-chunk-3-of-16", summary="previous failure context")

    store.update(job_id, status=JobStatus.running, step="retrying note generation", error="", progress=60)

    restarted = store.get(job_id)
    assert restarted is not None
    assert restarted.status == JobStatus.running
    assert restarted.error == ""
    assert restarted.failure_context is None


def test_job_store_persists_cancelled_state_across_reload(tmp_path) -> None:
    job_id = "cancelled-job"
    job_dir = tmp_path / job_id
    job_dir.mkdir()
    (job_dir / "metadata.json").write_text('{"job_id":"cancelled-job","title":"demo","original_filename":"demo.mp4"}', encoding="utf-8")

    store = JobStore(tmp_path)
    store.create(job_id)
    store.update(job_id, status=JobStatus.running, stage=JobStage.transcribing, step="字幕生成", progress=35)
    cancelled = store.request_cancel(job_id)

    assert cancelled is not None
    assert cancelled.status == JobStatus.cancelling
    assert cancelled.stage == JobStage.cancelling
    assert (job_dir / ".cancelled").exists()

    finished = store.mark_cancelled(job_id)
    assert finished is not None
    assert finished.status == JobStatus.cancelled

    reloaded = JobStore(tmp_path).load_from_disk(job_id)
    assert reloaded is not None
    assert reloaded.status == JobStatus.cancelled
    assert reloaded.stage == JobStage.cancelled
    assert reloaded.step == "已取消"
    assert reloaded.progress == 35
    assert reloaded.error is None


def test_job_store_exposes_stable_stage_for_processing_steps(tmp_path) -> None:
    store = JobStore(tmp_path)
    store.create("stage-job")
    store.update("stage-job", status=JobStatus.running, step="关键帧抽取", progress=78)

    state = store.get("stage-job")
    assert state is not None
    assert state.stage.value == "generating_frames"


def test_cancelled_job_ignores_late_worker_updates(tmp_path) -> None:
    store = JobStore(tmp_path)
    job_id = "late-update-job"
    (tmp_path / job_id).mkdir()
    store.create(job_id)
    store.update(job_id, status=JobStatus.running, step="字幕生成", progress=35)
    store.request_cancel(job_id)

    store.update(job_id, status=JobStatus.failed, step="失败", progress=100, error="late failure")

    state = store.get(job_id)
    assert state is not None
    assert state.status == JobStatus.cancelling
    assert state.stage == JobStage.cancelling
    assert state.error is None

    store.mark_cancelled(job_id)
    store.update(job_id, status=JobStatus.failed, step="失败", progress=100, error="later failure")
    finished = store.get(job_id)
    assert finished is not None
    assert finished.status == JobStatus.cancelled
    assert finished.stage == JobStage.cancelled
    assert finished.error is None


def test_job_store_explicit_stage_does_not_depend_on_display_copy(tmp_path) -> None:
    store = JobStore(tmp_path)
    store.create("explicit-stage-job")

    store.update(
        "explicit-stage-job",
        status=JobStatus.running,
        stage=JobStage.finalizing,
        step="写入下载包",
        progress=92,
    )

    state = store.get("explicit-stage-job")
    assert state is not None
    assert state.stage == JobStage.finalizing


def test_clearing_cancel_request_allows_a_cancelled_job_to_be_requeued(tmp_path) -> None:
    store = JobStore(tmp_path)
    job_id = "retry-cancelled-job"
    (tmp_path / job_id).mkdir()
    store.create(job_id)
    store.request_cancel(job_id)
    store.mark_cancelled(job_id)

    store.clear_cancel_request(job_id)
    store.update(
        job_id,
        status=JobStatus.pending,
        stage=JobStage.queued,
        step="等待重新生成笔记",
        progress=62,
        error="",
    )

    state = store.get(job_id)
    assert state is not None
    assert state.status == JobStatus.pending
    assert state.stage == JobStage.queued
    assert not (tmp_path / job_id / ".cancelled").exists()
