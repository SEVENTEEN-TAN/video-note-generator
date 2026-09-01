from __future__ import annotations

from backend.app import job_store
from backend.app.job_store import JobStore
from backend.app.job_state import load_job_state
from backend.app.models import FailureContext, JobStage, JobStatus, TranscriptionWorkProgress


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
    store.create(job_id)
    store.update(
        job_id,
        status=JobStatus.failed,
        error="previous failure",
        failure_context=FailureContext(
            context="note-chunk-3-of-16",
            summary="previous failure context",
        ),
    )

    store.update(job_id, status=JobStatus.running, step="retrying note generation", error="", progress=60)

    restarted = store.get(job_id)
    assert restarted is not None
    assert restarted.status == JobStatus.running
    assert restarted.error == ""
    assert restarted.failure_context is None


def test_job_store_returns_detached_public_state_snapshots(tmp_path) -> None:
    store = JobStore(tmp_path)
    job_id = "detached-state"
    created = store.create(job_id)
    created.status = JobStatus.failed
    created.step = "external mutation"

    initial = store.get(job_id)
    assert initial is not None
    assert initial.status == JobStatus.pending
    assert initial.step == "等待处理"

    work_progress = TranscriptionWorkProgress(
        completed_seconds=30,
        total_seconds=120,
        completed_chunks=1,
        total_chunks=4,
        resumable=True,
        cache_hits=1,
    )
    store.update(
        job_id,
        status=JobStatus.running,
        stage=JobStage.transcribing,
        step="字幕生成",
        progress=40,
        work_progress=work_progress,
    )
    returned = store.get(job_id)
    assert returned is not None
    assert returned.work_progress is not None
    returned.work_progress.resumable = False
    returned.work_progress.cache_hits = 99

    current = store.get(job_id)
    persisted = load_job_state(tmp_path / job_id)
    assert current is not None
    assert current.work_progress is not None
    assert current.work_progress.resumable is True
    assert current.work_progress.cache_hits == 1
    assert persisted is not None
    assert persisted.work_progress is not None
    assert persisted.work_progress.resumable is True
    assert persisted.work_progress.cache_hits == 1

    cancellation = store.request_cancel(job_id)
    assert cancellation is not None
    cancellation.status = JobStatus.succeeded
    assert store.get(job_id).status == JobStatus.cancelling


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


def test_high_frequency_progress_is_live_in_memory_and_throttled_on_disk(tmp_path) -> None:
    clock = [100.0]
    store = JobStore(
        tmp_path,
        state_persist_interval_seconds=0.75,
        monotonic_clock=lambda: clock[0],
    )
    job_id = "throttled-progress"
    store.create(job_id)
    store.update(
        job_id,
        status=JobStatus.running,
        stage=JobStage.transcribing,
        step="字幕生成",
        progress=35,
    )
    baseline = load_job_state(tmp_path / job_id)
    assert baseline is not None

    clock[0] = 100.20
    store.update(
        job_id,
        stage=JobStage.transcribing,
        step="字幕生成中：00:10 / 10:00",
        progress=36,
        throttle_persistence=True,
    )

    live = store.get(job_id)
    still_persisted = load_job_state(tmp_path / job_id)
    assert live is not None
    assert still_persisted is not None
    assert live.step == "字幕生成中：00:10 / 10:00"
    assert live.progress == 36
    assert live.state_revision == baseline.state_revision
    assert still_persisted.step == "字幕生成"
    assert still_persisted.progress == 35
    assert still_persisted.state_revision == baseline.state_revision

    clock[0] = 100.80
    store.update(
        job_id,
        stage=JobStage.transcribing,
        step="字幕生成中：00:20 / 10:00",
        progress=37,
        throttle_persistence=True,
    )

    flushed = load_job_state(tmp_path / job_id)
    assert flushed is not None
    assert flushed.step == "字幕生成中：00:20 / 10:00"
    assert flushed.progress == 37
    assert flushed.state_revision == baseline.state_revision + 1
    current = store.get(job_id)
    assert current is not None
    assert current.state_revision == flushed.state_revision


def test_transcription_chunk_boundaries_bypass_state_persist_throttle(tmp_path) -> None:
    clock = [200.0]
    store = JobStore(
        tmp_path,
        state_persist_interval_seconds=10.0,
        monotonic_clock=lambda: clock[0],
    )
    job_id = "chunk-boundary"
    store.create(job_id)
    store.update(
        job_id,
        status=JobStatus.running,
        stage=JobStage.transcribing,
        step="字幕生成",
        progress=35,
    )
    initial_work = TranscriptionWorkProgress(
        completed_seconds=0,
        total_seconds=1200,
        completed_chunks=0,
        total_chunks=2,
        current_chunk=0,
        resumable=True,
        device="cpu",
        compute_type="int8",
    )

    clock[0] = 200.10
    store.update(
        job_id,
        stage=JobStage.transcribing,
        work_progress=initial_work,
        throttle_persistence=True,
    )
    first_boundary = load_job_state(tmp_path / job_id)
    assert first_boundary is not None
    assert first_boundary.work_progress == initial_work

    clock[0] = 200.20
    in_chunk = initial_work.model_copy(
        update={
            "completed_seconds": 300,
            "realtime_factor": 0.5,
            "eta_seconds": 450,
        }
    )
    store.update(
        job_id,
        stage=JobStage.transcribing,
        work_progress=in_chunk,
        throttle_persistence=True,
    )
    still_at_boundary = load_job_state(tmp_path / job_id)
    assert still_at_boundary is not None
    assert still_at_boundary.work_progress == initial_work
    live = store.get(job_id)
    assert live is not None
    assert live.work_progress == in_chunk

    clock[0] = 200.30
    completed_chunk = in_chunk.model_copy(
        update={
            "completed_seconds": 600,
            "completed_chunks": 1,
            "current_chunk": 1,
        }
    )
    store.update(
        job_id,
        stage=JobStage.transcribing,
        work_progress=completed_chunk,
        throttle_persistence=True,
    )

    persisted_boundary = load_job_state(tmp_path / job_id)
    assert persisted_boundary is not None
    assert persisted_boundary.work_progress == completed_chunk
    assert persisted_boundary.state_revision == first_boundary.state_revision + 1


def test_terminal_status_bypasses_state_persist_throttle(tmp_path) -> None:
    clock = [300.0]
    store = JobStore(
        tmp_path,
        state_persist_interval_seconds=60.0,
        monotonic_clock=lambda: clock[0],
    )
    job_id = "terminal-flush"
    store.create(job_id)
    store.update(
        job_id,
        status=JobStatus.running,
        stage=JobStage.generating_note,
        step="生成笔记",
        progress=65,
    )
    before = load_job_state(tmp_path / job_id)
    assert before is not None

    clock[0] = 300.10
    store.update(
        job_id,
        status=JobStatus.awaiting_note_review,
        stage=JobStage.awaiting_note_review,
        step="等待复核笔记",
        progress=92,
        throttle_persistence=True,
    )

    persisted = load_job_state(tmp_path / job_id)
    assert persisted is not None
    assert persisted.status == JobStatus.awaiting_note_review
    assert persisted.stage == JobStage.awaiting_note_review
    assert persisted.progress == 92
    assert persisted.state_revision == before.state_revision + 1


def test_cancel_marker_propagates_between_job_store_instances(tmp_path) -> None:
    job_id = "cross-process-cancel"
    worker_store = JobStore(tmp_path)
    controller_store = JobStore(tmp_path)
    worker_store.create(job_id)
    worker_store.update(
        job_id,
        status=JobStatus.running,
        stage=JobStage.transcribing,
        step="字幕生成",
        progress=35,
    )
    assert controller_store.load_from_disk(job_id) is not None

    cancellation = controller_store.request_cancel(job_id)

    assert cancellation is not None
    assert cancellation.status == JobStatus.cancelling
    assert worker_store.is_cancel_requested(job_id)
    worker_store.update(
        job_id,
        status=JobStatus.failed,
        stage=JobStage.failed,
        step="迟到失败",
        progress=100,
        error="must be ignored",
    )
    still_cancelling = load_job_state(tmp_path / job_id)
    assert still_cancelling is not None
    assert still_cancelling.status == JobStatus.cancelling

    cancelled = worker_store.mark_cancelled(job_id)

    assert cancelled is not None
    assert cancelled.status == JobStatus.cancelled
    assert cancelled.state_revision == cancellation.state_revision + 1
    observed = controller_store.get(job_id)
    assert observed is not None
    assert observed.status == JobStatus.cancelled
    assert observed.state_revision == cancelled.state_revision


def test_job_store_get_merges_a_newer_cross_process_snapshot(tmp_path) -> None:
    job_id = "cross-process-refresh"
    first_store = JobStore(tmp_path)
    second_store = JobStore(tmp_path)
    first_store.create(job_id)
    assert second_store.load_from_disk(job_id) is not None

    first_store.update(
        job_id,
        status=JobStatus.awaiting_subtitle_confirmation,
        stage=JobStage.awaiting_subtitle_review,
        step="等待确认字幕",
        progress=40,
    )

    refreshed = second_store.get(job_id)
    assert refreshed is not None
    assert refreshed.status == JobStatus.awaiting_subtitle_confirmation
    assert refreshed.stage == JobStage.awaiting_subtitle_review
    assert refreshed.progress == 40
    assert refreshed.state_revision == first_store.get(job_id).state_revision
