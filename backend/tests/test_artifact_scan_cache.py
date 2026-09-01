from pathlib import Path

from backend.app.filenames import ZIP_DIRTY_MARKER
from backend.app.job_store import JobStore


def test_repeated_artifact_refresh_reuses_cached_scan(tmp_path, monkeypatch) -> None:
    job_id = "cached-artifacts"
    job_dir = tmp_path / job_id
    debug_dir = job_dir / "debug"
    debug_dir.mkdir(parents=True)
    (job_dir / "note.md").write_text("# note", encoding="utf-8")
    (debug_dir / "trace.log").write_text("trace", encoding="utf-8")
    store = JobStore(tmp_path)
    store.create(job_id)

    first = store.refresh_artifacts(job_id)
    real_rglob = Path.rglob
    monkeypatch.setattr(
        Path,
        "rglob",
        lambda self, pattern: (_ for _ in ()).throw(AssertionError("cached refresh must not rescan")),
    )

    second = store.refresh_artifacts(job_id)

    monkeypatch.setattr(Path, "rglob", real_rglob)
    assert second == first


def test_artifact_cache_invalidates_when_frame_directory_changes(tmp_path) -> None:
    job_id = "frame-cache-invalidation"
    job_dir = tmp_path / job_id
    job_dir.mkdir()
    (job_dir / "note.md").write_text("# note", encoding="utf-8")
    store = JobStore(tmp_path)
    store.create(job_id)
    store.refresh_artifacts(job_id)

    frame = job_dir / "frames" / "frame_001.jpg"
    frame.parent.mkdir()
    frame.write_bytes(b"frame")
    refreshed = store.refresh_artifacts(job_id)

    assert "frames/frame_001.jpg" in {artifact.path for artifact in refreshed}


def test_artifact_revision_changes_only_when_derived_resources_change(tmp_path) -> None:
    job_id = "derived-resource-revision"
    job_dir = tmp_path / job_id
    job_dir.mkdir()
    store = JobStore(tmp_path)
    state = store.create(job_id)
    initial_revision = state.artifact_revision

    store.update(job_id, progress=25, step="转写进度")
    store.refresh_artifacts(job_id)
    progress_revision = store.get(job_id).artifact_revision

    (job_dir / "debug.log").write_text("diagnostic", encoding="utf-8")
    store.refresh_artifacts(job_id)
    debug_revision = store.get(job_id).artifact_revision

    (job_dir / "subtitles.md").write_text("# subtitles", encoding="utf-8")
    store.refresh_artifacts(job_id)
    subtitle_revision = store.get(job_id).artifact_revision

    assert progress_revision == initial_revision
    assert debug_revision == initial_revision
    assert subtitle_revision != initial_revision


def test_artifact_revision_tracks_version_review_drafts(tmp_path) -> None:
    job_id = "version-review-revision"
    job_dir = tmp_path / job_id
    job_dir.mkdir()
    store = JobStore(tmp_path)
    state = store.create(job_id)
    initial_revision = state.artifact_revision

    review_draft = job_dir / "note_versions" / "note_001" / "review" / "review_draft.json"
    review_draft.parent.mkdir(parents=True)
    review_draft.write_text('{"schema_version":2}', encoding="utf-8")
    store.refresh_artifacts(job_id)
    created_revision = store.get(job_id).artifact_revision

    review_draft.write_text('{"schema_version":2,"title":"edited"}', encoding="utf-8")
    store.refresh_artifacts(job_id)
    edited_revision = store.get(job_id).artifact_revision

    assert created_revision != initial_revision
    assert edited_revision != created_revision


def test_artifact_revision_tracks_the_canonical_zip_dirty_marker(tmp_path) -> None:
    job_id = "zip-dirty-revision"
    job_dir = tmp_path / job_id
    job_dir.mkdir()
    store = JobStore(tmp_path)
    state = store.create(job_id)
    initial_revision = state.artifact_revision

    (job_dir / ZIP_DIRTY_MARKER).write_text("1", encoding="utf-8")
    store.refresh_artifacts(job_id)
    dirty_revision = store.get(job_id).artifact_revision

    assert dirty_revision != initial_revision
