from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_build_script_verifies_final_executable_and_removes_intermediate_exe() -> None:
    script = (ROOT / "scripts" / "build-desktop.ps1").read_text(encoding="utf-8")

    assert "$FinalExe = Join-Path $Root \"dist/VideoNoteGenerator/VideoNoteGenerator.exe\"" in script
    assert "$FinalInternalDir = Join-Path $Root \"dist/VideoNoteGenerator/_internal\"" in script
    assert "Test-Path $FinalInternalDir" in script
    assert "$FinalPythonDll = Get-ChildItem -LiteralPath $FinalInternalDir -Filter \"python*.dll\"" in script
    assert "$IntermediateExe = Join-Path $Root \"build/VideoNoteGenerator/VideoNoteGenerator.exe\"" in script
    assert "Remove-Item -LiteralPath $IntermediateExe -Force" in script
