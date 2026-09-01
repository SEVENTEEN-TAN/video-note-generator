from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from backend.app.main import app


REPO_ROOT = Path(__file__).resolve().parents[2]
OPENAPI_PATH = REPO_ROOT / "frontend" / "openapi.json"
GENERATED_TYPES_PATH = REPO_ROOT / "frontend" / "src" / "api.generated.ts"
TYPE_ALIASES_PATH = REPO_ROOT / "frontend" / "src" / "types.ts"


def test_exported_openapi_document_matches_fastapi_schema() -> None:
    exported = json.loads(OPENAPI_PATH.read_text(encoding="utf-8"))

    assert exported == app.openapi()


def test_generated_types_record_current_openapi_fingerprint() -> None:
    schema_hash = hashlib.sha256(OPENAPI_PATH.read_bytes()).hexdigest()
    generated = GENERATED_TYPES_PATH.read_text(encoding="utf-8")
    match = re.match(r"// OpenAPI-SHA256: ([0-9a-f]{64})\n", generated)

    assert match is not None
    assert match.group(1) == schema_hash
    assert "export interface components" in generated
    assert "UserSettings:" in generated
    assert "JobPublicState:" in generated
    assert "RuntimeState:" in generated
    assert "HealthState:" in generated
    assert "NoteChunkIndex:" in generated


def test_frontend_api_dtos_are_aliases_of_generated_components() -> None:
    aliases = TYPE_ALIASES_PATH.read_text(encoding="utf-8")

    assert 'import type { components } from "./api.generated";' in aliases
    assert 'export type UserSettings = ApiSchemas["UserSettings"];' in aliases
    assert 'export type JobState = WithRequired<ApiSchemas["JobPublicState"], "artifacts">;' in aliases
    assert 'export type FrameCandidate = WithRequired<ApiSchemas["FrameCandidate"], "risk_flags">;' in aliases
    assert 'export type RuntimeCapability = ApiSchemas["RuntimeCapability"];' in aliases
    assert 'export type RuntimeState = Omit<ApiSchemas["RuntimeState"], "faster_whisper" | "local_models"> & {' in aliases
    assert 'export type NoteChunkMeta = ApiSchemas["NoteChunkMeta"];' in aliases
    assert 'export type NoteChunkIndex = Omit<ApiSchemas["NoteChunkIndex"], "chunks"> & {' in aliases
    assert "export type UserSettings = {" not in aliases
    assert "export type JobState = {" not in aliases
    assert "export type RuntimeState = {" not in aliases


def test_runtime_health_and_note_chunks_publish_response_schemas() -> None:
    schema = app.openapi()
    paths = schema["paths"]

    assert (
        paths["/api/runtime"]["get"]["responses"]["200"]["content"]["application/json"]["schema"]["$ref"]
        == "#/components/schemas/RuntimeState"
    )
    assert (
        paths["/api/health"]["get"]["responses"]["200"]["content"]["application/json"]["schema"]["$ref"]
        == "#/components/schemas/HealthState"
    )
    assert (
        paths["/api/jobs/{job_id}/note-chunks"]["get"]["responses"]["200"]["content"]["application/json"]["schema"]["$ref"]
        == "#/components/schemas/NoteChunkIndex"
    )
