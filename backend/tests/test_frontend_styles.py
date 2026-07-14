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
    stepper_index = app_text.index('<div className="topbar-stepper">')
    step_progress_index = app_text.index('className="step-progress-bar"')
    scroll_start = app_text.index('<div className="result-body-scroll">')
    result_panel_end = app_text.index("          </section>\n        </div>\n      </form>", scroll_start)
    note_action_index = app_text.index("const noteTitleAction")
    note_preview_index = app_text.index("视频笔记 Markdown")
    subtitle_preview_index = app_text.index('title="字幕 Markdown"')
    frame_block_index = app_text.index('title="关键帧"', subtitle_preview_index)
    subtitle_action_index = app_text.index("确认字幕并生成笔记", subtitle_preview_index)

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
    assert stepper_index < step_progress_index < scroll_start
    assert ".subtitle-gate" not in styles
    assert 'className="subtitle-gate"' not in app_text
    assert 'className="frame-candidate-panel"' not in app_text
    assert 'className={`quality-panel ${qualityReport.status}`}' not in app_text
    assert ".quality-panel" not in styles
    assert 'className="quality-status-control"' in app_text
    assert 'className="quality-popover"' in app_text
    assert 'className="note-title-actions note-title-toolbar"' in app_text
    assert 'className="small-button manual-review-button"' in app_text
    assert "手动审核" in app_text
    assert "hasNoteArtifact" in app_text
    assert "findChunkForChapterContext" in app_text
    assert "重新生成本段文字" in app_text
    assert "fetchReviewDraft" in app_text
    assert "updateReviewDraftParagraph" in app_text
    assert "reviewDraft" in app_text
    assert "文案编辑" in app_text
    assert "字幕依据" in app_text
    assert "保存本段" in app_text
    assert "onRegenerateNote" in app_text
    assert "chunk ? onRegenerateChunk(chunk.id) : onRegenerateNote()" in app_text
    assert "Promise.all" in app_text
    assert "fetchFrameCandidates(job.job_id)" in app_text
    assert 'className="frame-candidate-group-actions"' in app_text
    assert 'className="frame-candidate-title-line"' in app_text
    assert "frame-candidate-reference-panel" in app_text
    assert 'className="review-paragraph-layout"' in app_text
    assert 'className="review-frame-column"' in app_text
    assert 'className="frame-candidate-strip review-frame-list"' in app_text
    assert 'className="review-subtitle-textarea"' in app_text
    assert 'className="review-subtitle-list"' not in app_text
    assert "function formatReviewSubtitleEvidence" in app_text
    assert "formatReviewSubtitleEvidence(paragraph.subtitle_segments)" in app_text
    assert "配图" in app_text
    assert 'className="frame-candidate-local-reference"' not in app_text
    assert 'className="frame-image-wrap"' in app_text
    assert 'className="frame-candidate-zoom"' in app_text
    assert 'className="frame-image-preview-backdrop"' in app_text
    assert 'className="frame-image-preview-reference"' in app_text
    assert "previewCandidate.note_excerpt" in app_text
    assert "previewCandidate.subtitle_excerpt" in app_text
    assert "previewCandidate" in app_text
    assert "ZoomIn" in app_text
    assert app_text.index('className="frame-candidate-group-actions"') < app_text.index('className="review-paragraph-layout"')
    assert 'className="frame-candidate-context-head"' not in app_text
    assert ".frame-candidate-context-head" not in styles
    assert "选图时对照本章笔记和字幕原文，避免只看缩略图判断。" not in app_text
    assert 'className="frame-candidate-empty"' in app_text
    assert 'className="frame-candidate-check"' in app_text
    assert 'type="checkbox"' in app_text
    assert "checked={isSelected}" in app_text
    assert "onChange={() => toggleFrame(candidate.id)}" in app_text
    assert app_text.index('className="frame-image-wrap"') < app_text.index('className="frame-candidate-check"')
    assert app_text.index('className="frame-candidate-check"') < app_text.index('className="frame-candidate-zoom"')
    assert '<span>{isSelected ? "已选" : "选用"}</span>' not in app_text
    assert "isSelected ? \"small-button selected\" : \"small-button\"" not in app_text
    assert 'className="frame-review-modal"' in app_text
    assert 'aria-label="段落审稿"' in app_text
    assert "确认定稿并生成 ZIP" not in app_text
    assert "确认定稿" in app_text
    assert "function CollapsibleBlock" in app_text
    assert "collapsible-block" in app_text
    assert 'className="collapse-toggle"' in app_text
    assert 'className="frame-preview-block"' in app_text
    assert '"frame-grid empty-frame-grid"' in app_text
    assert note_action_index < note_preview_index < subtitle_preview_index < frame_block_index
    assert scroll_start < subtitle_preview_index < subtitle_action_index < result_panel_end
    assert scroll_start < frame_block_index < app_text.index('className={previewImages.length === 0', frame_block_index) < result_panel_end
    assert 'filename={job.download_filename ?? `video-note-${job.job_id}.zip`}' in app_text
    for marker in (
        'className="chunk-manager"',
        'className="note-review-gate"',
        'className="preview-stack"',
        'className={previewImages.length === 0',
    ):
        marker_index = app_text.index(marker)
        assert scroll_start < marker_index < result_panel_end, marker


def test_video_upload_block_overrides_compact_field_grid() -> None:
    topbar_rule = _css_rule(".topbar")
    workspace_rule = _css_rule(".workspace-grid")
    config_main_rule = _css_rule(".task-config-panel .config-main")
    video_config_rule = _css_rule(".task-config-panel .config-main .video-config-block")
    quick_settings_rule = _css_rule(".quick-settings")
    upload_field_rule = _css_rule(".upload-field")
    app_text = (REPO_ROOT / "frontend" / "src" / "App.tsx").read_text(encoding="utf-8")

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
    assert '<span className="field-label">视频文件</span>' not in app_text
    assert '<span className="field-label">已有字幕（可选）</span>' not in app_text
    assert "视频文件：选择文件" in app_text
    assert "已有字幕（可选）：选择 SRT 字幕" in app_text


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


def test_workbench_and_cancellation_states_work_across_viewport_sizes() -> None:
    app_text = (REPO_ROOT / "frontend" / "src" / "App.tsx").read_text(encoding="utf-8")
    constants_text = (REPO_ROOT / "frontend" / "src" / "constants.ts").read_text(encoding="utf-8")
    types_text = (REPO_ROOT / "frontend" / "src" / "types.ts").read_text(encoding="utf-8")
    navigation_text = (REPO_ROOT / "frontend" / "src" / "WorkbenchNavigation.tsx").read_text(encoding="utf-8")
    styles = (REPO_ROOT / "frontend" / "src" / "styles.css").read_text(encoding="utf-8")

    assert 'cancelling: "正在取消"' in constants_text
    assert '"cancelling"' in types_text
    assert 'job?.status === "cancelling"' in app_text
    assert 'status: "pending"' in app_text
    assert 'stage: "queued"' in app_text
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
