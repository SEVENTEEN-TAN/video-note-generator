from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_health_loading_and_startup_retries_are_owned_by_a_focused_hook() -> None:
    app_source = (ROOT / "frontend" / "src" / "App.tsx").read_text(encoding="utf-8")
    hook_source = (ROOT / "frontend" / "src" / "useHealthState.ts").read_text(encoding="utf-8")

    assert 'from "./useHealthState"' in app_source
    assert "const { health, refreshHealth } = useHealthState();" in app_source
    assert "useSettings(refreshHealth)" in app_source
    assert "onRefreshHealth: refreshHealth" in app_source

    for legacy_marker in (
        "setHealth(",
        "fetchHealthState(",
        "const retryTimers",
    ):
        assert legacy_marker not in app_source

    assert "const STARTUP_RETRY_DELAYS = [2000, 5000]" in hook_source
    assert "window.setTimeout(" in hook_source
    assert "window.setInterval" not in hook_source
    assert "requestControllerRef.current?.abort()" in hook_source
    assert "requestEpochRef.current" in hook_source
    assert "mountedRef.current" in hook_source
    assert "window.clearTimeout(retryTimer)" in hook_source


def test_health_api_helper_supports_request_cancellation() -> None:
    api_source = (ROOT / "frontend" / "src" / "api.ts").read_text(encoding="utf-8")

    assert "export async function fetchHealthState(signal?: AbortSignal): Promise<HealthState>" in api_source
    assert 'requestJson("/api/health", "运行环境状态读取失败。", { signal })' in api_source
