from __future__ import annotations

import re
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


def _css_rule(selector: str) -> str:
    styles = (REPO_ROOT / "frontend" / "src" / "styles.css").read_text(encoding="utf-8")
    match = re.search(rf"{re.escape(selector)}\s*\{{(?P<body>.*?)\n\}}", styles, re.DOTALL)
    assert match, f"Missing CSS rule for {selector}"
    return re.sub(r"\s+", " ", match.group("body")).strip()


def test_result_panel_uses_review_flow_layout_without_nested_candidate_panel() -> None:
    result_scroll_rule = _css_rule(".result-body-scroll")
    step_progress_rule = _css_rule(".step-progress-bar")
    app_text = (REPO_ROOT / "frontend" / "src" / "App.tsx").read_text(encoding="utf-8")
    stepper_index = app_text.index('<div className="topbar-stepper">')
    step_progress_index = app_text.index('className="step-progress-bar"')
    scroll_start = app_text.index('<div className="result-body-scroll">')
    result_panel_end = app_text.index("          </section>\n        </div>\n      </form>", scroll_start)
    subtitle_preview_index = app_text.index('title="字幕 Markdown"')
    subtitle_action_index = app_text.index("确认字幕并生成笔记", subtitle_preview_index)

    assert "overflow: auto" in result_scroll_rule
    assert "height:" in step_progress_rule
    assert stepper_index < step_progress_index < scroll_start
    assert ".subtitle-gate" not in (REPO_ROOT / "frontend" / "src" / "styles.css").read_text(encoding="utf-8")
    assert 'className="subtitle-gate"' not in app_text
    assert 'className="frame-candidate-panel"' not in app_text
    assert 'className="frame-review-modal"' in app_text
    assert "审核配图" in app_text
    assert "原始段落参考" in app_text
    assert "笔记原段落" in app_text
    assert "字幕原文片段" in app_text
    assert "确认定稿并生成 ZIP" not in app_text
    assert "确认定稿" in app_text
    assert scroll_start < subtitle_preview_index < subtitle_action_index < result_panel_end
    assert 'filename={job.download_filename ?? `video-note-${job.job_id}.zip`}' in app_text
    for marker in (
        'className="chunk-manager"',
        "quality-panel",
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
