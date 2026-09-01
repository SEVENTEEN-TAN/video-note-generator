from __future__ import annotations

import base64
import json

from fastapi.testclient import TestClient

from backend.app import settings as settings_module
from backend.app.main import app
from backend.app.secret_storage import SecretProtectionError


class ApiTestSecretProvider:
    name = "api_test_provider"
    available = True

    def protect(self, value: str) -> str:
        if not value:
            return ""
        return base64.b64encode(f"api:{value}".encode()).decode()

    def unprotect(self, value: str) -> str:
        if not value:
            return ""
        try:
            decoded = base64.b64decode(value, validate=True).decode()
        except (ValueError, UnicodeDecodeError) as exc:
            raise SecretProtectionError("invalid test ciphertext") from exc
        if not decoded.startswith("api:"):
            raise SecretProtectionError("invalid test ciphertext")
        return decoded.removeprefix("api:")


def test_settings_api_roundtrip_preserves_language_without_plaintext_keys(tmp_path, monkeypatch) -> None:
    settings_path = tmp_path / "settings.json"
    monkeypatch.setenv("VIDEO_NOTE_SETTINGS_FILE", str(settings_path))
    monkeypatch.setattr(settings_module, "get_secret_provider", lambda: ApiTestSecretProvider())
    client = TestClient(app)

    update = client.patch(
        "/api/settings",
        json={
            "transcription_mode": "audio_transcriptions",
            "transcription_language": "zh",
            "transcription_api_key": "transcription-api-secret",
            "note_api_key": "note-api-secret",
            "note_model": "api-model",
        },
    )
    loaded = client.get("/api/settings")
    payload = json.loads(settings_path.read_text(encoding="utf-8"))
    serialized = settings_path.read_text(encoding="utf-8")

    assert update.status_code == 200
    assert update.json()["transcription_language"] == "zh"
    assert update.json()["note_api_key"] == "note-api-secret"
    assert loaded.status_code == 200
    assert loaded.json()["transcription_language"] == "zh"
    assert loaded.json()["transcription_api_key"] == "transcription-api-secret"
    assert payload["schema_version"] == 2
    assert payload["settings"]["transcription_language"] == "zh"
    assert payload["secrets"]["provider"] == "api_test_provider"
    assert "transcription-api-secret" not in serialized
    assert "note-api-secret" not in serialized


def test_settings_api_reports_generic_decryption_failure_without_overwriting_file(tmp_path, monkeypatch) -> None:
    settings_path = tmp_path / "settings.json"
    monkeypatch.setenv("VIDEO_NOTE_SETTINGS_FILE", str(settings_path))
    monkeypatch.setattr(settings_module, "get_secret_provider", lambda: ApiTestSecretProvider())
    settings_path.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "settings": {"note_model": "saved-model"},
                "secrets": {
                    "provider": "api_test_provider",
                    "transcription_api_key": "",
                    "note_api_key": "broken-ciphertext",
                },
            }
        ),
        encoding="utf-8",
    )
    before = settings_path.read_bytes()
    client = TestClient(app)

    loaded = client.get("/api/settings")
    updated = client.patch("/api/settings", json={"note_model": "new-model"})

    assert loaded.status_code == 500
    assert updated.status_code == 500
    assert "could not be decrypted" in loaded.json()["detail"]
    assert "could not be decrypted" in updated.json()["detail"]
    assert "broken-ciphertext" not in loaded.text
    assert "broken-ciphertext" not in updated.text
    assert settings_path.read_bytes() == before
