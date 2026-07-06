# Result Panel Unified Scroll Design

## Summary

The current result panel splits review content and preview content into different scroll behaviors. The panel itself has a fixed desktop height and hides overflow, while only the lower preview section owns a scroll container. Quality review, frame candidates, finalize controls, warnings, and chunk controls sit outside that scroll area. When frame candidates grow taller than the remaining panel height, the UI either clips them or requires brittle nested scrolling with guessed `max-height` values.

The selected design is option A from the visual companion: keep the result panel header and primary toolbar stable, then place all variable result content into one shared vertical scroll container.

## Goals

- Make frame candidates reliably reachable by normal vertical scrolling.
- Remove the need to estimate a candidate-list height such as `42vh`.
- Avoid nested scroll areas for review content.
- Preserve the existing visual language: compact, operational, review-oriented.
- Keep current controls and behavior intact: downloads, version selection, note regeneration, subtitle confirmation, quality review, candidate select/reject, finalize, previews, and key frames.

## Non-Goals

- No tabs in this fix.
- No split-pane review/preview redesign.
- No changes to backend review artifacts or candidate selection behavior.
- No new product states.
- No visual restyling beyond layout containment.

## Layout

The result panel should be structured as:

1. Fixed panel title row.
2. Fixed toolbar row for downloads, version selection, and note regeneration.
3. One `result-body-scroll` container that contains all variable content:
   - note chunk manager
   - subtitle confirmation gate
   - quality report panel
   - frame candidate panel
   - note review finalize gate
   - inline errors/warnings/progress
   - markdown and subtitle preview blocks
   - final key-frame preview grid

The scroll container should own the vertical overflow. Child review panels should size naturally and must not carry independent guessed vertical max heights.

## Interaction

- Users scroll the right result panel once to move through review controls and previews.
- Frame candidate groups remain fully expanded in document flow.
- Candidate cards keep their existing select/reject buttons.
- The finalize button stays below review content in the same scroll flow, so users naturally encounter it after checking quality and frame choices.
- On narrow/mobile layouts, the existing full-page scroll behavior remains acceptable; the right panel can continue to relax fixed heights at mobile breakpoints.

## Implementation Notes

- Move the variable result JSX currently above `result-body-scroll` into that container.
- Keep the result title and download/version toolbar outside `result-body-scroll`.
- Remove the previous nested scroll rules from `.frame-candidate-groups`.
- Update the CSS regression test so it asserts the unified scroll model:
  - `.result-body-scroll` has `overflow: auto`.
  - `.frame-candidate-groups` does not set a guessed `max-height`.

## Testing

- Update the CSS regression test to encode the unified scroll contract.
- Run the frontend production build.
- Run backend tests because the existing regression test lives in the backend test suite.

## Open Questions

None. The user selected option A in the visual companion.
