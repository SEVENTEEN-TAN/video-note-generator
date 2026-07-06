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
    assert 'className="note-title-actions"' in app_text
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
    assert note_action_index < note_preview_index < subtitle_preview_index < frame_block_index
    assert scroll_start < subtitle_preview_index < subtitle_action_index < result_panel_end
    assert scroll_start < frame_block_index < app_text.index('className="frame-grid"', frame_block_index) < result_panel_end
    assert 'filename={job.download_filename ?? `video-note-${job.job_id}.zip`}' in app_text
    for marker in (
        'className="chunk-manager"',
        'className="note-review-gate"',
        'className="preview-stack"',
        'className="frame-grid"',
    ):
        marker_index = app_text.index(marker)
        assert scroll_start < marker_index < result_panel_end, marker


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
