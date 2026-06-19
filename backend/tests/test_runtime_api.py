from __future__ import annotations

from fastapi.testclient import TestClient

from backend.app import main
from backend.app.main import app


def test_ready_endpoint_does_not_run_runtime_detection(monkeypatch) -> None:
    monkeypatch.setattr(main, "get_runtime_status", lambda: (_ for _ in ()).throw(RuntimeError("too slow")))
    client = TestClient(app)

    response = client.get("/api/ready")

    assert response.status_code == 200
    assert response.json() == {"ok": True}
