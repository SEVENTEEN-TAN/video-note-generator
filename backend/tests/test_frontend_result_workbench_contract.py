from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_result_workbench_receives_domain_grouped_inputs() -> None:
    app_source = (ROOT / "frontend" / "src" / "App.tsx").read_text(encoding="utf-8")
    workbench_source = (ROOT / "frontend" / "src" / "ResultWorkbench.tsx").read_text(encoding="utf-8")

    for grouped_prop in (
        "context",
        "downloads",
        "frames",
        "note",
        "subtitle",
    ):
        assert f"  {grouped_prop}: {{" in workbench_source
        assert f"            {grouped_prop}={{{{" in app_source

    for legacy_flat_prop in (
        "activeWorkbench={activeWorkbench}",
        "correctionError={correctionError}",
        "frameCandidateIndex={frameCandidateIndex}",
        "notePreview={notePreview}",
        "subtitlePreview={subtitlePreview}",
    ):
        assert legacy_flat_prop not in app_source

    assert "const { activeWorkbench, currentJobSummary, isBusy, job, onWorkbenchChange } = context;" in workbench_source
    assert "candidateIndex: frameCandidateIndex" in workbench_source
    assert "versions: noteVersions" in workbench_source
    assert "preview: subtitlePreview" in workbench_source


def test_result_workbench_keeps_network_and_job_identity_outside_the_view() -> None:
    workbench_source = (ROOT / "frontend" / "src" / "ResultWorkbench.tsx").read_text(encoding="utf-8")

    assert "useJobLifecycle" not in workbench_source
    assert "fetchJob(" not in workbench_source
    assert "setJob(" not in workbench_source
