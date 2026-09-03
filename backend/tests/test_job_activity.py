from __future__ import annotations

import json

from fastapi.testclient import TestClient

from backend.app import main
from backend.app.job_activity import load_job_activity
from backend.app.job_store import JobStore
from backend.app.main import app


def test_load_job_activity_summarizes_note_generation(tmp_path) -> None:
    job_dir = tmp_path / "activity-job"
    job_dir.mkdir()
    records = [
        {
            "ts": "2026-09-03T01:00:00+00:00",
            "level": "INFO",
            "stage": "note_model_call",
            "message": "requesting",
            "details": {"context": "note-chunk-7-of-17", "attempt": 1, "max_tokens": 8192},
        },
        {
            "ts": "2026-09-03T01:00:20+00:00",
            "level": "INFO",
            "stage": "note_model_call",
            "message": "response_received",
            "details": {"context": "note-chunk-7-of-17", "response_length": 0, "finish_reason": "length"},
        },
        {
            "ts": "2026-09-03T01:00:20+00:00",
            "level": "INFO",
            "stage": "note_model_call",
            "message": "truncation_retry",
            "details": {
                "context": "note-chunk-7-of-17",
                "previous_max_tokens": 8192,
                "next_max_tokens": 16384,
            },
        },
        {
            "ts": "2026-09-03T01:01:00+00:00",
            "level": "INFO",
            "stage": "generate_chunked_note_draft",
            "message": "binary_split_retry",
            "details": {"context": "note-chunk-7-of-17-left", "segment_count": 90},
        },
    ]
    (job_dir / "debug.log").write_text(
        "not-json\n" + "\n".join(json.dumps(record) for record in records),
        encoding="utf-8",
    )

    activity = load_job_activity(job_dir, limit=3)

    assert activity.current_context == "note-chunk-7-of-17-left"
    assert activity.request_count == 1
    assert activity.response_count == 1
    assert activity.truncation_retry_count == 1
    assert activity.binary_split_count == 1
    assert len(activity.events) == 3
    assert "8192 → 16384" in activity.events[1].summary
    assert "笔记块 7/17" in activity.events[2].summary


def test_job_activity_api_reads_active_job_log(tmp_path, monkeypatch) -> None:
    job_id = "activity-api-job"
    job_dir = tmp_path / job_id
    job_dir.mkdir()
    (job_dir / "debug.log").write_text(
        json.dumps(
            {
                "ts": "2026-09-03T01:00:00+00:00",
                "level": "INFO",
                "stage": "note_model_call",
                "message": "requesting",
                "details": {"context": "note-chunk-2-of-5", "attempt": 1, "max_tokens": 8192},
            }
        ),
        encoding="utf-8",
    )
    store = JobStore(tmp_path)
    store.create(job_id)
    monkeypatch.setattr(main, "OUTPUTS_ROOT", tmp_path)
    monkeypatch.setattr(main, "store", store)

    response = TestClient(app).get(f"/api/jobs/{job_id}/activity?limit=4")

    assert response.status_code == 200
    payload = response.json()
    assert payload["job_id"] == job_id
    assert payload["current_context"] == "note-chunk-2-of-5"
    assert payload["events"][0]["summary"].startswith("正在请求 AI")
