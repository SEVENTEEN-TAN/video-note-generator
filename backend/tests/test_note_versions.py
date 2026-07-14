from __future__ import annotations

import json
from zipfile import ZipFile

import pytest
from fastapi.testclient import TestClient

from backend.app import main
from backend.app.main import app
from backend.app.models import (
    Chapter,
    JobConfig,
    KeyMoment,
    NoteDraft,
    NoteLanguage,
    NoteStyle,
    NoteVersion,
    NoteVersionIndex,
    TranscriptionMode,
)
from backend.app.job_store import JobStore
from backend.app import note_versions
from backend.app.note_versions import (
    activate_note_version,
    add_note_version,
    load_note_version_index,
    regenerate_note_version,
    write_note_version_index,
)
from backend.app.processor import create_zip, mark_zip_dirty


def make_version(version_id: str, *, selected: bool = True, active: bool = False) -> NoteVersion:
    return NoteVersion(
        id=version_id,
        label=f"{version_id} detailed",
        note_style=NoteStyle.detailed,
        note_language="zh",
        note_model="qwen-plus",
        note_base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        frame_limit=6,
        note_path=f"note_versions/{version_id}/note.md",
        frame_dir=f"note_versions/{version_id}/frames",
        selected=selected,
        active=active,
    )


def test_add_note_version_keeps_existing_selection_and_makes_new_version_active(tmp_path) -> None:
    job_dir = tmp_path

    first = add_note_version(job_dir, make_version("note_001"))
    second = add_note_version(job_dir, make_version("note_002"))
    loaded = load_note_version_index(job_dir)

    assert first.active_version_id == "note_001"
    assert second.active_version_id == "note_002"
    assert loaded.selected_version_ids == ["note_001", "note_002"]
    assert [version.id for version in loaded.versions] == ["note_001", "note_002"]
    assert [version.active for version in loaded.versions] == [False, True]


def test_load_note_version_index_returns_empty_index_when_json_is_corrupt(tmp_path) -> None:
    job_dir = tmp_path
    index_path = job_dir / "note_versions" / "versions.json"
    index_path.parent.mkdir(parents=True)
    index_path.write_text("{not valid json", encoding="utf-8")

    loaded = load_note_version_index(job_dir)

    assert loaded.active_version_id is None
    assert loaded.selected_version_ids == []
    assert loaded.versions == []


def test_load_note_version_index_filters_versions_with_unsafe_paths(tmp_path) -> None:
    job_dir = tmp_path
    unsafe_note = make_version("note_001").model_copy(update={"note_path": "../secret.md"})
    unsafe_frames = make_version("note_002").model_copy(update={"frame_dir": "../frames"})
    unsafe_id = make_version("../note_003")
    safe = make_version("note_004")
    index_path = job_dir / "note_versions" / "versions.json"
    index_path.parent.mkdir(parents=True)
    index_path.write_text(
        NoteVersionIndex(
            active_version_id="note_001",
            selected_version_ids=["note_001", "note_002", "../note_003", "note_004"],
            versions=[unsafe_note, unsafe_frames, unsafe_id, safe],
        ).model_dump_json(indent=2),
        encoding="utf-8",
    )

    loaded = load_note_version_index(job_dir)

    assert [version.id for version in loaded.versions] == ["note_004"]
    assert loaded.active_version_id is None
    assert loaded.selected_version_ids == ["note_004"]


def test_activate_note_version_rejects_filtered_unsafe_version(tmp_path) -> None:
    job_dir = tmp_path / "job"
    job_dir.mkdir()
    secret = tmp_path / "secret.md"
    secret.write_text("# secret", encoding="utf-8")
    index_path = job_dir / "note_versions" / "versions.json"
    index_path.parent.mkdir(parents=True)
    index_path.write_text(
        NoteVersionIndex(
            active_version_id="note_001",
            selected_version_ids=["note_001"],
            versions=[make_version("note_001").model_copy(update={"note_path": "../secret.md"})],
        ).model_dump_json(indent=2),
        encoding="utf-8",
    )

    with pytest.raises(FileNotFoundError):
        activate_note_version(job_dir, "note_001")

    assert not (job_dir / "note.md").exists()


def test_activate_note_version_rejects_missing_note_before_changing_active(tmp_path) -> None:
    job_dir = tmp_path
    (job_dir / "note.md").write_text("# Active", encoding="utf-8")
    frames_dir = job_dir / "frames"
    frames_dir.mkdir()
    (frames_dir / "frame_001.jpg").write_bytes(b"active frame")

    version_dir = job_dir / "note_versions" / "note_001"
    (version_dir / "frames").mkdir(parents=True)
    (version_dir / "frames" / "frame_001.jpg").write_bytes(b"new frame")
    write_note_version_index(
        job_dir,
        NoteVersionIndex(
            active_version_id=None,
            selected_version_ids=[],
            versions=[make_version("note_001", selected=False, active=False)],
        ),
    )

    with pytest.raises(FileNotFoundError):
        activate_note_version(job_dir, "note_001")

    loaded = load_note_version_index(job_dir)
    assert loaded.active_version_id is None
    assert loaded.selected_version_ids == []
    assert (job_dir / "note.md").read_text(encoding="utf-8") == "# Active"
    assert (frames_dir / "frame_001.jpg").read_bytes() == b"active frame"


def test_activate_note_version_rejects_missing_frames_before_deleting_current_frames(tmp_path) -> None:
    job_dir = tmp_path
    (job_dir / "note.md").write_text("# Active", encoding="utf-8")
    frames_dir = job_dir / "frames"
    frames_dir.mkdir()
    (frames_dir / "frame_001.jpg").write_bytes(b"active frame")

    version_dir = job_dir / "note_versions" / "note_001"
    version_dir.mkdir(parents=True)
    (version_dir / "note.md").write_text("# New", encoding="utf-8")
    write_note_version_index(
        job_dir,
        NoteVersionIndex(
            active_version_id=None,
            selected_version_ids=[],
            versions=[make_version("note_001", selected=False, active=False)],
        ),
    )

    with pytest.raises(FileNotFoundError):
        activate_note_version(job_dir, "note_001")

    loaded = load_note_version_index(job_dir)
    assert loaded.active_version_id is None
    assert loaded.selected_version_ids == []
    assert (job_dir / "note.md").read_text(encoding="utf-8") == "# Active"
    assert (frames_dir / "frame_001.jpg").read_bytes() == b"active frame"


def test_note_version_patch_rejects_missing_frames_before_changing_active(tmp_path, monkeypatch) -> None:
    outputs_root = tmp_path / "outputs"
    job_id = "missing-frames-job"
    job_dir = outputs_root / job_id
    job_dir.mkdir(parents=True)
    (job_dir / "note.md").write_text("# Active", encoding="utf-8")
    frames_dir = job_dir / "frames"
    frames_dir.mkdir()
    (frames_dir / "frame_001.jpg").write_bytes(b"active frame")

    version_dir = job_dir / "note_versions" / "note_001"
    version_dir.mkdir(parents=True)
    (version_dir / "note.md").write_text("# New", encoding="utf-8")
    write_note_version_index(
        job_dir,
        NoteVersionIndex(
            active_version_id=None,
            selected_version_ids=[],
            versions=[make_version("note_001", selected=False, active=False)],
        ),
    )
    monkeypatch.setattr(main, "OUTPUTS_ROOT", outputs_root)
    monkeypatch.setattr(main, "store", JobStore(outputs_root))

    response = TestClient(app, raise_server_exceptions=False).patch(
        f"/api/jobs/{job_id}/note-versions",
        json={"active_version_id": "note_001", "selected_version_ids": ["note_001"]},
    )

    assert response.status_code == 404
    loaded = load_note_version_index(job_dir)
    assert loaded.active_version_id is None
    assert loaded.selected_version_ids == []
    assert (job_dir / "note.md").read_text(encoding="utf-8") == "# Active"
    assert (frames_dir / "frame_001.jpg").read_bytes() == b"active frame"


def test_ensure_root_note_has_version_snapshots_legacy_manual_note(tmp_path) -> None:
    job_dir = tmp_path / "job"
    job_dir.mkdir()
    (job_dir / "note.md").write_text("# 手工改过的旧笔记", encoding="utf-8-sig")
    (job_dir / "frames").mkdir()
    (job_dir / "frames" / "frame_001.jpg").write_bytes(b"manual frame")

    index = note_versions.ensure_root_note_has_version(job_dir)

    assert index.active_version_id == "manual_001"
    assert index.selected_version_ids == ["manual_001"]
    assert index.versions[0].label == "manual_001 · 手工版本"
    assert index.versions[0].note_path == "note_versions/manual_001/note.md"
    assert (job_dir / "note_versions" / "manual_001" / "note.md").read_text(encoding="utf-8-sig") == "# 手工改过的旧笔记"
    assert (job_dir / "note_versions" / "manual_001" / "frames" / "frame_001.jpg").read_bytes() == b"manual frame"


def test_ensure_root_note_has_version_snapshots_manual_note_that_differs_from_active_version(tmp_path) -> None:
    job_dir = tmp_path / "job"
    job_dir.mkdir()
    (job_dir / "note.md").write_text("# 用户定稿", encoding="utf-8-sig")
    root_frames = job_dir / "frames"
    root_frames.mkdir()
    (root_frames / "frame_001.jpg").write_bytes(b"manual frame")
    version_dir = job_dir / "note_versions" / "note_001"
    (version_dir / "frames").mkdir(parents=True)
    (version_dir / "note.md").write_text("# AI 初稿", encoding="utf-8-sig")
    (version_dir / "frames" / "frame_001.jpg").write_bytes(b"ai frame")
    write_note_version_index(
        job_dir,
        NoteVersionIndex(
            active_version_id="note_001",
            selected_version_ids=["note_001"],
            versions=[make_version("note_001", selected=True, active=True)],
        ),
    )

    index = note_versions.ensure_root_note_has_version(job_dir)

    assert index.active_version_id == "manual_001"
    assert index.selected_version_ids == ["note_001", "manual_001"]
    assert [version.id for version in index.versions] == ["note_001", "manual_001"]
    manual = index.versions[1]
    assert manual.label == "manual_001 · 手工版本"
    assert (job_dir / "note_versions" / "manual_001" / "note.md").read_text(encoding="utf-8-sig") == "# 用户定稿"


def test_create_zip_includes_selected_note_versions_with_relative_frames(tmp_path) -> None:
    job_dir = tmp_path
    (job_dir / "audio.mp3").write_bytes(b"mp3")
    (job_dir / "subtitles.md").write_text("00:00:00 - 00:00:01 hello", encoding="utf-8")
    (job_dir / "metadata.json").write_text(json.dumps({"title": "Demo"}), encoding="utf-8")
    (job_dir / "note.md").write_text("# Active", encoding="utf-8")

    for version_id in ("note_001", "note_002", "note_003"):
        version_dir = job_dir / "note_versions" / version_id
        frames_dir = version_dir / "frames"
        frames_dir.mkdir(parents=True)
        (version_dir / "note.md").write_text(f"# {version_id}\n\n![frame](frames/frame_001.jpg)", encoding="utf-8")
        (frames_dir / "frame_001.jpg").write_bytes(b"jpg")

    write_note_version_index(
        job_dir,
        NoteVersionIndex(
            active_version_id="note_002",
            selected_version_ids=["note_001", "note_002"],
            versions=[
                make_version("note_001", selected=True),
                make_version("note_002", selected=True, active=True),
                make_version("note_003", selected=False),
            ],
        ),
    )

    zip_path = create_zip(job_dir)

    with ZipFile(zip_path) as archive:
        names = set(archive.namelist())

    assert "note.md" in names
    assert "notes/note_001/note.md" in names
    assert "notes/note_001/frames/frame_001.jpg" in names
    assert "notes/note_002/note.md" in names
    assert "notes/note_002/frames/frame_001.jpg" in names
    assert "notes/note_003/note.md" not in names


def test_create_zip_ignores_unsafe_note_version_paths_from_disk_index(tmp_path) -> None:
    job_dir = tmp_path / "job"
    job_dir.mkdir()
    secret = tmp_path / "secret.md"
    secret.write_text("# secret", encoding="utf-8")
    (job_dir / "note.md").write_text("# active", encoding="utf-8")
    index_path = job_dir / "note_versions" / "versions.json"
    index_path.parent.mkdir(parents=True)
    index_path.write_text(
        NoteVersionIndex(
            active_version_id="note_001",
            selected_version_ids=["note_001"],
            versions=[make_version("note_001").model_copy(update={"note_path": "../secret.md"})],
        ).model_dump_json(indent=2),
        encoding="utf-8",
    )

    zip_path = create_zip(job_dir)

    with ZipFile(zip_path) as archive:
        names = set(archive.namelist())
        payloads = {name: archive.read(name) for name in names}

    assert "note.md" in names
    assert "notes/note_001/note.md" not in names
    assert b"# secret" not in payloads.values()


def test_create_zip_archives_normalized_note_version_index(tmp_path) -> None:
    job_dir = tmp_path
    (job_dir / "note.md").write_text("# Active", encoding="utf-8")
    unsafe = make_version("note_001").model_copy(update={"note_path": "../secret.md"})
    safe = make_version("note_002")
    safe_dir = job_dir / "note_versions" / "note_002"
    (safe_dir / "frames").mkdir(parents=True)
    (safe_dir / "note.md").write_text("# Safe", encoding="utf-8")
    index_path = job_dir / "note_versions" / "versions.json"
    index_path.parent.mkdir(parents=True, exist_ok=True)
    index_path.write_text(
        NoteVersionIndex(
            active_version_id="note_001",
            selected_version_ids=["note_001", "note_002"],
            versions=[unsafe, safe],
        ).model_dump_json(indent=2),
        encoding="utf-8",
    )

    zip_path = create_zip(job_dir)

    with ZipFile(zip_path) as archive:
        archived_index = json.loads(archive.read("notes/versions.json"))

    assert [version["id"] for version in archived_index["versions"]] == ["note_002"]
    assert "../secret.md" not in json.dumps(archived_index)


def test_create_zip_keeps_existing_zip_when_rebuild_fails(tmp_path, monkeypatch) -> None:
    job_dir = tmp_path
    old_zip = job_dir / "download.zip"
    old_zip.write_bytes(b"old zip")
    opened_paths = []

    class BrokenZipFile:
        def __init__(self, path, *_args, **_kwargs) -> None:
            opened_paths.append(path)

        def __enter__(self):
            raise RuntimeError("zip writer failed")

        def __exit__(self, *_args) -> bool:
            return False

    monkeypatch.setattr("backend.app.processor.ZipFile", BrokenZipFile)
    mark_zip_dirty(job_dir)

    with pytest.raises(RuntimeError):
        create_zip(job_dir)

    assert old_zip.read_bytes() == b"old zip"
    assert not (job_dir / "download.zip.tmp").exists()
    assert opened_paths == [job_dir / "download.zip.tmp"]


def test_refresh_artifacts_can_read_disk_job_without_memory_state(tmp_path) -> None:
    outputs_root = tmp_path / "outputs"
    job_id = "disk-only-job"
    job_dir = outputs_root / job_id
    job_dir.mkdir(parents=True)
    (job_dir / "note.md").write_text("# Disk note", encoding="utf-8")

    artifacts = JobStore(outputs_root).refresh_artifacts(job_id)

    assert [artifact.path for artifact in artifacts] == ["note.md"]


def test_regenerate_note_version_reuses_transcript_and_creates_new_version(tmp_path, monkeypatch) -> None:
    job_dir = tmp_path
    video_path = job_dir / "source_video" / "input.mp4"
    video_path.parent.mkdir(parents=True)
    video_path.write_bytes(b"video")
    (job_dir / "transcript.json").write_text(
        json.dumps({"text": "hello", "segments": [{"start": 0, "end": 2, "text": "hello"}]}),
        encoding="utf-8",
    )
    (job_dir / "metadata.json").write_text(
        json.dumps({"original_filename": "input.mp4", "duration_seconds": 10}),
        encoding="utf-8",
    )

    def fake_generate_note_draft(config, duration, segments) -> NoteDraft:
        assert duration == 10
        assert segments[0].text == "hello"
        return NoteDraft(
            title="Regenerated",
            summary="summary",
            chapters=[Chapter(title="Opening", start_time=0, end_time=2)],
            key_moments=[KeyMoment(time=1, reason="opening", chapter_index=0)],
        )

    def fake_extract_frame(source_video, output_path, timestamp, duration) -> float:
        assert source_video == video_path
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"jpg")
        return timestamp

    monkeypatch.setattr("backend.app.note_versions.generate_note_draft", fake_generate_note_draft)
    monkeypatch.setattr("backend.app.note_versions.extract_frame", fake_extract_frame)

    config = JobConfig(
        transcription_mode=TranscriptionMode.local_faster_whisper,
        transcription_model="reuse-transcript",
        note_api_key="secret",
        note_base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        note_model="qwen-plus",
        note_language=NoteLanguage.zh,
        note_style=NoteStyle.meeting_minutes,
        frame_limit=3,
        original_filename="input.mp4",
    )

    version = regenerate_note_version(job_dir, config)

    assert version.id == "note_001"
    assert version.note_style == NoteStyle.meeting_minutes
    assert (job_dir / "note_versions" / "note_001" / "note.md").exists()
    assert (job_dir / "note_versions" / "note_001" / "frames" / "frame_001.jpg").exists()
    assert (job_dir / "note.md").read_text(encoding="utf-8-sig").startswith("# Regenerated")


def test_note_version_frame_failure_leaves_no_partial_version_directory(tmp_path, monkeypatch) -> None:
    video_path = tmp_path / "source_video" / "input.mp4"
    video_path.parent.mkdir(parents=True)
    video_path.write_bytes(b"video")
    calls = 0

    def failing_extract(_video, output_path, timestamp, _duration):
        nonlocal calls
        calls += 1
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"partial")
        if calls == 2:
            raise RuntimeError("frame failed")
        return timestamp

    monkeypatch.setattr(note_versions, "extract_frame", failing_extract)
    config = JobConfig(
        transcription_mode=TranscriptionMode.local_faster_whisper,
        transcription_model="small",
        note_api_key="secret",
        note_model="gpt-5.5",
        note_language=NoteLanguage.zh,
        frame_limit=2,
        original_filename="input.mp4",
    )
    draft = NoteDraft(
        title="Transactional",
        summary="summary",
        chapters=[Chapter(title="One", start_time=0, end_time=20)],
        key_moments=[
            KeyMoment(time=5, reason="one", chapter_index=0),
            KeyMoment(time=10, reason="two", chapter_index=0),
        ],
    )

    with pytest.raises(RuntimeError, match="frame failed"):
        note_versions.create_note_version_from_draft(
            job_dir=tmp_path,
            video_path=video_path,
            draft=draft,
            duration=20,
            config=config,
            version_id="note_001",
        )

    versions_root = tmp_path / "note_versions"
    assert not (versions_root / "note_001").exists()
    assert not list(versions_root.glob(".note_001.*.tmp"))
    assert load_note_version_index(tmp_path).versions == []


def test_new_note_version_hardlinks_compatible_existing_frames(tmp_path, monkeypatch) -> None:
    video_path = tmp_path / "source_video" / "input.mp4"
    video_path.parent.mkdir(parents=True)
    video_path.write_bytes(b"video")
    extracts = 0

    def fake_extract(_video, output_path, timestamp, _duration):
        nonlocal extracts
        extracts += 1
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"shared frame")
        return timestamp

    monkeypatch.setattr(note_versions, "extract_frame", fake_extract)
    config = JobConfig(
        transcription_mode=TranscriptionMode.local_faster_whisper,
        transcription_model="small",
        note_api_key="secret",
        note_model="gpt-5.5",
        note_language=NoteLanguage.zh,
        frame_limit=1,
        original_filename="input.mp4",
    )
    draft = NoteDraft(
        title="Reuse",
        summary="summary",
        chapters=[Chapter(title="One", start_time=0, end_time=20)],
        key_moments=[KeyMoment(time=5, reason="same", chapter_index=0)],
    )

    note_versions.create_note_version_from_draft(
        job_dir=tmp_path,
        video_path=video_path,
        draft=draft,
        duration=20,
        config=config,
        version_id="note_001",
    )
    note_versions.create_note_version_from_draft(
        job_dir=tmp_path,
        video_path=video_path,
        draft=draft,
        duration=20,
        config=config,
        version_id="note_002",
    )

    assert extracts == 1
    assert (tmp_path / "note_versions" / "note_002" / "frames" / "frame_001.jpg").read_bytes() == b"shared frame"


def test_activate_note_version_copy_failure_preserves_previous_index_and_public_artifacts(tmp_path, monkeypatch) -> None:
    version_one = make_version("note_001", selected=True, active=True)
    version_two = make_version("note_002", selected=True, active=False)
    for version, note_text, frame_bytes in (
        (version_one, "# One", b"one"),
        (version_two, "# Two", b"two"),
    ):
        version_dir = tmp_path / "note_versions" / version.id
        (version_dir / "frames").mkdir(parents=True)
        (version_dir / "note.md").write_text(note_text, encoding="utf-8")
        (version_dir / "frames" / "frame_001.jpg").write_bytes(frame_bytes)
    write_note_version_index(
        tmp_path,
        NoteVersionIndex(
            active_version_id="note_001",
            selected_version_ids=["note_001", "note_002"],
            versions=[version_one, version_two],
        ),
    )
    (tmp_path / "note.md").write_text("# One", encoding="utf-8")
    (tmp_path / "frames").mkdir()
    (tmp_path / "frames" / "frame_001.jpg").write_bytes(b"one")
    monkeypatch.setattr(
        note_versions.shutil,
        "copytree",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("copy failed")),
    )

    with pytest.raises(OSError, match="copy failed"):
        activate_note_version(tmp_path, "note_002")

    assert load_note_version_index(tmp_path).active_version_id == "note_001"
    assert (tmp_path / "note.md").read_text(encoding="utf-8") == "# One"
    assert (tmp_path / "frames" / "frame_001.jpg").read_bytes() == b"one"


def test_activate_note_version_index_failure_rolls_back_public_artifacts(tmp_path, monkeypatch) -> None:
    version_one = make_version("note_001", selected=True, active=True)
    version_two = make_version("note_002", selected=True, active=False)
    for version, note_text, frame_bytes in (
        (version_one, "# One", b"one"),
        (version_two, "# Two", b"two"),
    ):
        version_dir = tmp_path / "note_versions" / version.id
        (version_dir / "frames").mkdir(parents=True)
        (version_dir / "note.md").write_text(note_text, encoding="utf-8")
        (version_dir / "frames" / "frame_001.jpg").write_bytes(frame_bytes)
    write_note_version_index(
        tmp_path,
        NoteVersionIndex(
            active_version_id="note_001",
            selected_version_ids=["note_001", "note_002"],
            versions=[version_one, version_two],
        ),
    )
    (tmp_path / "note.md").write_text("# One", encoding="utf-8")
    (tmp_path / "frames").mkdir()
    (tmp_path / "frames" / "frame_001.jpg").write_bytes(b"one")
    real_writer = note_versions.write_note_version_index
    monkeypatch.setattr(
        note_versions,
        "write_note_version_index",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("index failed")),
    )

    with pytest.raises(OSError, match="index failed"):
        activate_note_version(tmp_path, "note_002")

    monkeypatch.setattr(note_versions, "write_note_version_index", real_writer)
    assert load_note_version_index(tmp_path).active_version_id == "note_001"
    assert (tmp_path / "note.md").read_text(encoding="utf-8") == "# One"
    assert (tmp_path / "frames" / "frame_001.jpg").read_bytes() == b"one"
