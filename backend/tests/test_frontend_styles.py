from __future__ import annotations

import re
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


def _css_rule(selector: str) -> str:
    styles = (REPO_ROOT / "frontend" / "src" / "styles.css").read_text(encoding="utf-8")
    match = re.search(rf"{re.escape(selector)}\s*\{{(?P<body>.*?)\n\}}", styles, re.DOTALL)
    assert match, f"Missing CSS rule for {selector}"
    return re.sub(r"\s+", " ", match.group("body")).strip()


def test_result_panel_uses_single_scroll_region_for_review_and_preview() -> None:
    result_scroll_rule = _css_rule(".result-body-scroll")
    frame_groups_rule = _css_rule(".frame-candidate-groups")
    app_text = (REPO_ROOT / "frontend" / "src" / "App.tsx").read_text(encoding="utf-8")
    scroll_start = app_text.index('<div className="result-body-scroll">')
    result_panel_end = app_text.index("          </section>\n        </div>\n      </form>", scroll_start)

    assert "overflow: auto" in result_scroll_rule
    assert "max-height:" not in frame_groups_rule
    assert "overflow-y:" not in frame_groups_rule
    for marker in (
        'className="chunk-manager"',
        'className="subtitle-gate"',
        "quality-panel",
        'className="frame-candidate-panel"',
        'className="note-review-gate"',
        'className="preview-stack"',
        'className="frame-grid"',
    ):
        marker_index = app_text.index(marker)
        assert scroll_start < marker_index < result_panel_end, marker
