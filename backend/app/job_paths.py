from __future__ import annotations

import json
from pathlib import Path


class InvalidJobIdError(ValueError):
    pass


class JobDirectoryNotFoundError(FileNotFoundError):
    pass


class InvalidJobAssetPathError(ValueError):
    pass


class JobArtifactNotFoundError(FileNotFoundError):
    pass


def resolve_job_dir(outputs_root: Path, job_id: str) -> Path:
    if not job_id or job_id in {".", ".."} or "/" in job_id or "\\" in job_id or ":" in job_id:
        raise InvalidJobIdError("Invalid job id.")

    resolved_root = outputs_root.resolve()
    job_dir = (resolved_root / job_id).resolve()
    if job_dir.parent != resolved_root or job_dir.name != job_id:
        raise InvalidJobIdError("Invalid job id.")
    if not job_dir.exists():
        raise JobDirectoryNotFoundError("Job not found.")
    return job_dir


def resolve_job_path(outputs_root: Path, job_id: str, relative_path: str) -> Path:
    job_dir = resolve_job_dir(outputs_root, job_id)
    file_path = (job_dir / relative_path).resolve()
    if job_dir not in file_path.parents and file_path != job_dir:
        raise InvalidJobAssetPathError("Invalid asset path.")
    return file_path


def read_job_text(outputs_root: Path, job_id: str, relative_path: str) -> str:
    file_path = resolve_job_path(outputs_root, job_id, relative_path)
    if not file_path.exists() or not file_path.is_file():
        raise JobArtifactNotFoundError(f"{relative_path} is not ready.")
    return file_path.read_text(encoding="utf-8-sig")


def read_job_metadata(job_dir: Path) -> dict:
    metadata_path = job_dir / "metadata.json"
    if not metadata_path.exists():
        return {}
    payload = json.loads(metadata_path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}
