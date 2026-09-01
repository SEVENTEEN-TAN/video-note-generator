from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_review_preparation_and_saving_are_owned_by_a_focused_hook() -> None:
    app_source = (ROOT / "frontend" / "src" / "App.tsx").read_text(encoding="utf-8")
    hook_source = (ROOT / "frontend" / "src" / "useReviewWorkflow.ts").read_text(encoding="utf-8")
    resources_source = (ROOT / "frontend" / "src" / "useJobResources.ts").read_text(encoding="utf-8")
    api_source = (ROOT / "frontend" / "src" / "api.ts").read_text(encoding="utf-8")

    assert 'from "./useReviewWorkflow"' in app_source
    assert "useReviewWorkflow({" in app_source
    assert "resetReviewWorkflow();" in app_source
    assert "onOpenReview: openFrameReview" in app_source
    assert "onClose={closeFrameReview}" in app_source

    for local_state_setter in ("setReviewDraftSavingId", "setIsFrameReviewOpen"):
        assert local_state_setter not in app_source
        assert local_state_setter in hook_source

    assert "loadManualReview(previewVersionId || undefined)" in hook_source
    assert "updateReviewDraftParagraph(" in hook_source
    assert "await refreshQualityReport();" in hook_source
    assert "activeJobIdRef.current" in hook_source
    assert "operationEpochRef.current" in hook_source
    assert "isCurrentRequest(requestJobId, requestEpoch)" in hook_source
    assert "current?.job_id === requestJobId" in hook_source
    assert "prepareReviewAssets" in resources_source
    assert "expected_artifact_revision" in api_source
    assert "expected_state_revision" in api_source


def test_review_hook_preserves_editable_state_when_conflict_refresh_fails() -> None:
    hook_source = (ROOT / "frontend" / "src" / "useReviewWorkflow.ts").read_text(encoding="utf-8")

    assert "人工审核稿保存失败。" in hook_source
    assert "Keep the editable local paragraph intact" in hook_source
    assert "setReviewDraft(updatedDraft);" in hook_source
    assert "setFrameCandidateError(\"\");" in hook_source
