from __future__ import annotations

import os

from fastapi.testclient import TestClient

from backend.app import main
from backend.app.job_store import JobStore
from backend.app.main import app
from backend.app.models import Chapter, JobStatus, KeyMoment, NoteDraft


def test_create_job_rejects_missing_local_faster_whisper_model(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("FASTER_WHISPER_MODEL_DIR", str(tmp_path / "models"))
    client = TestClient(app)

    response = client.post(
        "/api/jobs",
        data={
            "transcription_mode": "local_faster_whisper",
            "transcription_model": "small",
            "note_api_key": "note-key",
            "note_base_url": "https://api.openai.com/v1",
            "note_model": "gpt-5.5",
            "note_language": "zh",
            "note_style": "detailed",
            "frame_limit": "6",
        },
        files={"video": ("input.mp4", b"fake video", "video/mp4")},
    )

    assert response.status_code == 400
    assert "Local Faster Whisper model 'small' is not available" in response.json()["detail"]


def test_create_job_rejects_invalid_config_before_creating_output_dir(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(main, "OUTPUTS_ROOT", tmp_path)
    monkeypatch.setattr(main, "store", JobStore(tmp_path))

    response = TestClient(app, raise_server_exceptions=False).post(
        "/api/jobs",
        data={
            "transcription_mode": "local_faster_whisper",
            "transcription_model": "small",
            "local_whisper_device": "gpu",
            "note_api_key": "note-key",
            "note_base_url": "https://api.openai.com/v1",
            "note_model": "gpt-5.5",
            "note_language": "zh",
            "note_style": "detailed",
            "frame_limit": "6",
        },
        files={"video": ("input.mp4", b"fake video", "video/mp4")},
    )

    assert response.status_code == 400
    assert "local_whisper_device must be auto, cpu, or cuda" in response.json()["detail"]
    assert list(tmp_path.iterdir()) == []


def test_create_job_cleans_output_dir_when_video_copy_fails(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(main, "OUTPUTS_ROOT", tmp_path)
    monkeypatch.setattr(main, "store", JobStore(tmp_path))

    def fail_copy(_source, _target) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(main.shutil, "copyfileobj", fail_copy)

    response = TestClient(app, raise_server_exceptions=False).post(
        "/api/jobs",
        data={
            "transcription_mode": "audio_transcriptions",
            "transcription_api_key": "transcription-key",
            "transcription_base_url": "https://api.openai.com/v1",
            "transcription_model": "whisper-1",
            "note_api_key": "note-key",
            "note_base_url": "https://api.openai.com/v1",
            "note_model": "gpt-5.5",
            "note_language": "zh",
            "note_style": "detailed",
            "frame_limit": "6",
        },
        files={"video": ("input.mp4", b"fake video", "video/mp4")},
    )

    assert response.status_code == 400
    assert "Cannot create job files" in response.json()["detail"]
    assert list(tmp_path.iterdir()) == []


def test_create_job_rejects_local_cuda_when_runtime_is_not_ready(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(main, "OUTPUTS_ROOT", tmp_path)
    monkeypatch.setattr(main, "store", JobStore(tmp_path))
    monkeypatch.setattr(main, "resolve_local_faster_whisper_model", lambda *_args, **_kwargs: "small")
    monkeypatch.setattr(
        main,
        "get_runtime_status",
        lambda: {
            "faster_whisper": {
                "ready_for_cuda": False,
                "cuda_runtime_hint": "请安装 CUDA 运行库，或切回 CPU。",
                "cuda_error": "missing ctranslate2 cuda runtime",
            }
        },
    )

    response = TestClient(app, raise_server_exceptions=False).post(
        "/api/jobs",
        data={
            "transcription_mode": "local_faster_whisper",
            "transcription_model": "small",
            "local_whisper_device": "cuda",
            "local_whisper_compute_type": "float16",
            "note_api_key": "note-key",
            "note_base_url": "https://api.openai.com/v1",
            "note_model": "gpt-5.5",
            "note_language": "zh",
            "note_style": "detailed",
            "frame_limit": "6",
        },
        files={"video": ("input.mp4", b"fake video", "video/mp4")},
    )

    assert response.status_code == 400
    assert "CUDA" in response.json()["detail"]
    assert list(tmp_path.iterdir()) == []


def test_frame_suggestion_rejects_invalid_config_before_creating_temp_dir(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(main, "OUTPUTS_ROOT", tmp_path)
    monkeypatch.setattr(main, "resolve_local_faster_whisper_model", lambda *_args, **_kwargs: "small")

    response = TestClient(app, raise_server_exceptions=False).post(
        "/api/jobs/frame-suggestion",
        data={
            "transcription_mode": "local_faster_whisper",
            "transcription_model": "small",
            "local_whisper_device": "gpu",
            "note_api_key": "note-key",
            "note_base_url": "https://api.openai.com/v1",
            "note_model": "gpt-5.5",
            "note_language": "zh",
            "note_style": "detailed",
        },
        files={"video": ("input.mp4", b"fake video", "video/mp4")},
    )

    assert response.status_code == 400
    assert "local_whisper_device must be auto, cpu, or cuda" in response.json()["detail"]
    assert list(tmp_path.iterdir()) == []


def test_frame_suggestion_rejects_local_cuda_when_runtime_is_not_ready_before_creating_temp_dir(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(main, "OUTPUTS_ROOT", tmp_path)
    monkeypatch.setattr(main, "resolve_local_faster_whisper_model", lambda *_args, **_kwargs: "small")
    monkeypatch.setattr(
        main,
        "get_runtime_status",
        lambda: {
            "faster_whisper": {
                "ready_for_cuda": False,
                "cuda_runtime_hint": "请安装 CUDA 运行库，或切回 CPU。",
                "cuda_error": "missing ctranslate2 cuda runtime",
            }
        },
    )
    monkeypatch.setattr(main, "probe_duration", lambda _video_path: 42.0, raising=False)
    monkeypatch.setattr(main, "extract_mp3", lambda _video_path, audio_path: audio_path.write_bytes(b"mp3"), raising=False)
    monkeypatch.setattr(
        main,
        "transcribe_audio",
        lambda _audio_path, _config, _job_dir: {"text": "hello", "segments": [{"start": 0, "end": 2, "text": "hello"}]},
        raising=False,
    )
    monkeypatch.setattr(
        main,
        "generate_note_draft",
        lambda _config, _duration, _segments: NoteDraft(
            title="Demo",
            summary="summary",
            chapters=[Chapter(title="Opening", start_time=0, end_time=2)],
            key_moments=[KeyMoment(time=1, reason="opening", chapter_index=0)],
            recommended_frame_count=7,
        ),
        raising=False,
    )

    response = TestClient(app, raise_server_exceptions=False).post(
        "/api/jobs/frame-suggestion",
        data={
            "transcription_mode": "local_faster_whisper",
            "transcription_model": "small",
            "local_whisper_device": "cuda",
            "local_whisper_compute_type": "float16",
            "note_api_key": "note-key",
            "note_base_url": "https://api.openai.com/v1",
            "note_model": "gpt-5.5",
            "note_language": "zh",
            "note_style": "detailed",
        },
        files={"video": ("input.mp4", b"fake video", "video/mp4")},
    )

    assert response.status_code == 400
    assert "CUDA" in response.json()["detail"]
    assert list(tmp_path.iterdir()) == []


def test_frame_suggestion_returns_recommended_count_from_note_draft(monkeypatch) -> None:
    client = TestClient(app)

    monkeypatch.setattr(main, "probe_duration", lambda _video_path: 42.0, raising=False)
    monkeypatch.setattr(main, "extract_mp3", lambda _video_path, audio_path: audio_path.write_bytes(b"mp3"), raising=False)
    monkeypatch.setattr(
        main,
        "transcribe_audio",
        lambda _audio_path, _config, _job_dir: {"text": "hello", "segments": [{"start": 0, "end": 2, "text": "hello"}]},
        raising=False,
    )
    monkeypatch.setattr(
        main,
        "generate_note_draft",
        lambda _config, _duration, _segments: NoteDraft(
            title="Demo",
            summary="summary",
            chapters=[Chapter(title="Opening", start_time=0, end_time=2)],
            key_moments=[KeyMoment(time=1, reason="opening", chapter_index=0)],
            recommended_frame_count=7,
        ),
        raising=False,
    )

    response = client.post(
        "/api/jobs/frame-suggestion",
        data={
            "transcription_mode": "audio_transcriptions",
            "transcription_api_key": "transcription-key",
            "transcription_base_url": "https://api.openai.com/v1",
            "transcription_model": "whisper-1",
            "note_api_key": "note-key",
            "note_base_url": "https://api.openai.com/v1",
            "note_model": "gpt-5.5",
            "note_language": "zh",
            "note_style": "detailed",
            "extras": "",
        },
        files={"video": ("input.mp4", b"fake video", "video/mp4")},
    )

    assert response.status_code == 200
    assert response.json() == {
        "recommended_frame_count": 7,
        "candidate_count": 1,
        "reasons": ["opening"],
    }


def test_frame_suggestion_fallback_uses_product_frame_limit(monkeypatch) -> None:
    client = TestClient(app)

    monkeypatch.setattr(main, "probe_duration", lambda _video_path: 42.0, raising=False)
    monkeypatch.setattr(main, "extract_mp3", lambda _video_path, audio_path: audio_path.write_bytes(b"mp3"), raising=False)
    monkeypatch.setattr(
        main,
        "transcribe_audio",
        lambda _audio_path, _config, _job_dir: {"text": "hello", "segments": [{"start": 0, "end": 2, "text": "hello"}]},
        raising=False,
    )
    monkeypatch.setattr(
        main,
        "generate_note_draft",
        lambda _config, _duration, _segments: NoteDraft(
            title="Demo",
            summary="summary",
            key_moments=[
                KeyMoment(time=index, reason=f"moment {index}", chapter_index=0)
                for index in range(18)
            ],
        ),
        raising=False,
    )

    response = client.post(
        "/api/jobs/frame-suggestion",
        data={
            "transcription_mode": "audio_transcriptions",
            "transcription_api_key": "transcription-key",
            "transcription_base_url": "https://api.openai.com/v1",
            "transcription_model": "whisper-1",
            "note_api_key": "note-key",
            "note_base_url": "https://api.openai.com/v1",
            "note_model": "gpt-5.5",
            "note_language": "zh",
            "note_style": "detailed",
            "extras": "",
        },
        files={"video": ("input.mp4", b"fake video", "video/mp4")},
    )

    assert response.status_code == 200
    assert response.json()["recommended_frame_count"] == 18
    assert response.json()["candidate_count"] == 18


def test_frame_suggestion_analyzes_against_product_frame_limit(monkeypatch) -> None:
    captured_frame_limits: list[int] = []
    client = TestClient(app)

    monkeypatch.setattr(main, "probe_duration", lambda _video_path: 42.0, raising=False)
    monkeypatch.setattr(main, "extract_mp3", lambda _video_path, audio_path: audio_path.write_bytes(b"mp3"), raising=False)
    monkeypatch.setattr(
        main,
        "transcribe_audio",
        lambda _audio_path, _config, _job_dir: {"text": "hello", "segments": [{"start": 0, "end": 2, "text": "hello"}]},
        raising=False,
    )

    def fake_generate_note_draft(config, _duration, _segments):
        captured_frame_limits.append(config.frame_limit)
        return NoteDraft(title="Demo", summary="summary", key_moments=[KeyMoment(time=1, reason="opening")])

    monkeypatch.setattr(main, "generate_note_draft", fake_generate_note_draft, raising=False)

    response = client.post(
        "/api/jobs/frame-suggestion",
        data={
            "transcription_mode": "audio_transcriptions",
            "transcription_api_key": "transcription-key",
            "transcription_base_url": "https://api.openai.com/v1",
            "transcription_model": "whisper-1",
            "note_api_key": "note-key",
            "note_base_url": "https://api.openai.com/v1",
            "note_model": "gpt-5.5",
            "note_language": "zh",
            "note_style": "detailed",
            "extras": "",
        },
        files={"video": ("input.mp4", b"fake video", "video/mp4")},
    )

    assert response.status_code == 200
    assert captured_frame_limits == [24]


def test_text_asset_response_uses_utf8_attachment_headers(tmp_path, monkeypatch) -> None:
    job_dir = tmp_path / "job-text"
    job_dir.mkdir(parents=True)
    (job_dir / "note.md").write_text("# 中文标题\n\n内容", encoding="utf-8")
    monkeypatch.setattr(main, "OUTPUTS_ROOT", tmp_path)
    client = TestClient(app)

    response = client.get("/api/jobs/job-text/assets/note.md")

    assert response.status_code == 200
    assert "attachment" in response.headers["content-disposition"].lower()
    assert "note.md" in response.headers["content-disposition"]
    assert "charset=utf-8" in response.headers["content-type"].lower()


def test_create_job_accepts_frame_limit_24_and_exposes_stage_timestamps(tmp_path, monkeypatch) -> None:
    client = TestClient(app)
    monkeypatch.setattr(main, "OUTPUTS_ROOT", tmp_path)

    response = client.post(
        "/api/jobs",
        data={
            "transcription_mode": "audio_transcriptions",
            "transcription_api_key": "transcription-key",
            "transcription_base_url": "https://api.openai.com/v1",
            "transcription_model": "whisper-1",
            "note_api_key": "note-key",
            "note_base_url": "https://api.openai.com/v1",
            "note_model": "gpt-5.5",
            "note_language": "zh",
            "note_style": "detailed",
            "frame_limit": "24",
        },
        files={"video": ("input.mp4", b"fake video", "video/mp4")},
    )

    assert response.status_code == 200
    job_id = response.json()["job_id"]

    state_response = client.get(f"/api/jobs/{job_id}")
    assert state_response.status_code == 200
    payload = state_response.json()
    assert payload["step_started_at"]
    assert payload["updated_at"]
    assert payload["stage_elapsed_seconds"] == 0


def test_create_job_keeps_previous_output_dirs(tmp_path, monkeypatch) -> None:
    old_job_dirs = []
    for index in range(4):
        old_job_dir = tmp_path / f"old-job-{index}"
        old_job_dir.mkdir()
        (old_job_dir / "note.md").write_text("# old", encoding="utf-8")
        os.utime(old_job_dir, (index + 1, index + 1))
        old_job_dirs.append(old_job_dir)

    monkeypatch.setattr(main, "OUTPUTS_ROOT", tmp_path)
    monkeypatch.setattr(main, "store", JobStore(tmp_path))
    monkeypatch.setattr(main, "process_transcription_job", lambda **_kwargs: None)

    response = TestClient(app).post(
        "/api/jobs",
        data={
            "transcription_mode": "audio_transcriptions",
            "transcription_api_key": "transcription-key",
            "transcription_base_url": "https://api.openai.com/v1",
            "transcription_model": "whisper-1",
            "note_api_key": "note-key",
            "note_base_url": "https://api.openai.com/v1",
            "note_model": "gpt-5.5",
            "note_language": "zh",
            "note_style": "detailed",
            "frame_limit": "6",
        },
        files={"video": ("input.mp4", b"fake video", "video/mp4")},
    )

    assert response.status_code == 200
    assert all(job_dir.exists() for job_dir in old_job_dirs)


def test_create_job_seeds_history_title_from_uploaded_filename(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(main, "OUTPUTS_ROOT", tmp_path)
    monkeypatch.setattr(main, "store", JobStore(tmp_path))
    monkeypatch.setattr(main, "process_transcription_job", lambda **_kwargs: None)

    response = TestClient(app).post(
        "/api/jobs",
        data={
            "transcription_mode": "audio_transcriptions",
            "transcription_api_key": "transcription-key",
            "transcription_base_url": "https://api.openai.com/v1",
            "transcription_model": "whisper-1",
            "note_api_key": "note-key",
            "note_base_url": "https://api.openai.com/v1",
            "note_model": "gpt-5.5",
            "note_language": "zh",
            "note_style": "detailed",
            "frame_limit": "6",
        },
        files={"video": ("02_梯度消失问题.mp4", b"fake video", "video/mp4")},
    )

    assert response.status_code == 200
    job_id = response.json()["job_id"]

    history_response = TestClient(app).get("/api/jobs")

    assert history_response.status_code == 200
    jobs = history_response.json()["jobs"]
    assert jobs[0]["job_id"] == job_id
    assert jobs[0]["title"] == "02_梯度消失问题.mp4"
    assert jobs[0]["original_filename"] == "02_梯度消失问题.mp4"


def test_create_job_repairs_mojibake_uploaded_filename(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(main, "OUTPUTS_ROOT", tmp_path)
    monkeypatch.setattr(main, "store", JobStore(tmp_path))
    monkeypatch.setattr(main, "process_transcription_job", lambda **_kwargs: None)

    mojibake_filename = "第二课：经典卷积神经网络.mp4".encode("utf-8").decode("latin1")
    response = TestClient(app).post(
        "/api/jobs",
        data={
            "transcription_mode": "audio_transcriptions",
            "transcription_api_key": "transcription-key",
            "transcription_base_url": "https://api.openai.com/v1",
            "transcription_model": "whisper-1",
            "note_api_key": "note-key",
            "note_base_url": "https://api.openai.com/v1",
            "note_model": "gpt-5.5",
            "note_language": "zh",
            "note_style": "detailed",
            "frame_limit": "6",
        },
        files={"video": (mojibake_filename, b"fake video", "video/mp4")},
    )

    assert response.status_code == 200
    jobs = TestClient(app).get("/api/jobs").json()["jobs"]
    assert jobs[0]["title"] == "第二课：经典卷积神经网络.mp4"
    assert jobs[0]["original_filename"] == "第二课：经典卷积神经网络.mp4"



def _seed_awaiting_job(tmp_path, job_id: str = "awaiting-job") -> Path:
    from backend.app.job_store import JobStore

    outputs_root = tmp_path
    job_dir = outputs_root / job_id
    (job_dir / "source_video").mkdir(parents=True)
    (job_dir / "source_video" / "input.mp4").write_bytes(b"video")
    (job_dir / "transcript.json").write_text(
        '{"text": "hello", "segments": [{"start": 0, "end": 1, "text": "hello"}]}',
        encoding="utf-8",
    )
    (job_dir / "subtitles.md").write_text("00:00:00 - 00:00:01 hello", encoding="utf-8")
    (job_dir / "subtitles.pending").write_text("1", encoding="utf-8")
    (job_dir / "metadata.json").write_text(
        '{"job_id": "awaiting-job", "original_filename": "input.mp4", "duration_seconds": 10}',
        encoding="utf-8",
    )
    store = JobStore(outputs_root)
    store.create(job_id)
    store.update(job_id, status=JobStatus.awaiting_subtitle_confirmation, step="wait", progress=40)
    return job_dir


def test_confirm_subtitles_rejects_non_awaiting_job(tmp_path, monkeypatch) -> None:
    from backend.app import main
    from backend.app.job_store import JobStore

    monkeypatch.setattr(main, "OUTPUTS_ROOT", tmp_path)
    monkeypatch.setattr(main, "store", JobStore(tmp_path))
    job_id = "succeeded-job"
    job_dir = tmp_path / job_id
    job_dir.mkdir(parents=True)
    (job_dir / "note.md").write_text("# note", encoding="utf-8")

    response = TestClient(app).post(
        f"/api/jobs/{job_id}/subtitles/confirm",
        data={
            "note_api_key": "key",
            "note_base_url": "https://api.openai.com/v1",
            "note_model": "gpt-5.5",
            "note_language": "zh",
        },
    )

    assert response.status_code == 404 or response.status_code == 409


def test_confirm_subtitles_requires_note_api_key(tmp_path, monkeypatch) -> None:
    from backend.app import main

    monkeypatch.setattr(main, "OUTPUTS_ROOT", tmp_path)
    monkeypatch.setattr(main, "store", __import__("backend.app.job_store", fromlist=["JobStore"]).JobStore(tmp_path))
    _seed_awaiting_job(tmp_path)

    response = TestClient(app).post(
        "/api/jobs/awaiting-job/subtitles/confirm",
        data={
            "note_api_key": "",
            "note_base_url": "https://api.openai.com/v1",
            "note_model": "gpt-5.5",
            "note_language": "zh",
        },
    )

    assert response.status_code == 400
    assert "Note API Key" in response.json()["detail"]


def test_regenerate_subtitles_rejects_non_awaiting_job(tmp_path, monkeypatch) -> None:
    from backend.app import main
    from backend.app.job_store import JobStore

    monkeypatch.setattr(main, "OUTPUTS_ROOT", tmp_path)
    monkeypatch.setattr(main, "store", JobStore(tmp_path))
    job_id = "done-job"
    job_dir = tmp_path / job_id
    job_dir.mkdir(parents=True)
    (job_dir / "note.md").write_text("# note", encoding="utf-8")

    response = TestClient(app).post(
        f"/api/jobs/{job_id}/subtitles/regenerate",
        data={
            "transcription_mode": "audio_transcriptions",
            "transcription_api_key": "k",
            "transcription_base_url": "https://api.openai.com/v1",
            "transcription_model": "whisper-1",
        },
    )

    assert response.status_code in (404, 409)


def test_regenerate_subtitles_requires_remote_api_key(tmp_path, monkeypatch) -> None:
    from backend.app import main
    from backend.app.job_store import JobStore

    monkeypatch.setattr(main, "OUTPUTS_ROOT", tmp_path)
    monkeypatch.setattr(main, "store", JobStore(tmp_path))
    _seed_awaiting_job(tmp_path)

    response = TestClient(app).post(
        "/api/jobs/awaiting-job/subtitles/regenerate",
        data={
            "transcription_mode": "audio_transcriptions",
            "transcription_api_key": "",
            "transcription_base_url": "https://api.openai.com/v1",
            "transcription_model": "whisper-1",
        },
    )

    assert response.status_code == 400
    assert "Transcription API Key" in response.json()["detail"]
