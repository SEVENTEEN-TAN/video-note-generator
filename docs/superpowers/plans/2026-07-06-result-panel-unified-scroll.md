# Result Panel Unified Scroll Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the result panel use one shared vertical scroll region for review controls, frame candidates, previews, and final key frames.

**Architecture:** Keep the result panel title and download/version toolbar outside the scroll area. Move all variable result content into `result-body-scroll`, and remove the frame-candidate nested height guess. Add regression tests that encode both the structural and CSS layout contract.

**Tech Stack:** React TSX, CSS, pytest text-based regression checks, Vite build.

---

## File Structure

- Modify `backend/tests/test_frontend_styles.py`
  - Update the regression test from nested frame-candidate scrolling to unified result-panel scrolling.
- Modify `frontend/src/App.tsx`
  - Move variable result JSX into the existing `result-body-scroll` container.
- Modify `frontend/src/styles.css`
  - Remove `.frame-candidate-groups` guessed `max-height` and `overflow-y`.
  - Ensure `.result-panel` and `.result-body-scroll` keep the panel title/toolbar fixed while the body scrolls.

---

### Task 1: Add Unified Scroll Regression Test

**Files:**
- Modify: `backend/tests/test_frontend_styles.py`

- [ ] **Step 1: Replace the old nested-scroll test**

Replace:

```python
def test_frame_candidate_groups_scroll_inside_result_panel() -> None:
    rule = _css_rule(".frame-candidate-groups")

    assert "max-height:" in rule
    assert "overflow-y: auto" in rule
```

with:

```python
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
```

- [ ] **Step 2: Run the test and verify RED**

Run:

```bash
pytest backend/tests/test_frontend_styles.py -q
```

Expected: FAIL because `frame-candidate-groups` still has `max-height` and review panels are still outside `result-body-scroll`.

- [ ] **Step 3: Commit the failing test is not allowed**

Do not commit yet. Continue to Task 2.

---

### Task 2: Move Variable Result Content Into One Scroll Container

**Files:**
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/styles.css`

- [ ] **Step 1: Move the JSX scroll boundary**

In `frontend/src/App.tsx`:

1. Keep the panel title row and `download-row` as direct children of `result-panel`.
2. Move the `chunk-manager` block from above `download-row` to immediately after the opening `result-body-scroll`.
3. Move the opening `<div className="result-body-scroll">` from just before `preview-stack` to immediately after `download-row`.
4. Keep all variable blocks between that opening and the existing closing `</div>` after `frame-grid`.

The resulting skeleton should be:

```tsx
<section className="panel result-panel" aria-label="结果预览">
  <div className="panel-title result-panel-title">...</div>
  <div className="download-row">...</div>
  <div className="result-body-scroll">
    {noteChunks && noteChunks.chunks.length > 1 && (
      <details className="chunk-manager" aria-label="笔记分段管理">...</details>
    )}
    {job?.status === "awaiting_subtitle_confirmation" && (...)}
    {qualityReport && (...)}
    {qualityReportError && (...)}
    {frameCandidateIndex && frameCandidateIndex.candidates.length > 0 && job && (...)}
    {frameCandidateError && (...)}
    {job?.status === "awaiting_note_review" && (...)}
    {finalizeError && (...)}
    {job && (job.status === "running" || job.status === "pending") && (...)}
    {downloadMessage && (...)}
    {versionError && (...)}
    {correctionError && !correctionPreview && (...)}
    <div className="preview-stack">...</div>
    <div className="frame-grid" aria-label="关键帧">...</div>
  </div>
</section>
```

- [ ] **Step 2: Remove nested frame candidate scrolling**

In `frontend/src/styles.css`, update `.frame-candidate-groups` from:

```css
.frame-candidate-groups {
  display: grid;
  gap: 12px;
  margin-top: 12px;
  max-height: min(520px, 42vh);
  overflow-y: auto;
  padding-right: 4px;
}
```

to:

```css
.frame-candidate-groups {
  display: grid;
  gap: 12px;
  margin-top: 12px;
}
```

- [ ] **Step 3: Ensure the result panel is a vertical flex layout**

In `frontend/src/styles.css`, ensure `.result-panel` has:

```css
.result-panel {
  display: flex;
  flex-direction: column;
  gap: 12px;
}
```

Keep existing height behavior and mobile overrides intact.

- [ ] **Step 4: Run the regression test and verify GREEN**

Run:

```bash
pytest backend/tests/test_frontend_styles.py -q
```

Expected: PASS.

- [ ] **Step 5: Run frontend build**

Run:

```bash
npm --prefix frontend run build
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/App.tsx frontend/src/styles.css backend/tests/test_frontend_styles.py
git commit -m "fix: use unified result panel scrolling"
```

---

### Task 3: Final Verification

**Files:**
- No new code files.

- [ ] **Step 1: Run focused regression**

Run:

```bash
pytest backend/tests/test_frontend_styles.py -q
```

Expected: PASS.

- [ ] **Step 2: Run full backend suite**

Run:

```bash
pytest backend/tests -q
```

Expected: PASS.

- [ ] **Step 3: Run frontend build**

Run:

```bash
npm --prefix frontend run build
```

Expected: PASS.

- [ ] **Step 4: Inspect git status**

Run:

```bash
git status --short --branch
```

Expected: clean branch.

---

## Self-Review Against Spec

- Frame candidates are reachable through normal vertical scrolling: Task 2.
- No guessed candidate-list height: Task 2 and regression test.
- No nested review-content scroll: Task 1 and Task 2.
- Existing controls and behaviors stay intact: Task 2 moves JSX without changing handlers or API calls.
- Mobile layout remains governed by existing media rules: Task 2 keeps mobile overrides intact.
