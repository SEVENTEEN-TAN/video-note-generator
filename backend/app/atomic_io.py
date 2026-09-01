from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from typing import Any
from uuid import uuid4

from .operation_leases import assert_current_operation_lease


def atomic_write_text(path: Path, text: str, *, encoding: str = "utf-8") -> None:
    """Write text through a unique same-directory temporary file and replace."""

    assert_current_operation_lease()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        with temporary.open("w", encoding=encoding) as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        assert_current_operation_lease()
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def atomic_write_json(
    path: Path,
    payload: Any,
    *,
    ensure_ascii: bool = False,
    indent: int | None = 2,
) -> None:
    atomic_write_text(
        path,
        json.dumps(payload, ensure_ascii=ensure_ascii, indent=indent),
        encoding="utf-8",
    )


def atomic_replace_directory(source: Path, target: Path) -> None:
    """Replace a sibling directory and restore the previous target on failure."""

    assert_current_operation_lease()
    if source.parent.resolve() != target.parent.resolve():
        raise ValueError("Atomic directory replacement requires sibling paths.")
    if not source.is_dir():
        raise FileNotFoundError(f"Replacement directory is missing: {source}")

    backup = target.with_name(f".{target.name}.{uuid4().hex}.backup")
    moved_existing = False
    try:
        if target.exists():
            assert_current_operation_lease()
            os.replace(target, backup)
            moved_existing = True
        assert_current_operation_lease()
        os.replace(source, target)
    except Exception:
        if moved_existing and backup.exists() and not target.exists():
            os.replace(backup, target)
        raise
    finally:
        if backup.exists() and target.exists():
            shutil.rmtree(backup)
