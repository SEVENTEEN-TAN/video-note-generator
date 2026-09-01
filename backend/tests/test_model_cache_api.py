from fastapi.testclient import TestClient

from backend.app.api import runtime as runtime_routes
from backend.app.main import app


def test_model_cache_clear_endpoint_reports_released_models(monkeypatch) -> None:
    monkeypatch.setattr(runtime_routes, "clear_internal_whisper_model_cache", lambda: 2)

    response = TestClient(app).post("/api/runtime/faster-whisper/cache/clear")

    assert response.status_code == 200
    assert response.json() == {"cleared_models": 2}
