from __future__ import annotations

from desktop import desktop_launcher


class FakeResponse:
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, _exc_type, _exc, _traceback):
        return False


def test_desktop_launcher_waits_on_lightweight_ready_endpoint(monkeypatch) -> None:
    requested_urls: list[str] = []

    def fake_urlopen(url: str, timeout: float):
        requested_urls.append(url)
        return FakeResponse()

    monkeypatch.setattr(desktop_launcher.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(desktop_launcher.time, "sleep", lambda _seconds: None)

    desktop_launcher.wait_until_ready("http://127.0.0.1:12345", timeout_seconds=1)

    assert requested_urls == ["http://127.0.0.1:12345/api/ready"]
