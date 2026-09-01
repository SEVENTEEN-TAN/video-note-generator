from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_local_runtime_requirements_include_faster_whisper_import_dependency() -> None:
    requirements = (ROOT / "backend" / "requirements-local.txt").read_text(encoding="utf-8").splitlines()

    assert any(line.startswith("requests") for line in requirements)


def test_frontend_allows_pinned_esbuild_install_script() -> None:
    package = json.loads((ROOT / "frontend" / "package.json").read_text(encoding="utf-8"))

    assert package["allowScripts"]["esbuild@0.25.12"] is True


def test_dev_init_script_covers_backend_frontend_and_optional_verification() -> None:
    script = (ROOT / "scripts" / "init-dev.ps1").read_text(encoding="utf-8")

    assert "python -m venv" in script
    assert "backend/requirements.txt" in script
    assert "npm install --allow-remote=all" in script
    assert "import faster_whisper" in script
    assert "scripts/export-openapi.py" in script
    assert "npm --prefix frontend run generate:api" in script
    assert "python.exe -m pytest backend/tests" not in script
    assert "$VenvPython -m pytest backend/tests" in script
    assert "npm --prefix frontend run build" in script


def test_desktop_build_refreshes_openapi_types_before_frontend_build() -> None:
    script = (ROOT / "scripts" / "build-desktop.ps1").read_text(encoding="utf-8")

    export_index = script.index("python scripts/export-openapi.py")
    generate_index = script.index("npm --prefix frontend run generate:api")
    build_index = script.index("npm --prefix frontend run build")

    assert export_index < generate_index < build_index


def test_desktop_release_uses_node24_compatible_official_actions() -> None:
    workflow = (ROOT / ".github" / "workflows" / "desktop-release.yml").read_text(encoding="utf-8")

    assert "actions/checkout@v5" in workflow
    assert "actions/setup-node@v5" in workflow
    assert "actions/setup-python@v6" in workflow
    assert "actions/upload-artifact@v6" in workflow


def test_desktop_release_creates_a_unique_versioned_release_for_each_build() -> None:
    workflow = (ROOT / ".github" / "workflows" / "desktop-release.yml").read_text(encoding="utf-8")

    assert "Publish versioned release" in workflow
    assert "github.run_number" in workflow
    assert "github.run_attempt" in workflow
    assert 'gh release create $tag $zip' in workflow
    assert "--target $env:RELEASE_SHA" in workflow
    assert "--latest" in workflow
    assert "desktop-latest" not in workflow
    assert "git push --force" not in workflow
