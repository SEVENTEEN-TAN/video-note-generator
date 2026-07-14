from pathlib import Path

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
