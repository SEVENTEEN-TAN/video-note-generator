from __future__ import annotations

import re
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


def _css_rule(selector: str) -> str:
    styles = (REPO_ROOT / "frontend" / "src" / "styles.css").read_text(encoding="utf-8")
    match = re.search(rf"{re.escape(selector)}\s*\{{(?P<body>.*?)\n\}}", styles, re.DOTALL)
    assert match, f"Missing CSS rule for {selector}"
    return re.sub(r"\s+", " ", match.group("body")).strip()


def test_result_panel_uses_compact_review_actions_and_collapsible_outputs() -> None:
    result_scroll_rule = _css_rule(".result-body-scroll")
    step_progress_rule = _css_rule(".step-progress-bar")
    modal_backdrop_rule = _css_rule(".modal-backdrop")
    frame_preview_content_rule = _css_rule(".frame-preview-block .collapsible-content")
    frame_empty_grid_rule = _css_rule(".frame-preview-block .empty-frame-grid")
    frame_empty_state_rule = _css_rule(".frame-preview-block .empty-frames")
    popover_rule = _css_rule(".quality-popover")
    hovered_block_rule = _css_rule(".collapsible-block:hover")
    context_paragraph_rule = _css_rule(".frame-candidate-context p")
    reference_panel_rule = _css_rule(".frame-candidate-reference-panel")
    review_layout_rule = _css_rule(".review-paragraph-layout")
    review_frame_column_rule = _css_rule(".review-frame-column")
    review_frame_list_rule = _css_rule(".review-frame-list")
    review_subtitle_textarea_rule = _css_rule(".review-subtitle-textarea")
    frame_candidate_check_rule = _css_rule(".frame-candidate-check")
    frame_candidate_check_input_rule = _css_rule(".frame-candidate-check input")
    zoom_button_rule = _css_rule(".frame-candidate-zoom")
    image_preview_rule = _css_rule(".frame-image-preview-backdrop")
    image_preview_body_rule = _css_rule(".frame-image-preview-body")
    image_preview_reference_rule = _css_rule(".frame-image-preview-reference")
    styles = (REPO_ROOT / "frontend" / "src" / "styles.css").read_text(encoding="utf-8")
    app_text = (REPO_ROOT / "frontend" / "src" / "App.tsx").read_text(encoding="utf-8")
    result_workbench_text = (REPO_ROOT / "frontend" / "src" / "ResultWorkbench.tsx").read_text(
        encoding="utf-8"
    )
    job_resources_text = (REPO_ROOT / "frontend" / "src" / "useJobResources.ts").read_text(encoding="utf-8")
    review_workflow_text = (REPO_ROOT / "frontend" / "src" / "useReviewWorkflow.ts").read_text(
        encoding="utf-8"
    )
    frame_review_text = (REPO_ROOT / "frontend" / "src" / "FrameReviewModal.tsx").read_text(encoding="utf-8")
    quality_status_text = (REPO_ROOT / "frontend" / "src" / "QualityStatusControl.tsx").read_text(encoding="utf-8")
    runtime_status_text = (REPO_ROOT / "frontend" / "src" / "RuntimeStatus.tsx").read_text(encoding="utf-8")
    settings_modal_text = (REPO_ROOT / "frontend" / "src" / "SettingsModal.tsx").read_text(encoding="utf-8")
    correction_modal_text = (REPO_ROOT / "frontend" / "src" / "TranscriptCorrectionModal.tsx").read_text(
        encoding="utf-8"
    )
    stepper_index = app_text.index('<div className="topbar-stepper">')
    step_progress_index = app_text.index('className="step-progress-bar"')
    result_workbench_index = app_text.index("<ResultWorkbench")
    scroll_start = result_workbench_text.index('<div className="result-body-scroll">')
    result_panel_end = result_workbench_text.index("\n    </section>\n  );", scroll_start)
    note_action_index = result_workbench_text.index("const noteTitleAction")
    note_preview_index = result_workbench_text.index("视频笔记 Markdown")
    subtitle_preview_index = result_workbench_text.index('title="字幕 Markdown"')
    frame_block_index = result_workbench_text.index('title="关键帧"', subtitle_preview_index)
    subtitle_action_index = result_workbench_text.index("确认字幕并生成笔记", subtitle_preview_index)

    assert "overflow: auto" in result_scroll_rule
    assert "height:" in step_progress_rule
    assert "overflow: auto" in frame_preview_content_rule
    assert "max-height:" in frame_preview_content_rule
    assert "display: block" in frame_empty_grid_rule
    assert "padding: 0" in frame_empty_grid_rule
    assert "min-height: auto" in frame_empty_state_rule
    assert "justify-content: flex-start" in frame_empty_state_rule
    assert "z-index: 1000" in popover_rule
    assert "z-index:" in hovered_block_rule
    assert "z-index: 2000" in modal_backdrop_rule
    assert "-webkit-line-clamp" not in context_paragraph_rule
    assert "overflow: auto" in context_paragraph_rule
    assert "overflow-wrap:" in context_paragraph_rule
    assert "padding:" in context_paragraph_rule
    assert "background:" in context_paragraph_rule
    assert "max-height:" in reference_panel_rule
    assert "overflow: hidden" in reference_panel_rule
    assert "grid-template-columns:" in review_layout_rule
    assert "minmax(360px" in review_layout_rule
    assert "minmax(240px" in review_layout_rule
    assert "overflow: auto" in review_frame_column_rule
    assert "grid-template-columns: 1fr" in review_frame_list_rule
    assert "font-size: 12px" in review_subtitle_textarea_rule
    assert "line-height: 1.55" in review_subtitle_textarea_rule
    assert "overflow: auto" in review_subtitle_textarea_rule
    assert "resize: none" in review_subtitle_textarea_rule
    assert "display: flex" in frame_candidate_check_rule
    assert "cursor: pointer" in frame_candidate_check_rule
    assert "position: absolute" in frame_candidate_check_rule
    assert "background: transparent" in frame_candidate_check_rule
    assert "border: 0" in frame_candidate_check_rule
    assert "left:" in frame_candidate_check_rule
    assert "padding: 0" in frame_candidate_check_rule
    assert "top:" in frame_candidate_check_rule
    assert "z-index:" in frame_candidate_check_rule
    assert "accent-color:" in frame_candidate_check_input_rule
    assert "position: absolute" in zoom_button_rule
    assert "right:" in zoom_button_rule
    assert "top:" in zoom_button_rule
    assert "position: fixed" in image_preview_rule
    assert "z-index: 2100" in image_preview_rule
    assert "overflow: auto" in image_preview_body_rule
    assert "grid-template-columns:" in image_preview_reference_rule
    assert stepper_index < step_progress_index < result_workbench_index
    assert ".subtitle-gate" not in styles
    assert 'className="subtitle-gate"' not in app_text
    assert 'className="frame-candidate-panel"' not in app_text
    assert 'className={`quality-panel ${qualityReport.status}`}' not in app_text
    assert ".quality-panel" not in styles
    assert 'className="quality-status-control"' in quality_status_text
    assert 'className="quality-popover"' in quality_status_text
    assert 'from "./RuntimeStatus"' in app_text
    assert "<HealthBadge" in app_text
    assert 'from "./SettingsModal"' in app_text
    assert "<SettingsModal" in app_text
    assert 'className="settings-modal"' not in app_text
    assert 'from "./ResultWorkbench"' in app_text
    assert "<ResultWorkbench" in app_text
    assert 'className={`panel result-panel' not in app_text
    assert 'from "./RuntimeStatus"' in settings_modal_text
    assert "<RuntimeStatusCard" in settings_modal_text
    assert 'className="runtime-card"' in runtime_status_text
    assert "capabilities.uploaded_subtitle" in runtime_status_text
    assert "local_transcription_cuda" in runtime_status_text
    assert 'from "./TranscriptCorrectionModal"' in app_text
    assert "<TranscriptCorrectionModal" in app_text
    assert 'aria-label="AI 字幕修正对比"' in correction_modal_text
    assert "采用修正版并重新生成笔记" in correction_modal_text
    assert 'className="note-title-actions note-title-toolbar"' in result_workbench_text
    assert 'className="small-button manual-review-button"' in result_workbench_text
    assert "手动审核" in frame_review_text
    assert "hasNoteArtifact" in app_text
    assert "findChunkForChapterContext" in frame_review_text
    assert "重新生成本段文字" in frame_review_text
    assert 'from "./useJobResources"' in app_text
    assert "useJobResources(job)" in app_text
    assert "prepareReviewAssets" in job_resources_text
    assert 'from "./useReviewWorkflow"' in app_text
    assert "useReviewWorkflow({" in app_text
    assert "updateReviewDraftParagraph" in review_workflow_text
    assert "reviewDraft" in app_text
    assert "文案编辑" in frame_review_text
    assert "字幕依据" in frame_review_text
    assert "保存本段" in frame_review_text
    assert "onRegenerateNote" in frame_review_text
    assert "chunk ? onRegenerateChunk(chunk.id) : onRegenerateNote()" in frame_review_text
    assert "await prepareReviewAssets(requestedJobId" in job_resources_text
    assert "loadManualReview" in app_text
    assert 'className="frame-candidate-group-actions"' in frame_review_text
    assert 'className="frame-candidate-title-line"' in frame_review_text
    assert "frame-candidate-reference-panel" in frame_review_text
    assert 'className="review-paragraph-layout"' in frame_review_text
    assert 'className="review-frame-column"' in frame_review_text
    assert 'className="frame-candidate-strip review-frame-list"' in frame_review_text
    assert 'className="review-subtitle-textarea"' in frame_review_text
    assert 'className="review-subtitle-list"' not in frame_review_text
    assert "function formatReviewSubtitleEvidence" in frame_review_text
    assert "formatReviewSubtitleEvidence(paragraph.subtitle_segments)" in frame_review_text
    assert "配图" in frame_review_text
    assert 'className="frame-candidate-local-reference"' not in frame_review_text
    assert 'className="frame-image-wrap"' in frame_review_text
    assert 'className="frame-candidate-zoom"' in frame_review_text
    assert 'className="frame-image-preview-backdrop"' in frame_review_text
    assert 'className="frame-image-preview-reference"' in frame_review_text
    assert "previewCandidate.note_excerpt" in frame_review_text
    assert "previewCandidate.subtitle_excerpt" in frame_review_text
    assert "previewCandidate" in frame_review_text
    assert "ZoomIn" in frame_review_text
    assert frame_review_text.index('className="frame-candidate-group-actions"') < frame_review_text.index(
        'className="review-paragraph-layout"'
    )
    assert 'className="frame-candidate-context-head"' not in frame_review_text
    assert ".frame-candidate-context-head" not in styles
    assert "选图时对照本章笔记和字幕原文，避免只看缩略图判断。" not in frame_review_text
    assert 'className="frame-candidate-empty"' in frame_review_text
    assert 'className="frame-candidate-check"' in frame_review_text
    assert 'type="checkbox"' in frame_review_text
    assert "checked={isSelected}" in frame_review_text
    assert "onChange={() => toggleFrame(candidate.id)}" in frame_review_text
    assert frame_review_text.index('className="frame-image-wrap"') < frame_review_text.index(
        'className="frame-candidate-check"'
    )
    assert frame_review_text.index('className="frame-candidate-check"') < frame_review_text.index(
        'className="frame-candidate-zoom"'
    )
    assert '<span>{isSelected ? "已选" : "选用"}</span>' not in frame_review_text
    assert "isSelected ? \"small-button selected\" : \"small-button\"" not in frame_review_text
    assert 'className="frame-review-modal"' in frame_review_text
    assert 'aria-label="段落审稿"' in frame_review_text
    assert "确认定稿并生成 ZIP" not in result_workbench_text
    assert "确认定稿" in result_workbench_text
    assert "function CollapsibleBlock" in result_workbench_text
    assert "collapsible-block" in result_workbench_text
    assert 'className="collapse-toggle"' in result_workbench_text
    assert 'className="frame-preview-block"' in result_workbench_text
    assert '"frame-grid empty-frame-grid"' in result_workbench_text
    assert note_action_index < note_preview_index < subtitle_preview_index < frame_block_index
    assert scroll_start < subtitle_preview_index < subtitle_action_index < result_panel_end
    assert (
        scroll_start
        < frame_block_index
        < result_workbench_text.index('className={previewImages.length === 0', frame_block_index)
        < result_panel_end
    )
    assert 'filename={job.download_filename ?? `video-note-${job.job_id}.zip`}' in result_workbench_text
    for marker in (
        'className="chunk-manager"',
        'className="note-review-gate"',
        'className="preview-stack"',
        'className={previewImages.length === 0',
    ):
        marker_index = result_workbench_text.index(marker)
        assert scroll_start < marker_index < result_panel_end, marker


def test_video_upload_block_overrides_compact_field_grid() -> None:
    topbar_rule = _css_rule(".topbar")
    workspace_rule = _css_rule(".workspace-grid")
    config_main_rule = _css_rule(".task-config-panel .config-main")
    video_config_rule = _css_rule(".task-config-panel .config-main .video-config-block")
    quick_settings_rule = _css_rule(".quick-settings")
    upload_field_rule = _css_rule(".upload-field")
    app_text = (REPO_ROOT / "frontend" / "src" / "App.tsx").read_text(encoding="utf-8")
    task_config_text = (REPO_ROOT / "frontend" / "src" / "TaskConfigPanel.tsx").read_text(encoding="utf-8")

    assert "max-width: none" in topbar_rule
    assert "width: 100%" in topbar_rule
    assert "max-width: none" in workspace_rule
    assert "width: 100%" in workspace_rule
    assert '"video settings extras submit"' in config_main_rule
    assert "minmax(540px" in config_main_rule
    assert "display: grid" in video_config_rule
    assert "grid-template-columns: minmax(0, 1fr) minmax(0, 1fr)" in video_config_rule
    assert "gap: 8px" in quick_settings_rule
    assert "minmax(146px" in quick_settings_rule
    assert "minmax(220px" in quick_settings_rule
    assert "minmax(154px" in quick_settings_rule
    assert "grid-template-columns" not in upload_field_rule
    assert 'from "./TaskConfigPanel"' in app_text
    assert "<TaskConfigPanel" in app_text
    assert '<section className="panel config-panel task-config-panel"' not in app_text
    assert '<span className="field-label">视频文件</span>' not in task_config_text
    assert '<span className="field-label">已有字幕（可选）</span>' not in task_config_text
    assert "视频文件：选择文件" in task_config_text
    assert "已有字幕（可选）：选择 SRT 字幕" in task_config_text


def test_frontend_api_error_messages_are_readable_chinese() -> None:
    api_text = (REPO_ROOT / "frontend" / "src" / "api.ts").read_text(encoding="utf-8")

    for message in (
        "任务状态读取失败。",
        "历史任务读取失败。",
        "下载失败：",
        "笔记版本读取失败。",
        "质量报告读取失败。",
        "配图候选读取失败。",
        "配图候选选择失败。",
        "配图候选拒绝失败。",
        "确认定稿失败。",
    ):
        assert message in api_text

    for mojibake in ("浠", "鍘", "绗", "璐", "閰", "纭", "涓", "澶辫触", "€?"):
        assert mojibake not in api_text


def test_job_resource_loading_cancels_stale_requests_and_uses_artifact_revision() -> None:
    app_text = (REPO_ROOT / "frontend" / "src" / "App.tsx").read_text(encoding="utf-8")
    result_workbench_text = (REPO_ROOT / "frontend" / "src" / "ResultWorkbench.tsx").read_text(
        encoding="utf-8"
    )
    api_text = (REPO_ROOT / "frontend" / "src" / "api.ts").read_text(encoding="utf-8")
    types_text = (REPO_ROOT / "frontend" / "src" / "types.ts").read_text(encoding="utf-8")
    generated_text = (REPO_ROOT / "frontend" / "src" / "api.generated.ts").read_text(encoding="utf-8")
    hook_text = (REPO_ROOT / "frontend" / "src" / "useJobResources.ts").read_text(encoding="utf-8")
    lifecycle_text = (REPO_ROOT / "frontend" / "src" / "useJobLifecycle.ts").read_text(encoding="utf-8")

    assert 'export type JobState = WithRequired<ApiSchemas["JobPublicState"], "artifacts">;' in types_text
    assert "artifact_revision: string" in generated_text
    assert "state_revision: number" in generated_text
    assert "expected_state_revision" in api_text
    assert "expected_artifact_revision" in api_text
    assert "JobRevisionGuard" in api_text
    assert "const artifactRevision = job?.artifact_revision" in hook_text
    assert "job?.updated_at" not in hook_text
    assert "new AbortController()" in hook_text
    assert "controller.abort()" in hook_text
    assert "manualReviewControllerRef.current?.abort()" in hook_text
    assert "activeJobIdRef.current" in hook_text
    assert "fetchNotePreview" in hook_text
    assert "fetchSubtitlePreview" in hook_text
    assert "fetchNoteChunks" in hook_text
    assert "prepareReviewAssets" in hook_text
    assert "fetchJob(jobId, controller.signal)" in lifecycle_text
    assert "window.setTimeout(() => void poll(), 1600)" in lifecycle_text
    assert "window.setInterval(async" not in app_text
    assert "updateNoteVersionSelection" in api_text
    assert "isSwitchingVersion" in app_text
    assert 'label="诊断包"' in result_workbench_text
    assert "/diagnostics.zip" in result_workbench_text


def test_frame_review_exposes_scene_stability_contract() -> None:
    generated_text = (REPO_ROOT / "frontend" / "src" / "api.generated.ts").read_text(encoding="utf-8")
    modal_text = (REPO_ROOT / "frontend" / "src" / "FrameReviewModal.tsx").read_text(encoding="utf-8")

    assert "anchor_time?: number | null" in generated_text
    assert "time_offset: number" in generated_text
    assert "stability_score: number" in generated_text
    assert "transition_score: number" in generated_text
    assert "scene_sample_count: number" in generated_text
    assert "稳定" in modal_text
    assert "锚点" in modal_text
    assert "transition_frame" in modal_text


def test_workbench_and_cancellation_states_work_across_viewport_sizes() -> None:
    app_text = (REPO_ROOT / "frontend" / "src" / "App.tsx").read_text(encoding="utf-8")
    note_workflow_text = (REPO_ROOT / "frontend" / "src" / "useNoteWorkflow.ts").read_text(encoding="utf-8")
    runtime_tasks_text = (REPO_ROOT / "frontend" / "src" / "useRuntimeTasks.ts").read_text(encoding="utf-8")
    constants_text = (REPO_ROOT / "frontend" / "src" / "constants.ts").read_text(encoding="utf-8")
    generated_text = (REPO_ROOT / "frontend" / "src" / "api.generated.ts").read_text(encoding="utf-8")
    navigation_text = (REPO_ROOT / "frontend" / "src" / "WorkbenchNavigation.tsx").read_text(encoding="utf-8")
    styles = (REPO_ROOT / "frontend" / "src" / "styles.css").read_text(encoding="utf-8")

    assert 'cancelling: "正在取消"' in constants_text
    assert '"cancelling"' in generated_text
    assert 'job?.status === "cancelling"' in app_text
    assert 'status: "pending"' in runtime_tasks_text
    assert 'stage: "queued"' in note_workflow_text
    assert 'tabIndex={active === tab.id ? 0 : -1}' in navigation_text
    assert 'event.key === "ArrowRight"' in navigation_text
    assert "/* Workbench behavior is shared by desktop and narrow browser layouts. */" in styles
    assert ".badge.cancelling" in styles
    assert ".badge.cancelled" in styles
    assert ".workbench-files .result-body-scroll" in styles


def test_note_review_gate_keeps_its_height_above_the_scrollable_preview() -> None:
    styles = (REPO_ROOT / "frontend" / "src" / "styles.css").read_text(encoding="utf-8")

    assert re.search(
        r"\.workbench-note \.result-body-scroll\s*\{[^}]*display:\s*flex;[^}]*flex-direction:\s*column;[^}]*overflow:\s*hidden;",
        styles,
        re.DOTALL,
    )
    assert re.search(r"\.workbench-note \.note-review-gate\s*\{[^}]*flex:\s*0 0 auto;", styles, re.DOTALL)
    assert re.search(
        r"\.workbench-note \.preview-stack\s*\{[^}]*flex:\s*1 1 auto;[^}]*height:\s*auto;[^}]*min-height:\s*0;",
        styles,
        re.DOTALL,
    )
