# Review Flow UI Design

## Goal

Make the video note generator feel like one coherent review workflow: progress belongs to the top stepper, subtitle decisions live next to the subtitle preview, frame candidate review opens as a focused secondary surface, finalization means producing the final draft, and downloads use the article title.

## Product Principles

- Keep the main result panel clean. Inline content should be note preview, subtitle preview, quality warnings, and the final review action.
- Put decisions at the evidence. Subtitle regeneration/confirmation belongs in the subtitle preview header. Frame choices need their own review surface because they require comparison.
- Preserve user work. AI-generated versions, manually edited legacy notes, and final reviewed output must not be confused or silently overwritten.
- Make packaging secondary. ZIP is a downloadable artifact, not the purpose of finalization.

## UI Design

### Top Progress

The current running progress bar moves out of the result preview body and into the stepper area. It sits below the five numbered steps as a slim stage progress rail with the current step label, percentage, and elapsed time. This keeps progress visually tied to the process instead of appearing as another result block.

### Subtitle Review

When a job is waiting for subtitle confirmation, the subtitle preview header shows the actions directly:

- `重新生成字幕`
- `确认字幕并生成笔记`

The standalone subtitle gate block is removed. The user can read the subtitles and act from the same header area.

### Frame Candidate Review

The main result panel shows a compact button in the review gate row:

- `审核配图 · N 已选`

Clicking it opens a modal. The modal shows grouped candidates by chapter, but each group includes enough context:

- chapter title
- time range
- note excerpt
- subtitle excerpt
- selected count for that chapter

This prevents the current “第 1 章” ambiguity.

### Multi-Image Selection

Frame candidate selection changes from one selected image per chapter to multiple selected images per chapter, constrained by the job frame limit.

Default behavior stays conservative: one non-duplicate candidate per chapter is selected automatically. The user can select additional candidates for important chapters until the global frame limit is reached. Candidate cards support:

- `选用`
- `取消`
- `拒绝`

Rejected candidates stay visible but subdued.

### Finalization

The final review action says `确认定稿`, not `确认定稿并生成 ZIP`. Finalization still rebuilds `download.zip` in the background because the package is a derived download artifact, but the product promise is the final draft.

### Download Naming

The browser and desktop download filename for `download.zip` should use the generated article title from `metadata.json`, sanitized for filesystem use, with `.zip` appended. Single artifact downloads can keep their artifact names.

## Data Flow

- Backend progress strings are corrected at the source so the UI never receives `????`.
- Frame candidates remain stored in `review/frame_candidates.json`; selection endpoints update that file.
- `FrameCandidateIndex` includes optional `chapter_contexts` so the modal can explain each group without parsing markdown on the frontend.
- `JobPublicState` includes a `download_filename` for ZIP naming, derived from metadata title.
- Loading an old job protects manual notes by snapshotting an unmatched root `note.md` into a `manual_###` version before further version operations.

## Testing

- Backend tests prove progress labels are readable Chinese strings and never `????`.
- Backend tests prove multiple candidates can be selected in the same chapter and that selected counts respect frame limits.
- Backend tests prove old root `note.md` content is snapshotted as a manual version when it has no matching version.
- Backend/API tests prove ZIP filename is derived from metadata title.
- Frontend style/structure tests prove progress moved under the stepper, subtitle actions moved into the preview header, the inline frame candidate block is gone, and a modal entry exists.
- Full backend tests and frontend build must pass before merge.
