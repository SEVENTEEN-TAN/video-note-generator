from __future__ import annotations

from fastapi.testclient import TestClient

from backend.app import main
from backend.app.main import app
from backend.app.runtime_status import get_external_runtime_status


def test_ready_endpoint_does_not_run_runtime_detection(monkeypatch) -> None:
    monkeypatch.setattr(main, "get_runtime_status", lambda: (_ for _ in ()).throw(RuntimeError("too slow")))
    client = TestClient(app)

    response = client.get("/api/ready")

    assert response.status_code == 200
    assert response.json() == {"ok": True}


def test_external_runtime_status_classifies_worker_process_failure(monkeypatch) -> None:
    def fake_run(*_args, **_kwargs):
        return type(
            "Completed",
            (),
            {"returncode": 1, "stdout": "", "stderr": "worker script could not start"},
        )()

    monkeypatch.setattr("backend.app.runtime_status.subprocess.run", fake_run)

    status = get_external_runtime_status("python.exe", "worker.py")

    assert status["worker_error_code"] == "worker_process_failed"
    assert status["worker_error"] == "worker script could not start"
    assert status["faster_whisper_error"] == ""
    assert status["cuda_error"] == ""
