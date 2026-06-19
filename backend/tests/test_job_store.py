from __future__ import annotations

from backend.app.job_store import JobStore


def test_job_store_tracks_step_timing(tmp_path) -> None:
    store = JobStore(tmp_path)
    job_id = "timed-job"
    store.create(job_id)

    store.update(job_id, step="字幕生成中", progress=35)
    first = store.get(job_id)

    assert first is not None
    assert first.step == "字幕生成中"
    assert first.step_started_at is not None
    assert first.updated_at is not None
    assert first.stage_elapsed_seconds >= 0

    first_started_at = first.step_started_at

    store.update(job_id, step="字幕生成中", progress=40)
    second = store.get(job_id)

    assert second is not None
    assert second.step_started_at == first_started_at
    assert second.updated_at is not None
    assert second.stage_elapsed_seconds >= 0

    store.update(job_id, step="笔记生成中", progress=60)
    third = store.get(job_id)

    assert third is not None
    assert third.step == "笔记生成中"
    assert third.step_started_at is not None
    assert third.step_started_at != first_started_at
