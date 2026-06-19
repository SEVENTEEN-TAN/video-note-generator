from __future__ import annotations

from backend.app import job_store
from backend.app.job_store import JobStore


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
