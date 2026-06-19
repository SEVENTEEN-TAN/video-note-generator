from __future__ import annotations

from fastapi.testclient import TestClient

from backend.app.main import app


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
