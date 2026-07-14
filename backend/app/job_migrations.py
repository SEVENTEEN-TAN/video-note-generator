from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

CURRENT_JOB_SCHEMA_VERSION = 1


def _schema_version(value: object) -> int:
    if isinstance(value, bool):
        return 0
    try:
        version = int(value or 0)
    except (TypeError, ValueError):
        return 0
    return max(0, version)


def _write_metadata_atomically(metadata_path: Path, payload: dict) -> None:
    temp_path = metadata_path.with_name(f".{metadata_path.name}.{uuid4().hex}.tmp")
    try:
        temp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        temp_path.replace(metadata_path)
    finally:
        try:
            temp_path.unlink(missing_ok=True)
        except OSError:
            pass


def migrate_job_directory(job_dir: Path) -> dict:
    """Upgrade persisted job metadata in place and return the normalized payload."""
    metadata_path = job_dir / "metadata.json"
    if not metadata_path.exists():
        return {}
    try:
        payload = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(payload, dict):
        return {}
    version = _schema_version(payload.get("schema_version"))
    if version > CURRENT_JOB_SCHEMA_VERSION:
        return payload
    if version < CURRENT_JOB_SCHEMA_VERSION:
        payload["schema_version"] = CURRENT_JOB_SCHEMA_VERSION
        try:
            _write_metadata_atomically(metadata_path, payload)
        except OSError:
            # History reads should remain available even when an old job directory is read-only.
            pass
    return payload
