from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_subtitle_mutations_are_owned_by_a_focused_workflow_hook() -> None:
    app_source = (ROOT / "frontend" / "src" / "App.tsx").read_text(encoding="utf-8")
    hook_source = (ROOT / "frontend" / "src" / "useSubtitleWorkflow.ts").read_text(encoding="utf-8")
    api_source = (ROOT / "frontend" / "src" / "api.ts").read_text(encoding="utf-8")
    types_source = (ROOT / "frontend" / "src" / "types.ts").read_text(encoding="utf-8")

    assert 'from "./useSubtitleWorkflow"' in app_source
    assert "useSubtitleWorkflow({" in app_source
    assert "resetSubtitleWorkflow();" in app_source
    assert "onClose={closeTranscriptCorrection}" in app_source

    for endpoint in (
        "/subtitles/confirm",
        "/subtitles/regenerate",
        "/transcript-corrections",
    ):
        assert endpoint not in app_source
        assert endpoint in api_source

    for local_state_setter in (
        "setCorrectionPreview",
        "setCorrectionError",
        "setIsCorrectingTranscript",
        "setIsApplyingCorrection",
        "setIsConfirmingSubtitles",
        "setIsRegeneratingSubtitles",
        "setSubtitleGateError",
    ):
        assert local_state_setter not in app_source
        assert local_state_setter in hook_source

    assert "activeJobIdRef.current" in hook_source
    assert "operationEpochRef.current" in hook_source
    assert "isCurrentRequest(requestJobId, requestEpoch)" in hook_source
    assert "current?.job_id === jobId" in hook_source
    assert "queued.job_id !== requestJobId" in hook_source
    assert 'markJobQueued(requestJobId, "等待重新生成字幕", 20, false)' in hook_source

    assert 'ApiSchemas["TranscriptCorrectionRequest"]' in types_source
    assert 'ApiSchemas["TranscriptCorrectionApplyRequest"]' in types_source
    assert 'ApiSchemas["Body_confirm_subtitles_api_jobs__job_id__subtitles_confirm_post"]' in types_source
    assert 'ApiSchemas["Body_regenerate_subtitles_api_jobs__job_id__subtitles_regenerate_post"]' in types_source


def test_subtitle_api_helpers_share_readable_error_handling() -> None:
    api_source = (ROOT / "frontend" / "src" / "api.ts").read_text(encoding="utf-8")

    for helper in (
        "export async function confirmSubtitles",
        "export async function regenerateSubtitles",
        "export async function createTranscriptCorrection",
        "export async function applyTranscriptCorrection",
    ):
        assert helper in api_source

    for message in (
        "字幕确认失败，请重试。",
        "重新生成字幕失败，请重试。",
        "字幕修正失败。",
        "采用字幕修正失败。",
    ):
        assert message in api_source

    assert "await readResponseError(response, fallback)" in api_source
