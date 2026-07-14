from __future__ import annotations

from threading import Event, Thread

from backend.app import processor


def _seed_zip_job(job_dir) -> None:
    job_dir.mkdir()
    (job_dir / "note.md").write_text("# note", encoding="utf-8")
    (job_dir / "metadata.json").write_text("{}", encoding="utf-8")


def test_clean_zip_is_reused_without_rebuilding(tmp_path, monkeypatch) -> None:
    job_dir = tmp_path / "job"
    _seed_zip_job(job_dir)
    first = processor.create_zip(job_dir)
    first_bytes = first.read_bytes()
    monkeypatch.setattr(
        processor,
        "ZipFile",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("clean ZIP must be reused")),
    )

    second = processor.create_zip(job_dir)

    assert second == first
    assert second.read_bytes() == first_bytes


def test_dirty_zip_rebuild_is_serialized_across_concurrent_downloads(tmp_path, monkeypatch) -> None:
    job_dir = tmp_path / "job"
    _seed_zip_job(job_dir)
    processor.create_zip(job_dir)
    processor.mark_zip_dirty(job_dir)
    real_zip_file = processor.ZipFile
    builds = 0

    def counting_zip_file(*args, **kwargs):
        nonlocal builds
        builds += 1
        return real_zip_file(*args, **kwargs)

    monkeypatch.setattr(processor, "ZipFile", counting_zip_file)
    threads = [Thread(target=lambda: processor.create_zip(job_dir)) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=2)

    assert builds == 1
    assert not (job_dir / processor.ZIP_DIRTY_MARKER).exists()


def test_mutation_during_zip_build_leaves_zip_marked_dirty(tmp_path, monkeypatch) -> None:
    job_dir = tmp_path / "job"
    _seed_zip_job(job_dir)
    processor.create_zip(job_dir)
    processor.mark_zip_dirty(job_dir)
    build_started = Event()
    release_build = Event()
    mutation_finished = Event()

    def blocking_build(_job_dir, zip_path, dirty_marker):
        build_started.set()
        assert release_build.wait(timeout=2)
        dirty_marker.unlink(missing_ok=True)
        return zip_path

    monkeypatch.setattr(processor, "_build_zip", blocking_build)
    builder = Thread(target=lambda: processor.create_zip(job_dir))
    mutation = Thread(
        target=lambda: (processor.mark_zip_dirty(job_dir), mutation_finished.set())
    )
    builder.start()
    assert build_started.wait(timeout=1)
    mutation.start()
    assert mutation_finished.wait(timeout=0.05) is False
    release_build.set()
    builder.join(timeout=1)
    mutation.join(timeout=1)

    assert mutation_finished.is_set()
    assert (job_dir / processor.ZIP_DIRTY_MARKER).exists()
