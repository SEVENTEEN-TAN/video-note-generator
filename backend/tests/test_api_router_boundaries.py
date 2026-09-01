from __future__ import annotations

import ast
import inspect
from pathlib import Path

from fastapi.routing import APIRoute

from backend.app import main
from backend.app.main import app


EXPECTED_ROUTE_MODULES = {
    ("GET", "/api/ready"): "backend.app.api.runtime",
    ("GET", "/api/health"): "backend.app.api.runtime",
    ("GET", "/api/runtime"): "backend.app.api.runtime",
    ("POST", "/api/runtime/faster-whisper/cache/clear"): "backend.app.api.runtime",
    ("POST", "/api/runtime/cuda-dependencies/install"): "backend.app.api.runtime",
    ("GET", "/api/runtime/cuda-dependencies/install"): "backend.app.api.runtime",
    ("POST", "/api/runtime/local-dependencies/install"): "backend.app.api.runtime",
    ("GET", "/api/runtime/local-dependencies/install"): "backend.app.api.runtime",
    ("POST", "/api/models/faster-whisper/download"): "backend.app.api.runtime",
    ("GET", "/api/models/faster-whisper/download/{model_name}"): "backend.app.api.runtime",
    ("GET", "/api/settings"): "backend.app.api.settings",
    ("PATCH", "/api/settings"): "backend.app.api.settings",
    ("DELETE", "/api/settings"): "backend.app.api.settings",
    ("GET", "/api/jobs/{job_id}/preview/note"): "backend.app.api.downloads",
    ("GET", "/api/jobs/{job_id}/preview/subtitles"): "backend.app.api.downloads",
    ("GET", "/api/jobs/{job_id}/preview/note/{version_id}"): "backend.app.api.downloads",
    ("GET", "/api/jobs/{job_id}/assets/{asset_path:path}"): "backend.app.api.downloads",
    ("GET", "/api/jobs/{job_id}/download.zip"): "backend.app.api.downloads",
    ("GET", "/api/jobs/{job_id}/diagnostics.zip"): "backend.app.api.downloads",
    ("GET", "/api/jobs/{job_id}/quality-report"): "backend.app.api.review",
    ("GET", "/api/jobs/{job_id}/frame-candidates"): "backend.app.api.review",
    ("POST", "/api/jobs/{job_id}/frame-candidates/{candidate_id}/select"): "backend.app.api.review",
    ("POST", "/api/jobs/{job_id}/frame-candidates/{candidate_id}/reject"): "backend.app.api.review",
    ("GET", "/api/jobs/{job_id}/review-draft"): "backend.app.api.review",
    ("POST", "/api/jobs/{job_id}/review-assets/prepare"): "backend.app.api.review",
    ("PATCH", "/api/jobs/{job_id}/review-draft/paragraphs/{paragraph_id}"): "backend.app.api.review",
    ("POST", "/api/jobs/{job_id}/finalize"): "backend.app.api.review",
    ("POST", "/api/jobs/{job_id}/subtitles/confirm"): "backend.app.api.subtitles",
    ("POST", "/api/jobs/{job_id}/subtitles/regenerate"): "backend.app.api.subtitles",
    ("POST", "/api/jobs/{job_id}/transcript-corrections"): "backend.app.api.subtitles",
    ("POST", "/api/jobs/{job_id}/transcript-corrections/apply"): "backend.app.api.subtitles",
    ("GET", "/api/jobs/{job_id}/note-chunks"): "backend.app.api.notes",
    ("POST", "/api/jobs/{job_id}/note-chunks/{chunk_id}/regenerate"): "backend.app.api.notes",
    ("GET", "/api/jobs/{job_id}/note-versions"): "backend.app.api.notes",
    ("PATCH", "/api/jobs/{job_id}/note-versions"): "backend.app.api.notes",
    ("POST", "/api/jobs/{job_id}/note-versions"): "backend.app.api.notes",
    ("POST", "/api/jobs/frame-suggestion"): "backend.app.api.jobs",
    ("POST", "/api/jobs"): "backend.app.api.jobs",
    ("GET", "/api/jobs"): "backend.app.api.jobs",
    ("GET", "/api/jobs/{job_id}"): "backend.app.api.jobs",
    ("POST", "/api/jobs/{job_id}/cancel"): "backend.app.api.jobs",
    ("POST", "/api/jobs/{job_id}/transcription/resume"): "backend.app.api.jobs",
    ("GET", "/api/jobs/{job_id}/storage"): "backend.app.api.jobs",
    ("DELETE", "/api/jobs/{job_id}/transcription/cache"): "backend.app.api.jobs",
    ("DELETE", "/api/jobs/{job_id}"): "backend.app.api.jobs",
}


def test_extracted_routes_are_registered_from_domain_routers() -> None:
    registered = {
        (method, route.path): route.endpoint.__module__
        for route in app.routes
        if isinstance(route, APIRoute)
        for method in route.methods or set()
    }

    for route_key, expected_module in EXPECTED_ROUTE_MODULES.items():
        assert registered.get(route_key) == expected_module


def test_domain_router_modules_do_not_import_main() -> None:
    api_root = Path(main.__file__).resolve().parent / "api"

    for filename in ("downloads.py", "jobs.py", "notes.py", "review.py", "runtime.py", "settings.py", "subtitles.py"):
        tree = ast.parse((api_root / filename).read_text(encoding="utf-8"))
        imports = [
            node.module or ""
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
        ]
        assert all(not module.endswith("main") for module in imports)


def test_main_is_only_the_registration_point_for_extracted_routes() -> None:
    source = inspect.getsource(main)

    assert "app.include_router(runtime_router)" in source
    assert "app.include_router(settings_router)" in source
    assert "app.include_router(downloads_router)" in source
    assert "app.include_router(review_router)" in source
    assert "app.include_router(subtitles_router)" in source
    assert "app.include_router(notes_router)" in source
    assert "app.include_router(jobs_router)" in source
    for _method, path in EXPECTED_ROUTE_MODULES:
        assert f'"{path}"' not in source
