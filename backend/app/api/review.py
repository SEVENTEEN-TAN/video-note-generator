from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractContextManager
from pathlib import Path

from fastapi import APIRouter, HTTPException

from ..frame_candidates import (
    build_frame_candidate_index,
    load_frame_candidate_index,
    reject_frame_candidate,
    select_frame_candidate,
    write_frame_candidate_index,
)
from ..job_paths import InvalidJobIdError, JobDirectoryNotFoundError, read_job_metadata, resolve_job_dir
from ..job_store import JobStore
from ..models import (
    FrameCandidateIndex,
    JobPublicState,
    JobStage,
    JobStatus,
    QualityReport,
    ReviewAssets,
    ReviewDraft,
    ReviewDraftParagraphUpdate,
)
from ..note_versions import find_source_video, load_note_version_index
from ..processor import mark_zip_dirty
from ..review_drafts import get_or_build_review_draft, load_review_draft, update_review_draft_paragraph
from ..review_finalization import complete_review_finalization, finalize_reviewed_note, is_note_review_pending
from ..review_quality import (
    build_quality_report,
    invalidate_quality_report,
    load_quality_report,
    write_quality_report,
)


JobMutation = Callable[[str], AbstractContextManager[None]]
RevisionGuard = Callable[..., JobPublicState | None]
CreateZip = Callable[[Path], Path]


def create_review_router(
    *,
    get_outputs_root: Callable[[], Path],
    get_store: Callable[[], JobStore],
    job_mutation: JobMutation,
    require_expected_job_revisions: RevisionGuard,
    create_zip: CreateZip,
) -> APIRouter:
    router = APIRouter(tags=["review"])

    def current_store() -> JobStore:
        store = get_store()
        store.outputs_root = get_outputs_root()
        return store

    @router.get("/api/jobs/{job_id}/quality-report", response_model=QualityReport)
    def get_quality_report(job_id: str) -> QualityReport:
        job_dir = _resolve_job_dir_or_http(get_outputs_root(), job_id)
        if not (job_dir / "note.md").exists():
            raise HTTPException(status_code=400, detail="quality report requires note.md.")
        if not (job_dir / "transcript.json").exists():
            raise HTTPException(status_code=400, detail="quality report requires transcript.json.")
        report = load_quality_report(job_dir)
        if report is None:
            raise HTTPException(status_code=404, detail="Quality report is not prepared.")
        return report

    @router.get("/api/jobs/{job_id}/frame-candidates", response_model=FrameCandidateIndex)
    def get_frame_candidates(job_id: str) -> FrameCandidateIndex:
        job_dir = _resolve_job_dir_or_http(get_outputs_root(), job_id)
        existing = load_frame_candidate_index(job_dir)
        if existing is not None:
            return existing
        raise HTTPException(status_code=404, detail="Frame candidates are not prepared.")

    @router.post(
        "/api/jobs/{job_id}/frame-candidates/{candidate_id}/select",
        response_model=FrameCandidateIndex,
    )
    def select_job_frame_candidate(
        job_id: str,
        candidate_id: str,
        expected_state_revision: int | None = None,
        expected_artifact_revision: str | None = None,
    ) -> FrameCandidateIndex:
        with job_mutation(job_id):
            require_expected_job_revisions(
                job_id,
                expected_state_revision=expected_state_revision,
                expected_artifact_revision=expected_artifact_revision,
            )
            job_dir = _resolve_job_dir_or_http(get_outputs_root(), job_id)
            try:
                metadata = read_job_metadata(job_dir)
                index = select_frame_candidate(
                    job_dir,
                    candidate_id,
                    frame_limit=int(metadata.get("frame_limit") or 6),
                )
            except FileNotFoundError as exc:
                raise HTTPException(status_code=404, detail=str(exc)) from exc
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            invalidate_quality_report(job_dir)
            current_store().refresh_artifacts(job_id)
            return index

    @router.post(
        "/api/jobs/{job_id}/frame-candidates/{candidate_id}/reject",
        response_model=FrameCandidateIndex,
    )
    def reject_job_frame_candidate(
        job_id: str,
        candidate_id: str,
        expected_state_revision: int | None = None,
        expected_artifact_revision: str | None = None,
    ) -> FrameCandidateIndex:
        with job_mutation(job_id):
            require_expected_job_revisions(
                job_id,
                expected_state_revision=expected_state_revision,
                expected_artifact_revision=expected_artifact_revision,
            )
            job_dir = _resolve_job_dir_or_http(get_outputs_root(), job_id)
            try:
                index = reject_frame_candidate(job_dir, candidate_id)
            except FileNotFoundError as exc:
                raise HTTPException(status_code=404, detail=str(exc)) from exc
            invalidate_quality_report(job_dir)
            current_store().refresh_artifacts(job_id)
            return index

    @router.get("/api/jobs/{job_id}/review-draft", response_model=ReviewDraft)
    def get_job_review_draft(job_id: str, version_id: str | None = None) -> ReviewDraft:
        job_dir = _resolve_job_dir_or_http(get_outputs_root(), job_id)
        existing = load_review_draft(job_dir, version_id)
        if existing is not None:
            return existing
        raise HTTPException(status_code=404, detail="Review draft is not prepared.")

    @router.post("/api/jobs/{job_id}/review-assets/prepare", response_model=ReviewAssets)
    def prepare_job_review_assets(job_id: str, version_id: str | None = None) -> ReviewAssets:
        with job_mutation(job_id):
            job_dir = _resolve_job_dir_or_http(get_outputs_root(), job_id)
            if not (job_dir / "note.md").exists():
                raise HTTPException(status_code=400, detail="Review assets require note.md.")
            if not (job_dir / "transcript.json").exists():
                raise HTTPException(status_code=400, detail="Review assets require transcript.json.")

            store = current_store()
            frame_candidates = load_frame_candidate_index(job_dir)
            if frame_candidates is None:
                try:
                    video_path = find_source_video(job_dir)
                except FileNotFoundError as exc:
                    raise HTTPException(status_code=400, detail=str(exc)) from exc
                metadata = read_job_metadata(job_dir)
                duration = metadata.get("duration_seconds")
                frame_candidates = build_frame_candidate_index(
                    job_dir,
                    video_path,
                    duration=float(duration) if duration is not None else None,
                    is_cancelled=lambda: store.is_cancel_requested(job_id),
                )
                write_frame_candidate_index(job_dir, frame_candidates)

            try:
                review_draft = get_or_build_review_draft(job_dir, version_id)
                quality_report = build_quality_report(job_dir)
                write_quality_report(job_dir, quality_report)
            except (FileNotFoundError, ValueError) as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            store.refresh_artifacts(job_id)
            return ReviewAssets(
                frame_candidates=frame_candidates,
                quality_report=quality_report,
                review_draft=review_draft,
            )

    @router.patch(
        "/api/jobs/{job_id}/review-draft/paragraphs/{paragraph_id}",
        response_model=ReviewDraft,
    )
    def update_job_review_draft_paragraph(
        job_id: str,
        paragraph_id: str,
        update: ReviewDraftParagraphUpdate,
        version_id: str | None = None,
        expected_state_revision: int | None = None,
        expected_artifact_revision: str | None = None,
    ) -> ReviewDraft:
        with job_mutation(job_id):
            require_expected_job_revisions(
                job_id,
                expected_state_revision=expected_state_revision,
                expected_artifact_revision=expected_artifact_revision,
            )
            job_dir = _resolve_job_dir_or_http(get_outputs_root(), job_id)
            try:
                draft = update_review_draft_paragraph(
                    job_dir,
                    paragraph_id,
                    body=update.body,
                    selected_frame_ids=update.selected_frame_ids,
                    status=update.status,
                    version_id=version_id,
                )
            except FileNotFoundError as exc:
                raise HTTPException(status_code=404, detail=str(exc)) from exc
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            invalidate_quality_report(job_dir)
            current_store().refresh_artifacts(job_id)
            return draft

    @router.post("/api/jobs/{job_id}/finalize", response_model=JobPublicState)
    def finalize_job(
        job_id: str,
        version_id: str | None = None,
        expected_state_revision: int | None = None,
        expected_artifact_revision: str | None = None,
    ) -> JobPublicState:
        with job_mutation(job_id):
            require_expected_job_revisions(
                job_id,
                expected_state_revision=expected_state_revision,
                expected_artifact_revision=expected_artifact_revision,
            )
            job_dir = _resolve_job_dir_or_http(get_outputs_root(), job_id)
            if not is_note_review_pending(job_dir):
                raise HTTPException(status_code=409, detail="note review is not pending.")
            if version_id:
                index = load_note_version_index(job_dir)
                if index.active_version_id != version_id:
                    raise HTTPException(
                        status_code=409,
                        detail="The selected note version is no longer active. Reload it before finalizing.",
                    )
            try:
                finalize_reviewed_note(job_dir, version_id)
                report = build_quality_report(job_dir)
                write_quality_report(job_dir, report)
                mark_zip_dirty(job_dir)
                create_zip(job_dir)
                complete_review_finalization(job_dir)
            except (FileNotFoundError, ValueError) as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc

            store = current_store()
            store.refresh_artifacts(job_id)
            if not store.get(job_id):
                store.load_from_disk(job_id)
            store.update(
                job_id,
                status=JobStatus.succeeded,
                stage=JobStage.completed,
                step="完成",
                progress=100,
                error="",
            )
            state = store.get(job_id)
            if not state:
                raise HTTPException(status_code=404, detail="Job not found.")
            return state

    return router


def _resolve_job_dir_or_http(outputs_root: Path, job_id: str) -> Path:
    try:
        return resolve_job_dir(outputs_root, job_id)
    except InvalidJobIdError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except JobDirectoryNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
