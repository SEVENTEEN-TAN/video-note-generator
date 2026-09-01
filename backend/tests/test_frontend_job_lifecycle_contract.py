from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_primary_job_polling_and_history_are_owned_by_a_focused_hook() -> None:
    app_source = (ROOT / "frontend" / "src" / "App.tsx").read_text(encoding="utf-8")
    hook_source = (ROOT / "frontend" / "src" / "useJobLifecycle.ts").read_text(encoding="utf-8")
    api_source = (ROOT / "frontend" / "src" / "api.ts").read_text(encoding="utf-8")

    assert 'from "./useJobLifecycle"' in app_source
    assert "useJobLifecycle({" in app_source
    assert "resetTaskContextRef.current = resetTaskContext" in app_source
    assert "submitError={submitError || lifecycleError}" in app_source

    for endpoint in (
        "/cancel",
        "/transcription/resume",
    ):
        assert endpoint not in app_source
        assert endpoint in api_source

    for local_state_setter in (
        "setJobHistory",
        "setHistoryError",
        "setIsHistoryLoading",
        "setIsDeletingJobId",
    ):
        assert local_state_setter not in app_source
        assert local_state_setter in hook_source

    assert "fetchJob(jobId, controller.signal)" in hook_source
    assert "window.setTimeout(() => void poll(), 1600)" in hook_source
    assert "window.setInterval" not in hook_source
    assert "controller?.abort()" in hook_source
    assert "loadControllerRef.current?.abort()" in hook_source
    assert "historyRequestRef.current" in hook_source
    assert "mountedRef.current" in hook_source
    assert "current?.job_id === requestJobId" in hook_source
    assert "onResetTaskContextRef.current()" in hook_source
    assert "onClearSelectedInputsRef.current()" in hook_source


def test_job_lifecycle_api_helpers_keep_readable_errors() -> None:
    api_source = (ROOT / "frontend" / "src" / "api.ts").read_text(encoding="utf-8")

    for helper in (
        "export async function fetchJobHistory",
        "export async function cancelJob",
        "export async function resumeJobTranscription",
        "export async function deleteJob",
    ):
        assert helper in api_source

    for message in (
        "历史任务读取失败。",
        "取消任务失败。",
        "继续转写失败。",
        "历史任务删除失败。",
    ):
        assert message in api_source

    assert "encodeURIComponent(jobId)" in api_source
