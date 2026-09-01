from __future__ import annotations

import json

import pytest

from backend.app import atomic_io


def test_atomic_write_text_creates_parent_and_replaces_content(tmp_path) -> None:
    path = tmp_path / "nested" / "state.txt"
    path.parent.mkdir(parents=True)
    path.write_text("old", encoding="utf-8")

    atomic_io.atomic_write_text(path, "new", encoding="utf-8")

    assert path.read_text(encoding="utf-8") == "new"
    assert list(path.parent.glob(f".{path.name}.*.tmp")) == []


def test_atomic_write_json_writes_unicode_payload(tmp_path) -> None:
    path = tmp_path / "state" / "payload.json"

    atomic_io.atomic_write_json(path, {"title": "视频笔记", "count": 2})

    assert json.loads(path.read_text(encoding="utf-8")) == {
        "title": "视频笔记",
        "count": 2,
    }


def test_atomic_write_text_cleans_temporary_file_when_replace_fails(tmp_path, monkeypatch) -> None:
    path = tmp_path / "state.txt"

    def fail_replace(_source, _target) -> None:
        raise OSError("replace failed")

    monkeypatch.setattr(atomic_io.os, "replace", fail_replace)

    with pytest.raises(OSError, match="replace failed"):
        atomic_io.atomic_write_text(path, "content")

    assert not path.exists()
    assert list(tmp_path.glob(f".{path.name}.*.tmp")) == []


def test_atomic_replace_directory_restores_previous_target_on_failure(tmp_path, monkeypatch) -> None:
    source = tmp_path / "frames.new"
    target = tmp_path / "frames"
    source.mkdir()
    target.mkdir()
    (source / "frame.jpg").write_bytes(b"new")
    (target / "frame.jpg").write_bytes(b"old")
    real_replace = atomic_io.os.replace
    failed = False

    def fail_new_directory_replace(current_source, current_target) -> None:
        nonlocal failed
        if not failed and current_source == source and current_target == target:
            failed = True
            raise OSError("directory replace failed")
        real_replace(current_source, current_target)

    monkeypatch.setattr(atomic_io.os, "replace", fail_new_directory_replace)

    with pytest.raises(OSError, match="directory replace failed"):
        atomic_io.atomic_replace_directory(source, target)

    assert (target / "frame.jpg").read_bytes() == b"old"
    assert (source / "frame.jpg").read_bytes() == b"new"
    assert list(tmp_path.glob(".frames.*.backup")) == []
