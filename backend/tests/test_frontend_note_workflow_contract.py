from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_note_mutations_are_owned_by_a_focused_workflow_hook() -> None:
    app_source = (ROOT / "frontend" / "src" / "App.tsx").read_text(encoding="utf-8")
    hook_source = (ROOT / "frontend" / "src" / "useNoteWorkflow.ts").read_text(encoding="utf-8")
    api_source = (ROOT / "frontend" / "src" / "api.ts").read_text(encoding="utf-8")
    types_source = (ROOT / "frontend" / "src" / "types.ts").read_text(encoding="utf-8")

    assert 'from "./useNoteWorkflow"' in app_source
    assert "useNoteWorkflow({" in app_source
    assert "resetNoteWorkflow();" in app_source

    for endpoint in (
        "/note-versions",
        "/note-chunks/${encodeURIComponent(chunkId)}/regenerate",
        "/finalize",
    ):
        assert endpoint not in app_source
        assert endpoint in api_source

    for local_state_setter in (
        "setVersionError",
        "setIsRegenerating",
        "setRegeneratingChunkId",
        "setIsFinalizingJob",
        "setIsSwitchingVersion",
        "setFinalizeError",
    ):
        assert local_state_setter not in app_source
        assert local_state_setter in hook_source

    assert "activeJobIdRef.current" in hook_source
    assert "operationEpochRef.current" in hook_source
    assert "versionSwitchRequestRef.current" in hook_source
    assert "versionSwitchControllerRef.current?.abort()" in hook_source
    assert "isCurrentRequest(requestedJobId, requestEpoch)" in hook_source
    assert "current?.job_id === requestJobId" in hook_source
    assert "queued.job_id !== requestJobId" in hook_source
    assert 'job?.status === "awaiting_note_review"' in hook_source
    assert "setIsRegenerating(false);" in hook_source
    assert 'markJobQueued(requestJobId, "等待重新生成笔记块", 70, false)' in hook_source

    assert 'ApiSchemas["Body_regenerate_note_version_endpoint_api_jobs__job_id__note_versions_post"]' in types_source
    assert (
        'ApiSchemas["Body_regenerate_note_chunk_api_jobs__job_id__note_chunks__chunk_id__regenerate_post"]'
        in types_source
    )


def test_note_api_helpers_keep_revision_guards_and_readable_errors() -> None:
    api_source = (ROOT / "frontend" / "src" / "api.ts").read_text(encoding="utf-8")
    hook_source = (ROOT / "frontend" / "src" / "useNoteWorkflow.ts").read_text(encoding="utf-8")

    for helper in (
        "export async function updateNoteVersionSelection",
        "export async function regenerateNoteVersion",
        "export async function regenerateNoteChunk",
        "export async function finalizeJob",
    ):
        assert helper in api_source

    for message in (
        "笔记版本切换失败。",
        "重新生成笔记失败。",
        "重新生成笔记块失败。",
        "确认定稿失败。",
    ):
        assert message in api_source

    assert "expected_artifact_revision" in api_source
    assert "expected_state_revision" in api_source
    assert "updateNoteVersionSelection(" in hook_source
    assert "finalizeJob(requestJobId, job" in hook_source
