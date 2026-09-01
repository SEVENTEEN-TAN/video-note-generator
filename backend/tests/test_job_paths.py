from __future__ import annotations

import pytest

from backend.app.job_paths import (
    InvalidJobAssetPathError,
    InvalidJobIdError,
    JobArtifactNotFoundError,
    JobDirectoryNotFoundError,
    read_job_text,
    resolve_job_dir,
    resolve_job_path,
)


@pytest.mark.parametrize("job_id", ["", ".", "..", "../job", "nested/job", "C:job"])
def test_resolve_job_dir_rejects_invalid_job_ids(tmp_path, job_id: str) -> None:
    with pytest.raises(InvalidJobIdError):
        resolve_job_dir(tmp_path, job_id)


def test_resolve_job_dir_distinguishes_missing_job(tmp_path) -> None:
    with pytest.raises(JobDirectoryNotFoundError, match="Job not found"):
        resolve_job_dir(tmp_path, "missing-job")


def test_resolve_job_path_rejects_directory_traversal(tmp_path) -> None:
    (tmp_path / "job-1").mkdir()

    with pytest.raises(InvalidJobAssetPathError):
        resolve_job_path(tmp_path, "job-1", "../outside.txt")


def test_read_job_text_accepts_utf8_bom_and_reports_missing_artifact(tmp_path) -> None:
    job_dir = tmp_path / "job-1"
    job_dir.mkdir()
    (job_dir / "note.md").write_text("# 中文", encoding="utf-8-sig")

    assert read_job_text(tmp_path, "job-1", "note.md") == "# 中文"
    with pytest.raises(JobArtifactNotFoundError, match="subtitles.md is not ready"):
        read_job_text(tmp_path, "job-1", "subtitles.md")
