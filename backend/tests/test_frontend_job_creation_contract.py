from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_job_creation_is_owned_by_a_focused_hook() -> None:
    app_source = (ROOT / "frontend" / "src" / "App.tsx").read_text(encoding="utf-8")
    hook_source = (ROOT / "frontend" / "src" / "useJobCreation.ts").read_text(encoding="utf-8")
    api_source = (ROOT / "frontend" / "src" / "api.ts").read_text(encoding="utf-8")

    assert 'from "./useJobCreation"' in app_source
    assert "useJobCreation({" in app_source
    assert "clearSelectedInputsRef.current = clearSelectedInputs" in app_source
    assert "submitError={submitError || lifecycleError}" in app_source

    for legacy_marker in (
        "setVideo(",
        "setSubtitle(",
        "setSubmitError(",
        "setIsSubmitting(",
        "new FormData()",
    ):
        assert legacy_marker not in app_source
        assert legacy_marker in hook_source or legacy_marker in api_source

    assert 'fetch("/api/jobs"' not in app_source
    assert 'requestJson("/api/jobs"' in api_source

    assert 'formData.append("video", video)' in hook_source
    assert 'formData.append("performance_mode", currentSettings.performance_mode)' in hook_source
    assert 'formData.append("note_language", currentSettings.note_language)' in hook_source
    assert "submissionEpochRef.current" in hook_source
    assert "mountedRef.current" in hook_source
    assert "optionsRef.current" in hook_source
    assert "options.onResetTaskContext();" in hook_source
    assert "await options.onRefreshJobHistory();" in hook_source


def test_job_creation_api_helper_keeps_a_readable_error() -> None:
    api_source = (ROOT / "frontend" / "src" / "api.ts").read_text(encoding="utf-8")

    assert "export async function createJob(formData: FormData)" in api_source
    assert 'requestJson("/api/jobs", "任务创建失败。"' in api_source
