from __future__ import annotations

import json
import os

from fastapi.testclient import TestClient

from backend.app import main
from backend.app.job_store import JobStore
from backend.app.main import app
from backend.app.models import NoteStyle, NoteVersion, NoteVersionIndex


def write_history_job(
    outputs_root,
    job_id: str,
    *,
    created_at: str,
    title: str,
    original_filename: str,
    version_count: int = 1,
) -> None:
    job_dir = outputs_root / job_id
    job_dir.mkdir(parents=True)
    (job_dir / "note.md").write_text(f"# {title}", encoding="utf-8-sig")
    (job_dir / "subtitles.md").write_text("00:00:00 - 00:00:01 hello", encoding="utf-8-sig")
    (job_dir / "metadata.json").write_text(
        json.dumps(
            {
                "job_id": job_id,
                "created_at": created_at,
                "original_filename": original_filename,
                "title": title,
                "duration_seconds": 12.5,
            }
        ),
        encoding="utf-8",
    )

    versions = []
    selected_ids = []
    for index in range(1, version_count + 1):
        version_id = f"note_{index:03d}"
        version_dir = job_dir / "note_versions" / version_id
        version_dir.mkdir(parents=True)
        (version_dir / "note.md").write_text(f"# {title} {version_id}", encoding="utf-8-sig")
        versions.append(
            NoteVersion(
                id=version_id,
                label=f"{version_id} · detailed",
                note_style=NoteStyle.detailed,
                note_language="zh",
                note_model="gpt-5.5",
                note_base_url="https://api.openai.com/v1",
                frame_limit=6,
                note_path=f"note_versions/{version_id}/note.md",
                frame_dir=f"note_versions/{version_id}/frames",
                selected=True,
                active=index == version_count,
            )
        )
        selected_ids.append(version_id)
    (job_dir / "note_versions").mkdir(exist_ok=True)
    (job_dir / "note_versions" / "versions.json").write_text(
        NoteVersionIndex(
            active_version_id=selected_ids[-1],
            selected_version_ids=selected_ids,
            versions=versions,
        ).model_dump_json(indent=2),
        encoding="utf-8",
    )


def write_partial_history_job(
    outputs_root,
    job_id: str,
    *,
    created_at: str,
    title: str,
    original_filename: str,
) -> None:
    job_dir = outputs_root / job_id
    job_dir.mkdir(parents=True)
    (job_dir / "audio.mp3").write_bytes(b"partial audio")
    (job_dir / "metadata.json").write_text(
        json.dumps(
            {
                "job_id": job_id,
                "created_at": created_at,
                "original_filename": original_filename,
                "title": title,
                "duration_seconds": None,
            }
        ),
        encoding="utf-8",
    )


def append_debug_events(outputs_root, job_id: str, events: list[dict]) -> None:
    debug_log = outputs_root / job_id / "debug.log"
    debug_log.write_text(
        "\n".join(json.dumps(event, ensure_ascii=False) for event in events) + "\n",
        encoding="utf-8",
    )


def test_list_jobs_returns_disk_history_with_note_version_counts(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(main, "OUTPUTS_ROOT", tmp_path)
    monkeypatch.setattr(main, "store", JobStore(tmp_path))
    write_history_job(
        tmp_path,
        "older-job",
        created_at="2026-06-20T00:00:00+00:00",
        title="Older",
        original_filename="older.mp4",
    )
    write_history_job(
        tmp_path,
        "newer-job",
        created_at="2026-06-21T00:00:00+00:00",
        title="Newer",
        original_filename="newer.mp4",
        version_count=2,
    )
    (tmp_path / ".frame-suggestions").mkdir()

    response = TestClient(app).get("/api/jobs")

    assert response.status_code == 200
    assert response.json()["jobs"] == [
        {
            "job_id": "newer-job",
            "title": "Newer",
            "original_filename": "newer.mp4",
            "created_at": "2026-06-21T00:00:00+00:00",
            "updated_at": "2026-06-21T00:00:00+00:00",
            "status": "succeeded",
            "duration_seconds": 12.5,
            "artifact_count": 3,
            "note_version_count": 2,
            "active_version_id": "note_002",
        },
        {
            "job_id": "older-job",
            "title": "Older",
            "original_filename": "older.mp4",
            "created_at": "2026-06-20T00:00:00+00:00",
            "updated_at": "2026-06-20T00:00:00+00:00",
            "status": "succeeded",
            "duration_seconds": 12.5,
            "artifact_count": 3,
            "note_version_count": 1,
            "active_version_id": "note_001",
        },
    ]


def test_refresh_artifacts_includes_quality_report_files(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(main, "OUTPUTS_ROOT", tmp_path)
    monkeypatch.setattr(main, "store", JobStore(tmp_path))
    job_dir = tmp_path / "quality-artifacts"
    job_dir.mkdir()
    review_dir = job_dir / "review"
    review_dir.mkdir()
    (review_dir / "quality_report.json").write_text("{}", encoding="utf-8")
    (review_dir / "quality_report.md").write_text("# Quality Report", encoding="utf-8")

    artifacts = main.store.refresh_artifacts("quality-artifacts")

    assert {artifact.path for artifact in artifacts} >= {
        "review/quality_report.json",
        "review/quality_report.md",
    }


def test_refresh_artifacts_includes_frame_candidate_index(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(main, "OUTPUTS_ROOT", tmp_path)
    monkeypatch.setattr(main, "store", JobStore(tmp_path))
    job_dir = tmp_path / "frame-candidate-artifacts"
    job_dir.mkdir()
    review_dir = job_dir / "review"
    review_dir.mkdir()
    (review_dir / "frame_candidates.json").write_text('{"candidates":[]}', encoding="utf-8")

    artifacts = main.store.refresh_artifacts("frame-candidate-artifacts")

    assert {artifact.path for artifact in artifacts} >= {"review/frame_candidates.json"}


def test_list_jobs_orders_recent_activity_before_newer_creation_time(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(main, "OUTPUTS_ROOT", tmp_path)
    monkeypatch.setattr(main, "store", JobStore(tmp_path))
    write_history_job(
        tmp_path,
        "older-active-job",
        created_at="2026-06-20T00:00:00+00:00",
        title="Older Active",
        original_filename="older-active.mp4",
    )
    write_history_job(
        tmp_path,
        "newer-idle-job",
        created_at="2026-06-21T00:00:00+00:00",
        title="Newer Idle",
        original_filename="newer-idle.mp4",
    )
    append_debug_events(
        tmp_path,
        "older-active-job",
        [
            {
                "ts": "2026-06-22T00:00:00+00:00",
                "level": "ERROR",
                "stage": "regenerate_note_job",
                "message": "failed",
                "details": {"exception_type": "APITimeoutError", "exception_message": "Request timed out."},
            },
        ],
    )

    response = TestClient(app).get("/api/jobs")

    assert response.status_code == 200
    jobs = response.json()["jobs"]
    assert [job["job_id"] for job in jobs] == ["older-active-job", "newer-idle-job"]
    assert jobs[0]["updated_at"] == "2026-06-22T00:00:00+00:00"
    assert jobs[1]["updated_at"] == "2026-06-21T00:00:00+00:00"


def test_list_jobs_uses_debug_log_mtime_when_activity_has_no_timestamp(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(main, "OUTPUTS_ROOT", tmp_path)
    monkeypatch.setattr(main, "store", JobStore(tmp_path))
    write_history_job(
        tmp_path,
        "older-active-job",
        created_at="2026-06-20T00:00:00+00:00",
        title="Older Active",
        original_filename="older-active.mp4",
    )
    write_history_job(
        tmp_path,
        "newer-idle-job",
        created_at="2026-06-21T00:00:00+00:00",
        title="Newer Idle",
        original_filename="newer-idle.mp4",
    )
    append_debug_events(
        tmp_path,
        "older-active-job",
        [
            {
                "level": "ERROR",
                "stage": "regenerate_note_job",
                "message": "failed",
                "details": {"exception_type": "APITimeoutError", "exception_message": "Request timed out."},
            },
        ],
    )
    debug_log = tmp_path / "older-active-job" / "debug.log"
    os.utime(debug_log, (1782259200, 1782259200))

    response = TestClient(app).get("/api/jobs")

    assert response.status_code == 200
    assert [job["job_id"] for job in response.json()["jobs"]] == ["older-active-job", "newer-idle-job"]


def test_list_jobs_marks_incomplete_disk_history_as_failed(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(main, "OUTPUTS_ROOT", tmp_path)
    monkeypatch.setattr(main, "store", JobStore(tmp_path))
    write_partial_history_job(
        tmp_path,
        "partial-job",
        created_at="2026-06-22T00:00:00+00:00",
        title="Partial",
        original_filename="partial.mp4",
    )

    response = TestClient(app).get("/api/jobs")

    assert response.status_code == 200
    assert response.json()["jobs"] == [
        {
            "job_id": "partial-job",
            "title": "Partial",
            "original_filename": "partial.mp4",
            "created_at": "2026-06-22T00:00:00+00:00",
            "updated_at": "2026-06-22T00:00:00+00:00",
            "status": "failed",
            "duration_seconds": None,
            "artifact_count": 2,
            "note_version_count": 0,
            "active_version_id": None,
        }
    ]


def test_list_jobs_repairs_mojibake_metadata_filename(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(main, "OUTPUTS_ROOT", tmp_path)
    monkeypatch.setattr(main, "store", JobStore(tmp_path))
    mojibake_filename = "第二课：经典卷积神经网络.mp4".encode("utf-8").decode("latin1")
    write_history_job(
        tmp_path,
        "mojibake-job",
        created_at="2026-06-24T00:00:00+00:00",
        title=mojibake_filename,
        original_filename=mojibake_filename,
    )

    response = TestClient(app).get("/api/jobs")

    assert response.status_code == 200
    job = response.json()["jobs"][0]
    assert job["title"] == "第二课：经典卷积神经网络.mp4"
    assert job["original_filename"] == "第二课：经典卷积神经网络.mp4"


def test_list_jobs_ignores_corrupt_note_version_index(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(main, "OUTPUTS_ROOT", tmp_path)
    monkeypatch.setattr(main, "store", JobStore(tmp_path))
    job_dir = tmp_path / "corrupt-version-job"
    job_dir.mkdir()
    (job_dir / "audio.mp3").write_bytes(b"mp3")
    (job_dir / "metadata.json").write_text(
        json.dumps(
            {
                "job_id": "corrupt-version-job",
                "created_at": "2026-06-23T00:00:00+00:00",
                "original_filename": "input.mp4",
                "title": "Corrupt",
                "duration_seconds": None,
            }
        ),
        encoding="utf-8",
    )
    version_index_path = job_dir / "note_versions" / "versions.json"
    version_index_path.parent.mkdir(parents=True)
    version_index_path.write_text("{broken", encoding="utf-8")

    response = TestClient(app, raise_server_exceptions=False).get("/api/jobs")

    assert response.status_code == 200
    assert response.json()["jobs"][0]["job_id"] == "corrupt-version-job"
    assert response.json()["jobs"][0]["note_version_count"] == 0
    assert response.json()["jobs"][0]["status"] == "failed"


def test_history_restores_latest_failed_generation_even_with_existing_note(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(main, "OUTPUTS_ROOT", tmp_path)
    monkeypatch.setattr(main, "store", JobStore(tmp_path))
    write_history_job(
        tmp_path,
        "failed-regeneration-job",
        created_at="2026-06-25T00:00:00+00:00",
        title="Previous Note",
        original_filename="previous.mp4",
    )
    append_debug_events(
        tmp_path,
        "failed-regeneration-job",
        [
            {
                "ts": "2026-06-25T01:00:00+00:00",
                "level": "INFO",
                "stage": "regenerate_note_job",
                "message": "succeeded",
                "details": {},
            },
            {
                "ts": "2026-06-25T02:00:00+00:00",
                "level": "ERROR",
                "stage": "regenerate_note_job",
                "message": "failed",
                "details": {
                    "exception_type": "BadRequestError",
                    "exception_message": "content_policy_violation",
                },
            },
        ],
    )
    client = TestClient(app)

    history_response = client.get("/api/jobs")
    state_response = client.get("/api/jobs/failed-regeneration-job")

    assert history_response.status_code == 200
    history_job = history_response.json()["jobs"][0]
    assert history_job["status"] == "failed"
    assert "content_policy_violation" in history_job["error"]
    assert state_response.status_code == 200
    payload = state_response.json()
    assert payload["status"] == "failed"
    assert payload["error"] == "笔记模型请求被内容安全策略拦截（content_policy_violation）。可尝试重新生成、减少单次内容或更换模型。"
    assert "note.md" in {artifact["path"] for artifact in payload["artifacts"]}


def test_history_includes_note_api_error_request_context(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(main, "OUTPUTS_ROOT", tmp_path)
    monkeypatch.setattr(main, "store", JobStore(tmp_path))
    write_history_job(
        tmp_path,
        "api-context-failed-job",
        created_at="2026-06-25T00:00:00+00:00",
        title="API Context",
        original_filename="api-context.mp4",
    )
    append_debug_events(
        tmp_path,
        "api-context-failed-job",
        [
            {
                "ts": "2026-06-25T02:00:00+00:00",
                "level": "INFO",
                "stage": "regenerate_note_job",
                "message": "started",
                "details": {},
            },
            {
                "ts": "2026-06-25T02:01:00+00:00",
                "level": "INFO",
                "stage": "note_model_call",
                "message": "requesting",
                "details": {
                    "context": "note-chunk-15-of-16",
                    "attempt": 1,
                    "note_base_url": "https://api.cdn-krill-ai.com/codex/v1",
                    "note_model": "gpt-5.3-codex-spark",
                    "message_chars": 13442,
                    "max_tokens": 2200,
                },
            },
            {
                "ts": "2026-06-25T02:01:01+00:00",
                "level": "INFO",
                "stage": "note_model_call",
                "message": "api_error",
                "details": {
                    "context": "note-chunk-15-of-16",
                    "attempt": 1,
                    "exception_type": "BadRequestError",
                    "exception_message": "Error code: 400 - content_policy_violation",
                    "status_code": 400,
                    "body": {
                        "error": {
                            "code": "content_policy_violation",
                            "flagged_categories": ["sexual"],
                            "type": "invalid_request_error",
                        }
                    },
                },
            },
            {
                "ts": "2026-06-25T02:01:02+00:00",
                "level": "ERROR",
                "stage": "regenerate_note_job",
                "message": "failed",
                "details": {
                    "exception_type": "LLMError",
                    "exception_message": "Error code: 400 - content_policy_violation",
                },
            },
        ],
    )

    response = TestClient(app).get("/api/jobs/api-context-failed-job")

    assert response.status_code == 200
    error = response.json()["error"]
    assert "content_policy_violation" in error
    assert "note-chunk-15-of-16" in error
    assert "第 1 次请求" in error
    assert "gpt-5.3-codex-spark" in error
    assert "https://api.cdn-krill-ai.com/codex/v1" in error
    assert "sexual" in error
    failure_context = response.json()["failure_context"]
    assert failure_context["status_code"] == 400
    assert failure_context["error_code"] == "content_policy_violation"
    assert failure_context["flagged_categories"] == ["sexual"]
    assert "HTTP 400" in failure_context["summary"]
    assert "content_policy_violation" in failure_context["summary"]
    assert "sexual" in failure_context["summary"]


def test_history_normalizes_provider_flagged_categories_mapping(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(main, "OUTPUTS_ROOT", tmp_path)
    monkeypatch.setattr(main, "store", JobStore(tmp_path))
    write_history_job(
        tmp_path,
        "mapped-categories-failed-job",
        created_at="2026-06-25T03:00:00+00:00",
        title="Mapped Categories",
        original_filename="mapped-categories.mp4",
    )
    append_debug_events(
        tmp_path,
        "mapped-categories-failed-job",
        [
            {
                "ts": "2026-06-25T03:00:00+00:00",
                "level": "INFO",
                "stage": "regenerate_note_job",
                "message": "started",
                "details": {},
            },
            {
                "ts": "2026-06-25T03:01:00+00:00",
                "level": "INFO",
                "stage": "note_model_call",
                "message": "requesting",
                "details": {
                    "context": "note-chunk-4-of-16",
                    "attempt": 1,
                    "note_base_url": "https://api.example.test/v1",
                    "note_model": "example-model",
                },
            },
            {
                "ts": "2026-06-25T03:01:01+00:00",
                "level": "INFO",
                "stage": "note_model_call",
                "message": "api_error",
                "details": {
                    "context": "note-chunk-4-of-16",
                    "attempt": 1,
                    "exception_type": "BadRequestError",
                    "exception_message": "Error code: 400 - content_policy_violation",
                    "status_code": 400,
                    "body": {
                        "error": {
                            "code": "content_policy_violation",
                            "flagged_categories": {
                                "sexual": True,
                                "violence": False,
                                "self-harm": True,
                            },
                        }
                    },
                },
            },
            {
                "ts": "2026-06-25T03:01:02+00:00",
                "level": "ERROR",
                "stage": "regenerate_note_job",
                "message": "failed",
                "details": {
                    "exception_type": "LLMError",
                    "exception_message": "Error code: 400 - content_policy_violation",
                },
            },
        ],
    )

    response = TestClient(app).get("/api/jobs/mapped-categories-failed-job")

    assert response.status_code == 200
    failure_context = response.json()["failure_context"]
    assert failure_context["flagged_categories"] == ["sexual", "self-harm"]
    assert "sexual" in failure_context["summary"]
    assert "self-harm" in failure_context["summary"]
    assert "violence" not in failure_context["summary"]


def test_history_summarizes_authentication_failures(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(main, "OUTPUTS_ROOT", tmp_path)
    monkeypatch.setattr(main, "store", JobStore(tmp_path))
    write_history_job(
        tmp_path,
        "auth-failed-job",
        created_at="2026-06-26T00:00:00+00:00",
        title="Auth Failed",
        original_filename="auth.mp4",
    )
    append_debug_events(
        tmp_path,
        "auth-failed-job",
        [
            {
                "ts": "2026-06-26T02:00:00+00:00",
                "level": "ERROR",
                "stage": "regenerate_note_job",
                "message": "failed",
                "details": {
                    "exception_type": "AuthenticationError",
                    "exception_message": "Error code: 401 - {'error': {'message': 'invalid token'}}",
                },
            },
        ],
    )

    response = TestClient(app).get("/api/jobs/auth-failed-job")

    assert response.status_code == 200
    assert response.json()["error"] == "API 认证失败（401 invalid token）。请检查 API Key 或接口地址。"


def test_history_summarizes_model_not_found_failures(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(main, "OUTPUTS_ROOT", tmp_path)
    monkeypatch.setattr(main, "store", JobStore(tmp_path))
    write_history_job(
        tmp_path,
        "model-not-found-job",
        created_at="2026-06-26T02:10:00+00:00",
        title="Model Not Found",
        original_filename="model.mp4",
    )
    append_debug_events(
        tmp_path,
        "model-not-found-job",
        [
            {
                "ts": "2026-06-26T02:20:00+00:00",
                "level": "ERROR",
                "stage": "regenerate_note_job",
                "message": "failed",
                "details": {
                    "exception_type": "NotFoundError",
                    "exception_message": "Error code: 404 - {'error': {'message': 'model not found'}}",
                },
            },
        ],
    )

    response = TestClient(app).get("/api/jobs/model-not-found-job")

    assert response.status_code == 200
    assert response.json()["error"] == "模型或接口地址不存在（404/model not found）。请检查模型名称、Base URL 和供应商接口路径。"


def test_history_summarizes_rate_limit_failures(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(main, "OUTPUTS_ROOT", tmp_path)
    monkeypatch.setattr(main, "store", JobStore(tmp_path))
    write_history_job(
        tmp_path,
        "rate-limited-job",
        created_at="2026-06-26T02:30:00+00:00",
        title="Rate Limited",
        original_filename="rate-limit.mp4",
    )
    append_debug_events(
        tmp_path,
        "rate-limited-job",
        [
            {
                "ts": "2026-06-26T02:45:00+00:00",
                "level": "ERROR",
                "stage": "regenerate_note_job",
                "message": "failed",
                "details": {
                    "exception_type": "RateLimitError",
                    "exception_message": "Error code: 429 - rate limit exceeded",
                },
            },
        ],
    )

    response = TestClient(app).get("/api/jobs/rate-limited-job")

    assert response.status_code == 200
    assert response.json()["error"] == "API 请求被限流或额度不足（429/rate limit）。请稍后重试，或检查账号额度、模型并发限制。"


def test_history_summarizes_connection_failures(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(main, "OUTPUTS_ROOT", tmp_path)
    monkeypatch.setattr(main, "store", JobStore(tmp_path))
    write_history_job(
        tmp_path,
        "connection-failed-job",
        created_at="2026-06-26T02:50:00+00:00",
        title="Connection Failed",
        original_filename="connection.mp4",
    )
    append_debug_events(
        tmp_path,
        "connection-failed-job",
        [
            {
                "ts": "2026-06-26T02:55:00+00:00",
                "level": "ERROR",
                "stage": "regenerate_note_job",
                "message": "failed",
                "details": {
                    "exception_type": "APIConnectionError",
                    "exception_message": "Connection error.",
                },
            },
        ],
    )

    response = TestClient(app).get("/api/jobs/connection-failed-job")

    assert response.status_code == 200
    assert response.json()["error"] == "无法连接到模型接口。请检查网络、代理、防火墙或接口地址后重试。"


def test_history_summarizes_note_model_timeouts(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(main, "OUTPUTS_ROOT", tmp_path)
    monkeypatch.setattr(main, "store", JobStore(tmp_path))
    write_history_job(
        tmp_path,
        "timeout-failed-job",
        created_at="2026-06-26T03:00:00+00:00",
        title="Timeout Failed",
        original_filename="timeout.mp4",
    )
    append_debug_events(
        tmp_path,
        "timeout-failed-job",
        [
            {
                "ts": "2026-06-26T03:30:00+00:00",
                "level": "ERROR",
                "stage": "regenerate_note_job",
                "message": "failed",
                "details": {
                    "exception_type": "APITimeoutError",
                    "exception_message": "Request timed out.",
                },
            },
        ],
    )

    response = TestClient(app).get("/api/jobs/timeout-failed-job")

    assert response.status_code == 200
    assert response.json()["error"] == "笔记模型请求超时。可重试生成，或减少单次内容、更换模型/接口后再试。"


def test_history_summarizes_provider_server_failures(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(main, "OUTPUTS_ROOT", tmp_path)
    monkeypatch.setattr(main, "store", JobStore(tmp_path))
    write_history_job(
        tmp_path,
        "server-failed-job",
        created_at="2026-06-26T03:40:00+00:00",
        title="Server Failed",
        original_filename="server.mp4",
    )
    append_debug_events(
        tmp_path,
        "server-failed-job",
        [
            {
                "ts": "2026-06-26T03:45:00+00:00",
                "level": "ERROR",
                "stage": "regenerate_note_job",
                "message": "failed",
                "details": {
                    "exception_type": "InternalServerError",
                    "exception_message": "Error code: 503 - {'error': {'message': 'upstream server error'}}",
                },
            },
        ],
    )

    response = TestClient(app).get("/api/jobs/server-failed-job")

    assert response.status_code == 200
    assert response.json()["error"] == "模型服务暂时不可用（5xx/server error）。请稍后重试，或临时更换模型/接口。"


def test_history_summarizes_invalid_note_json_failures(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(main, "OUTPUTS_ROOT", tmp_path)
    monkeypatch.setattr(main, "store", JobStore(tmp_path))
    write_history_job(
        tmp_path,
        "invalid-json-failed-job",
        created_at="2026-06-26T04:00:00+00:00",
        title="Invalid Json Failed",
        original_filename="invalid-json.mp4",
    )
    append_debug_events(
        tmp_path,
        "invalid-json-failed-job",
        [
            {
                "ts": "2026-06-26T04:30:00+00:00",
                "level": "ERROR",
                "stage": "regenerate_note_job",
                "message": "failed",
                "details": {
                    "exception_type": "LLMError",
                    "exception_message": "Model returned invalid note JSON: Expecting value: line 1 column 1 (char 0)",
                },
            },
        ],
    )

    response = TestClient(app).get("/api/jobs/invalid-json-failed-job")

    assert response.status_code == 200
    assert response.json()["error"] == "笔记模型返回了空内容或非 JSON，无法解析为结构化笔记。可重试生成，或更换模型、减少单次内容长度。"


def test_history_summarizes_truncated_note_json_failures(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(main, "OUTPUTS_ROOT", tmp_path)
    monkeypatch.setattr(main, "store", JobStore(tmp_path))
    write_history_job(
        tmp_path,
        "truncated-json-failed-job",
        created_at="2026-06-26T05:00:00+00:00",
        title="Truncated Json Failed",
        original_filename="truncated-json.mp4",
    )
    append_debug_events(
        tmp_path,
        "truncated-json-failed-job",
        [
            {
                "ts": "2026-06-26T05:30:00+00:00",
                "level": "INFO",
                "stage": "regenerate_note_job",
                "message": "started",
                "details": {},
            },
            {
                "ts": "2026-06-26T05:31:00+00:00",
                "level": "INFO",
                "stage": "note_model_call",
                "message": "response_received",
                "details": {
                    "context": "note-chunk-4-of-16",
                    "attempt": 1,
                    "response_file": "debug/note-chunk-4-of-16-model-response-attempt-1.txt",
                    "response_length": 2200,
                    "finish_reason": "length",
                },
            },
            {
                "ts": "2026-06-26T05:31:01+00:00",
                "level": "INFO",
                "stage": "note_model_call",
                "message": "invalid_json",
                "details": {
                    "context": "note-chunk-4-of-16",
                    "attempt": 1,
                    "error": "Model returned invalid note JSON: Expecting ',' delimiter: line 40 column 2 (char 2199)",
                },
            },
            {
                "ts": "2026-06-26T05:31:02+00:00",
                "level": "ERROR",
                "stage": "regenerate_note_job",
                "message": "failed",
                "details": {
                    "exception_type": "LLMError",
                    "exception_message": "Model returned invalid note JSON: Expecting ',' delimiter: line 40 column 2 (char 2199)",
                },
            },
        ],
    )

    client = TestClient(app)
    response = client.get("/api/jobs/truncated-json-failed-job")
    history_response = client.get("/api/jobs")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "failed"
    assert "finish_reason=length" in payload["error"]
    assert "JSON" in payload["error"]
    assert history_response.status_code == 200
    history_job = history_response.json()["jobs"][0]
    assert history_job["status"] == "failed"
    assert "finish_reason=length" in history_job["error"]


def test_history_includes_response_finish_reason_request_context(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(main, "OUTPUTS_ROOT", tmp_path)
    monkeypatch.setattr(main, "store", JobStore(tmp_path))
    write_history_job(
        tmp_path,
        "truncated-json-context-job",
        created_at="2026-06-26T05:10:00+00:00",
        title="Truncated Json Context",
        original_filename="truncated-json-context.mp4",
    )
    append_debug_events(
        tmp_path,
        "truncated-json-context-job",
        [
            {
                "ts": "2026-06-26T05:30:00+00:00",
                "level": "INFO",
                "stage": "regenerate_note_job",
                "message": "started",
                "details": {},
            },
            {
                "ts": "2026-06-26T05:30:30+00:00",
                "level": "INFO",
                "stage": "note_model_call",
                "message": "requesting",
                "details": {
                    "context": "note-chunk-4-of-16",
                    "attempt": 1,
                    "note_base_url": "https://open.bigmodel.cn/api/coding/paas/v4",
                    "note_model": "glm-5.2",
                },
            },
            {
                "ts": "2026-06-26T05:31:00+00:00",
                "level": "INFO",
                "stage": "note_model_call",
                "message": "response_received",
                "details": {
                    "context": "note-chunk-4-of-16",
                    "attempt": 1,
                    "response_file": "debug/note-chunk-4-of-16-model-response-attempt-1.txt",
                    "response_length": 2200,
                    "finish_reason": "length",
                },
            },
            {
                "ts": "2026-06-26T05:31:01+00:00",
                "level": "INFO",
                "stage": "note_model_call",
                "message": "invalid_json",
                "details": {
                    "context": "note-chunk-4-of-16",
                    "attempt": 1,
                    "error": "Model returned invalid note JSON: Expecting ',' delimiter: line 40 column 2 (char 2199)",
                },
            },
            {
                "ts": "2026-06-26T05:31:02+00:00",
                "level": "ERROR",
                "stage": "regenerate_note_job",
                "message": "failed",
                "details": {
                    "exception_type": "LLMError",
                    "exception_message": "Model returned invalid note JSON: Expecting ',' delimiter: line 40 column 2 (char 2199)",
                },
            },
        ],
    )

    response = TestClient(app).get("/api/jobs/truncated-json-context-job")

    assert response.status_code == 200
    error = response.json()["error"]
    assert "finish_reason=length" in error
    assert "note-chunk-4-of-16" in error
    assert "第 1 次请求" in error
    assert "glm-5.2" in error
    assert "https://open.bigmodel.cn/api/coding/paas/v4" in error
    assert "debug/note-chunk-4-of-16-model-response-attempt-1.txt" in error


def test_history_failure_context_includes_model_response_details_for_invalid_json(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(main, "OUTPUTS_ROOT", tmp_path)
    monkeypatch.setattr(main, "store", JobStore(tmp_path))
    write_history_job(
        tmp_path,
        "invalid-json-response-details-job",
        created_at="2026-06-26T05:20:00+00:00",
        title="Invalid Json Response Details",
        original_filename="invalid-json-response-details.mp4",
    )
    append_debug_events(
        tmp_path,
        "invalid-json-response-details-job",
        [
            {
                "ts": "2026-06-26T05:20:00+00:00",
                "level": "INFO",
                "stage": "regenerate_note_job",
                "message": "started",
                "details": {},
            },
            {
                "ts": "2026-06-26T05:20:30+00:00",
                "level": "INFO",
                "stage": "note_model_call",
                "message": "requesting",
                "details": {
                    "context": "note-chunk-7-of-16",
                    "attempt": 1,
                    "note_base_url": "https://open.bigmodel.cn/api/coding/paas/v4",
                    "note_model": "glm-5.2",
                    "message_chars": 12913,
                    "max_tokens": 2200,
                },
            },
            {
                "ts": "2026-06-26T05:21:00+00:00",
                "level": "INFO",
                "stage": "note_model_call",
                "message": "response_received",
                "details": {
                    "context": "note-chunk-7-of-16",
                    "attempt": 1,
                    "response_file": "debug/note-chunk-7-of-16-model-response-attempt-1.txt",
                    "response_length": 0,
                    "finish_reason": "length",
                },
            },
            {
                "ts": "2026-06-26T05:21:01+00:00",
                "level": "INFO",
                "stage": "note_model_call",
                "message": "invalid_json",
                "details": {
                    "context": "note-chunk-7-of-16",
                    "attempt": 1,
                    "error": "Model returned invalid note JSON: Expecting value: line 1 column 1 (char 0)",
                },
            },
            {
                "ts": "2026-06-26T05:21:02+00:00",
                "level": "ERROR",
                "stage": "regenerate_note_job",
                "message": "failed",
                "details": {
                    "exception_type": "LLMError",
                    "exception_message": "Model returned invalid note JSON: Expecting value: line 1 column 1 (char 0)",
                },
            },
        ],
    )

    response = TestClient(app).get("/api/jobs/invalid-json-response-details-job")

    assert response.status_code == 200
    failure_context = response.json()["failure_context"]
    assert failure_context["context"] == "note-chunk-7-of-16"
    assert failure_context["note_model"] == "glm-5.2"
    assert failure_context["message_chars"] == 12913
    assert failure_context["max_tokens"] == 2200
    assert failure_context["response_file"] == "debug/note-chunk-7-of-16-model-response-attempt-1.txt"
    assert failure_context["response_length"] == 0
    assert failure_context["finish_reason"] == "length"
    assert "response_length=0" in failure_context["summary"]
    assert "finish_reason=length" in failure_context["summary"]
    assert "debug/note-chunk-7-of-16-model-response-attempt-1.txt" in failure_context["summary"]


def test_history_summarizes_content_filtered_note_json_failures(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(main, "OUTPUTS_ROOT", tmp_path)
    monkeypatch.setattr(main, "store", JobStore(tmp_path))
    write_history_job(
        tmp_path,
        "content-filtered-json-failed-job",
        created_at="2026-06-26T05:40:00+00:00",
        title="Content Filtered Json Failed",
        original_filename="content-filtered-json.mp4",
    )
    append_debug_events(
        tmp_path,
        "content-filtered-json-failed-job",
        [
            {
                "ts": "2026-06-26T05:40:00+00:00",
                "level": "INFO",
                "stage": "regenerate_note_job",
                "message": "started",
                "details": {},
            },
            {
                "ts": "2026-06-26T05:41:00+00:00",
                "level": "INFO",
                "stage": "note_model_call",
                "message": "response_received",
                "details": {
                    "context": "note-chunk-8-of-16",
                    "attempt": 1,
                    "response_length": 0,
                    "finish_reason": "content_filter",
                },
            },
            {
                "ts": "2026-06-26T05:41:01+00:00",
                "level": "INFO",
                "stage": "note_model_call",
                "message": "invalid_json",
                "details": {
                    "context": "note-chunk-8-of-16",
                    "attempt": 1,
                    "error": "Model returned invalid note JSON: Expecting value: line 1 column 1 (char 0)",
                },
            },
            {
                "ts": "2026-06-26T05:41:02+00:00",
                "level": "ERROR",
                "stage": "regenerate_note_job",
                "message": "failed",
                "details": {
                    "exception_type": "LLMError",
                    "exception_message": "Model returned invalid note JSON: Expecting value: line 1 column 1 (char 0)",
                },
            },
        ],
    )

    client = TestClient(app)
    response = client.get("/api/jobs/content-filtered-json-failed-job")
    history_response = client.get("/api/jobs")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "failed"
    assert "finish_reason=content_filter" in payload["error"]
    assert "JSON" in payload["error"]
    assert history_response.status_code == 200
    history_job = history_response.json()["jobs"][0]
    assert history_job["status"] == "failed"
    assert "finish_reason=content_filter" in history_job["error"]


def test_history_summarizes_direct_content_filter_finish_reason_failures(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(main, "OUTPUTS_ROOT", tmp_path)
    monkeypatch.setattr(main, "store", JobStore(tmp_path))
    write_history_job(
        tmp_path,
        "direct-content-filter-job",
        created_at="2026-06-26T05:50:00+00:00",
        title="Direct Content Filter",
        original_filename="content-filter.mp4",
    )
    append_debug_events(
        tmp_path,
        "direct-content-filter-job",
        [
            {
                "ts": "2026-06-26T05:50:00+00:00",
                "level": "INFO",
                "stage": "regenerate_note_job",
                "message": "started",
                "details": {},
            },
            {
                "ts": "2026-06-26T05:51:00+00:00",
                "level": "INFO",
                "stage": "note_model_call",
                "message": "response_received",
                "details": {
                    "context": "note-chunk-8-of-16",
                    "attempt": 1,
                    "response_length": 0,
                    "finish_reason": "content_filter",
                },
            },
            {
                "ts": "2026-06-26T05:51:01+00:00",
                "level": "ERROR",
                "stage": "regenerate_note_job",
                "message": "failed",
                "details": {
                    "exception_type": "LLMError",
                    "exception_message": "Model response was filtered by content policy (finish_reason=content_filter).",
                },
            },
        ],
    )

    client = TestClient(app)
    response = client.get("/api/jobs/direct-content-filter-job")
    history_response = client.get("/api/jobs")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "failed"
    assert "finish_reason=content_filter" in payload["error"]
    assert "内容" in payload["error"]
    assert "Model response was filtered" not in payload["error"]
    assert history_response.status_code == 200
    history_job = history_response.json()["jobs"][0]
    assert history_job["status"] == "failed"
    assert "finish_reason=content_filter" in history_job["error"]
    assert "Model response was filtered" not in history_job["error"]


def test_history_recovers_latest_failure_from_malformed_debug_line(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(main, "OUTPUTS_ROOT", tmp_path)
    monkeypatch.setattr(main, "store", JobStore(tmp_path))
    write_history_job(
        tmp_path,
        "malformed-debug-job",
        created_at="2026-06-27T00:00:00+00:00",
        title="Malformed Debug",
        original_filename="debug.mp4",
    )
    debug_log = tmp_path / "malformed-debug-job" / "debug.log"
    debug_log.write_text(
        json.dumps(
            {
                "ts": "2026-06-27T01:00:00+00:00",
                "level": "INFO",
                "stage": "regenerate_note_job",
                "message": "succeeded",
                "details": {},
            }
        )
        + "\n"
        + '{"ts":"2026-06-27T02:00:00+00:00","level":"ERROR","stage":"regenerate_note_job","message":"failed","details":{"exception_type":"AuthenticationError","exception_message":"Error code: 401 - invalid token"\n',
        encoding="utf-8",
    )

    response = TestClient(app).get("/api/jobs/malformed-debug-job")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "failed"
    assert "invalid token" in payload["error"]


def test_history_uses_timestamp_from_malformed_debug_line(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(main, "OUTPUTS_ROOT", tmp_path)
    monkeypatch.setattr(main, "store", JobStore(tmp_path))
    write_history_job(
        tmp_path,
        "malformed-latest-job",
        created_at="2026-06-26T00:00:00+00:00",
        title="Malformed Latest",
        original_filename="debug.mp4",
    )
    write_history_job(
        tmp_path,
        "newer-clean-job",
        created_at="2026-06-28T00:00:00+00:00",
        title="Newer Clean",
        original_filename="clean.mp4",
    )
    debug_log = tmp_path / "malformed-latest-job" / "debug.log"
    debug_log.write_text(
        json.dumps(
            {
                "ts": "2026-06-26T01:00:00+00:00",
                "level": "INFO",
                "stage": "regenerate_note_job",
                "message": "succeeded",
                "details": {},
            }
        )
        + "\n"
        + '{"ts":"2026-06-29T02:00:00+00:00","level":"ERROR","stage":"regenerate_note_job","message":"failed","details":{"exception_type":"AuthenticationError","exception_message":"Error code: 401 - invalid token"\n',
        encoding="utf-8",
    )
    os.utime(debug_log, (1782259200, 1782259200))

    response = TestClient(app).get("/api/jobs")

    assert response.status_code == 200
    jobs = response.json()["jobs"]
    assert [job["job_id"] for job in jobs] == ["malformed-latest-job", "newer-clean-job"]
    assert jobs[0]["updated_at"] == "2026-06-29T02:00:00+00:00"
    assert jobs[0]["status"] == "failed"
    assert "invalid token" in jobs[0]["error"]


def test_history_reports_interrupted_attempt_after_older_failure(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(main, "OUTPUTS_ROOT", tmp_path)
    monkeypatch.setattr(main, "store", JobStore(tmp_path))
    write_history_job(
        tmp_path,
        "interrupted-regeneration-job",
        created_at="2026-06-28T00:00:00+00:00",
        title="Interrupted Debug",
        original_filename="interrupted.mp4",
    )
    append_debug_events(
        tmp_path,
        "interrupted-regeneration-job",
        [
            {
                "ts": "2026-06-28T01:00:00+00:00",
                "level": "ERROR",
                "stage": "regenerate_note_job",
                "message": "failed",
                "details": {
                    "exception_type": "BadRequestError",
                    "exception_message": "content_policy_violation",
                },
            },
            {
                "ts": "2026-06-28T02:00:00+00:00",
                "level": "INFO",
                "stage": "regenerate_note_job",
                "message": "started",
                "details": {},
            },
            {
                "ts": "2026-06-28T02:01:00+00:00",
                "level": "INFO",
                "stage": "note_model_call",
                "message": "requesting",
                "details": {
                    "context": "note-chunk-3-of-16",
                    "attempt": 1,
                },
            },
        ],
    )

    client = TestClient(app)
    response = client.get("/api/jobs/interrupted-regeneration-job")
    history_response = client.get("/api/jobs")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "failed"
    assert payload["step"] == "最近一次处理中断"
    assert "中断" in payload["error"]
    assert "note_model_call" in payload["error"]
    assert "note-chunk-3-of-16" in payload["error"]
    assert history_response.status_code == 200
    history_job = history_response.json()["jobs"][0]
    assert history_job["status"] == "failed"
    assert "note_model_call" in history_job["error"]
    assert "note-chunk-3-of-16" in history_job["error"]


def test_history_includes_model_request_details_for_interrupted_attempt(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(main, "OUTPUTS_ROOT", tmp_path)
    monkeypatch.setattr(main, "store", JobStore(tmp_path))
    write_history_job(
        tmp_path,
        "interrupted-model-request-job",
        created_at="2026-06-28T00:00:00+00:00",
        title="Interrupted Model Request",
        original_filename="interrupted.mp4",
    )
    append_debug_events(
        tmp_path,
        "interrupted-model-request-job",
        [
            {
                "ts": "2026-06-28T02:00:00+00:00",
                "level": "INFO",
                "stage": "regenerate_note_job",
                "message": "started",
                "details": {},
            },
            {
                "ts": "2026-06-28T02:01:00+00:00",
                "level": "INFO",
                "stage": "note_model_call",
                "message": "requesting",
                "details": {
                    "context": "note-chunk-3-of-16",
                    "attempt": 1,
                    "note_base_url": "https://api.cdn-krill-ai.com/codex/v1",
                    "note_model": "gpt-5.3-codex-spark",
                    "message_chars": 11453,
                    "max_tokens": 2200,
                },
            },
        ],
    )

    response = TestClient(app).get("/api/jobs/interrupted-model-request-job")
    history_response = TestClient(app).get("/api/jobs")

    assert response.status_code == 200
    payload = response.json()
    error = payload["error"]
    assert "note-chunk-3-of-16" in error
    assert "第 1 次请求" in error
    assert "gpt-5.3-codex-spark" in error
    assert "https://api.cdn-krill-ai.com/codex/v1" in error
    assert "11453 字符" in error
    assert "max_tokens=2200" in error
    assert payload["failure_context"] == {
        "ts": "2026-06-28T02:01:00+00:00",
        "stage": "note_model_call",
        "message": "requesting",
        "context": "note-chunk-3-of-16",
        "attempt": 1,
        "note_base_url": "https://api.cdn-krill-ai.com/codex/v1",
        "note_model": "gpt-5.3-codex-spark",
        "message_chars": 11453,
        "max_tokens": 2200,
        "summary": "note-chunk-3-of-16，第 1 次请求，模型 gpt-5.3-codex-spark，接口 https://api.cdn-krill-ai.com/codex/v1，11453 字符，max_tokens=2200",
    }
    assert history_response.status_code == 200
    assert history_response.json()["jobs"][0]["failure_context"] == payload["failure_context"]


def test_history_recovers_interrupted_context_from_malformed_debug_line(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(main, "OUTPUTS_ROOT", tmp_path)
    monkeypatch.setattr(main, "store", JobStore(tmp_path))
    write_history_job(
        tmp_path,
        "malformed-interrupted-job",
        created_at="2026-06-28T00:00:00+00:00",
        title="Malformed Interrupted",
        original_filename="interrupted.mp4",
    )
    debug_log = tmp_path / "malformed-interrupted-job" / "debug.log"
    debug_log.write_text(
        json.dumps(
            {
                "ts": "2026-06-28T02:00:00+00:00",
                "level": "INFO",
                "stage": "regenerate_note_job",
                "message": "started",
                "details": {},
            }
        )
        + "\n"
        + '{"ts":"2026-06-28T02:01:00+00:00","level":"INFO","stage":"note_model_call","message":"requesting","details":{"context":"note-chunk-7-of-16","attempt":1\n',
        encoding="utf-8",
    )

    response = TestClient(app).get("/api/jobs/malformed-interrupted-job")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "failed"
    assert "note_model_call" in payload["error"]
    assert "note-chunk-7-of-16" in payload["error"]
    assert payload["updated_at"] == "2026-06-28T02:01:00+00:00"


def test_history_recovers_model_request_details_from_malformed_interrupted_line(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(main, "OUTPUTS_ROOT", tmp_path)
    monkeypatch.setattr(main, "store", JobStore(tmp_path))
    write_history_job(
        tmp_path,
        "malformed-request-details-job",
        created_at="2026-06-28T00:00:00+00:00",
        title="Malformed Request Details",
        original_filename="interrupted.mp4",
    )
    debug_log = tmp_path / "malformed-request-details-job" / "debug.log"
    debug_log.write_text(
        json.dumps(
            {
                "ts": "2026-06-28T02:00:00+00:00",
                "level": "INFO",
                "stage": "regenerate_note_job",
                "message": "started",
                "details": {},
            }
        )
        + "\n"
        + '{"ts":"2026-06-28T02:01:00+00:00","level":"INFO","stage":"note_model_call","message":"requesting","details":{"context":"note-chunk-3-of-16","attempt":1,"note_base_url":"https://api.cdn-krill-ai.com/codex/v1","note_model":"gpt-5.3-codex-spark","message_chars":11453,"max_tokens":2200\n',
        encoding="utf-8",
    )

    response = TestClient(app).get("/api/jobs/malformed-request-details-job")

    assert response.status_code == 200
    error = response.json()["error"]
    assert "note-chunk-3-of-16" in error
    assert "gpt-5.3-codex-spark" in error
    assert "https://api.cdn-krill-ai.com/codex/v1" in error
    assert "11453" in error
    assert "max_tokens=2200" in error


def test_get_job_loads_disk_history_when_job_is_not_in_memory(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(main, "OUTPUTS_ROOT", tmp_path)
    monkeypatch.setattr(main, "store", JobStore(tmp_path))
    write_history_job(
        tmp_path,
        "disk-job",
        created_at="2026-06-21T00:00:00+00:00",
        title="Disk",
        original_filename="disk.mp4",
    )

    response = TestClient(app).get("/api/jobs/disk-job")

    assert response.status_code == 200
    payload = response.json()
    assert payload["job_id"] == "disk-job"
    assert payload["status"] == "succeeded"
    assert payload["step"] == "已从历史记录载入"
    assert {artifact["path"] for artifact in payload["artifacts"]} == {"metadata.json", "note.md", "subtitles.md"}


def test_get_job_uses_article_title_for_zip_download_filename(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(main, "OUTPUTS_ROOT", tmp_path)
    monkeypatch.setattr(main, "store", JobStore(tmp_path))
    write_history_job(
        tmp_path,
        "zip-title-job",
        created_at="2026-07-06T00:00:00+00:00",
        title="Self-Attention 详解：计算流程/缩放技巧",
        original_filename="input.mp4",
    )
    (tmp_path / "zip-title-job" / "download.zip").write_bytes(b"zip")

    response = TestClient(app).get("/api/jobs/zip-title-job")

    assert response.status_code == 200
    payload = response.json()
    assert payload["download_filename"] == "Self-Attention 详解：计算流程_缩放技巧.zip"


def test_get_job_loads_note_review_pending_state_from_disk(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(main, "OUTPUTS_ROOT", tmp_path)
    monkeypatch.setattr(main, "store", JobStore(tmp_path))
    write_history_job(
        tmp_path,
        "note-review-job",
        created_at="2026-07-06T00:00:00+00:00",
        title="Review",
        original_filename="review.mp4",
    )
    (tmp_path / "note-review-job" / ".note-review.pending").write_text("1", encoding="utf-8")

    response = TestClient(app).get("/api/jobs/note-review-job")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "awaiting_note_review"
    assert payload["progress"] == 92


def test_get_job_uses_latest_debug_activity_as_loaded_timestamp(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(main, "OUTPUTS_ROOT", tmp_path)
    monkeypatch.setattr(main, "store", JobStore(tmp_path))
    write_history_job(
        tmp_path,
        "disk-activity-job",
        created_at="2026-06-21T00:00:00+00:00",
        title="Disk Activity",
        original_filename="disk-activity.mp4",
    )
    append_debug_events(
        tmp_path,
        "disk-activity-job",
        [
            {
                "ts": "2026-06-21T03:00:00+00:00",
                "level": "INFO",
                "stage": "regenerate_note_job",
                "message": "succeeded",
                "details": {},
            },
        ],
    )

    response = TestClient(app).get("/api/jobs/disk-activity-job")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "succeeded"
    assert payload["step_started_at"] == "2026-06-21T03:00:00+00:00"
    assert payload["updated_at"] == "2026-06-21T03:00:00+00:00"


def test_get_job_loads_incomplete_disk_history_as_failed(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(main, "OUTPUTS_ROOT", tmp_path)
    monkeypatch.setattr(main, "store", JobStore(tmp_path))
    write_partial_history_job(
        tmp_path,
        "partial-job",
        created_at="2026-06-22T00:00:00+00:00",
        title="Partial",
        original_filename="partial.mp4",
    )

    response = TestClient(app).get("/api/jobs/partial-job")

    assert response.status_code == 200
    payload = response.json()
    assert payload["job_id"] == "partial-job"
    assert payload["status"] == "failed"
    assert payload["step"] == "历史任务不完整"
    assert {artifact["path"] for artifact in payload["artifacts"]} == {"audio.mp3", "metadata.json"}


def test_get_job_rejects_encoded_dot_job_id_without_loading_outputs_root(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(main, "OUTPUTS_ROOT", tmp_path)
    monkeypatch.setattr(main, "store", JobStore(tmp_path))
    (tmp_path / "root-sentinel.txt").write_text("keep root", encoding="utf-8")

    response = TestClient(app, raise_server_exceptions=False).get("/api/jobs/%2E")

    assert response.status_code == 400
    assert response.json()["detail"] == "Invalid job id."
    assert (tmp_path / "root-sentinel.txt").exists()


def test_get_job_rejects_drive_relative_job_id_alias(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(main, "OUTPUTS_ROOT", tmp_path)
    monkeypatch.setattr(main, "store", JobStore(tmp_path))
    write_history_job(
        tmp_path,
        "foo",
        created_at="2026-06-24T00:00:00+00:00",
        title="Foo",
        original_filename="foo.mp4",
    )

    response = TestClient(app, raise_server_exceptions=False).get("/api/jobs/C:foo")

    assert response.status_code == 400
    assert response.json()["detail"] == "Invalid job id."


def test_delete_job_removes_disk_history(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(main, "OUTPUTS_ROOT", tmp_path)
    monkeypatch.setattr(main, "store", JobStore(tmp_path))
    write_history_job(
        tmp_path,
        "delete-job",
        created_at="2026-06-21T00:00:00+00:00",
        title="Delete",
        original_filename="delete.mp4",
    )

    response = TestClient(app).delete("/api/jobs/delete-job")

    assert response.status_code == 200
    assert response.json() == {"ok": True}
    assert not (tmp_path / "delete-job").exists()
    assert TestClient(app).get("/api/jobs/delete-job").status_code == 404


def test_delete_loaded_history_job_removes_memory_state_and_disk_files(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(main, "OUTPUTS_ROOT", tmp_path)
    monkeypatch.setattr(main, "store", JobStore(tmp_path))
    write_history_job(
        tmp_path,
        "loaded-job",
        created_at="2026-06-21T00:00:00+00:00",
        title="Loaded",
        original_filename="loaded.mp4",
    )
    client = TestClient(app, raise_server_exceptions=False)

    assert client.get("/api/jobs/loaded-job").status_code == 200
    response = client.delete("/api/jobs/loaded-job")

    assert response.status_code == 200
    assert response.json() == {"ok": True}
    assert not (tmp_path / "loaded-job").exists()
    assert main.store.get("loaded-job") is None


def test_delete_job_rejects_encoded_dot_job_id_without_deleting_outputs_root(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(main, "OUTPUTS_ROOT", tmp_path)
    monkeypatch.setattr(main, "store", JobStore(tmp_path))
    (tmp_path / "root-sentinel.txt").write_text("keep root", encoding="utf-8")

    response = TestClient(app, raise_server_exceptions=False).delete("/api/jobs/%2E")

    assert response.status_code == 400
    assert response.json()["detail"] == "Invalid job id."
    assert tmp_path.exists()
    assert (tmp_path / "root-sentinel.txt").exists()


def test_delete_job_rejects_drive_relative_job_id_alias(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(main, "OUTPUTS_ROOT", tmp_path)
    monkeypatch.setattr(main, "store", JobStore(tmp_path))
    write_history_job(
        tmp_path,
        "foo",
        created_at="2026-06-24T00:00:00+00:00",
        title="Foo",
        original_filename="foo.mp4",
    )

    response = TestClient(app, raise_server_exceptions=False).delete("/api/jobs/C:foo")

    assert response.status_code == 400
    assert response.json()["detail"] == "Invalid job id."
    assert (tmp_path / "foo").exists()


def test_delete_job_returns_json_error_when_files_are_in_use(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(main, "OUTPUTS_ROOT", tmp_path)
    monkeypatch.setattr(main, "store", JobStore(tmp_path))
    write_history_job(
        tmp_path,
        "locked-job",
        created_at="2026-06-21T00:00:00+00:00",
        title="Locked",
        original_filename="locked.mp4",
    )

    def fail_rmtree(_path) -> None:
        raise PermissionError("file is locked")

    monkeypatch.setattr(main.shutil, "rmtree", fail_rmtree)

    response = TestClient(app, raise_server_exceptions=False).delete("/api/jobs/locked-job")

    assert response.status_code == 409
    assert "files are in use" in response.json()["detail"]
    assert (tmp_path / "locked-job").exists()
