from __future__ import annotations

from fastapi.testclient import TestClient

from backend.app import model_downloads
from backend.app.main import app


def write_model_files(model_dir) -> None:
    model_dir.mkdir(parents=True)
    for name in ("config.json", "model.bin", "tokenizer.json", "vocabulary.txt"):
        (model_dir / name).write_text("x", encoding="utf-8")


def test_start_model_download_marks_existing_model_succeeded(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("FASTER_WHISPER_MODEL_DIR", str(tmp_path / "models"))
    write_model_files(tmp_path / "models" / "medium")
    model_downloads.clear_model_download_states()

    state = model_downloads.start_model_download("medium")

    assert state.status == "succeeded"
    assert state.progress == 100
    assert state.error == ""


def test_run_model_download_records_success_and_refreshes_model(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("FASTER_WHISPER_MODEL_DIR", str(tmp_path / "models"))
    model_downloads.clear_model_download_states()

    def fake_download(model_name, model_root):
        write_model_files(model_root / model_name)

    monkeypatch.setattr(model_downloads, "download_faster_whisper_model", fake_download)

    state = model_downloads.start_model_download("medium")
    model_downloads.run_model_download("medium")

    finished = model_downloads.get_model_download_state("medium")
    assert state.status == "pending"
    assert finished.status == "succeeded"
    assert finished.progress == 100
    assert (tmp_path / "models" / "medium" / "model.bin").exists()


def test_model_download_api_rejects_invalid_model_name() -> None:
    client = TestClient(app)

    response = client.post("/api/models/faster-whisper/download", json={"model_name": "../secret"})

    assert response.status_code == 422
