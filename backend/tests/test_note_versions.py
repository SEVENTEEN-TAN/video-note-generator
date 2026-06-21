from __future__ import annotations

import json
from zipfile import ZipFile

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
from backend.app.note_versions import add_note_version, load_note_version_index, regenerate_note_version, write_note_version_index
from backend.app.processor import create_zip


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
