from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_frontend_exposes_adaptive_modes_work_progress_and_resume() -> None:
    types_source = (ROOT / "frontend" / "src" / "types.ts").read_text(encoding="utf-8")
    generated_source = (ROOT / "frontend" / "src" / "api.generated.ts").read_text(encoding="utf-8")
    app_source = (ROOT / "frontend" / "src" / "App.tsx").read_text(encoding="utf-8")
    api_source = (ROOT / "frontend" / "src" / "api.ts").read_text(encoding="utf-8")
    creation_source = (ROOT / "frontend" / "src" / "useJobCreation.ts").read_text(encoding="utf-8")
    lifecycle_source = (ROOT / "frontend" / "src" / "useJobLifecycle.ts").read_text(encoding="utf-8")
    task_config_source = (ROOT / "frontend" / "src" / "TaskConfigPanel.tsx").read_text(encoding="utf-8")
    local_settings_source = (ROOT / "frontend" / "src" / "SettingsLocalTranscriptionSection.tsx").read_text(
        encoding="utf-8"
    )

    assert 'export type PerformanceMode = ApiSchemas["PerformanceMode"];' in types_source
    assert 'PerformanceMode: "fast" | "balanced" | "accurate";' in generated_source
    assert 'export type TranscriptionWorkProgress = ApiSchemas["TranscriptionWorkProgress"];' in types_source
    assert 'work_progress?: components["schemas"]["TranscriptionWorkProgress"] | null;' in generated_source
    assert 'formData.append("performance_mode", currentSettings.performance_mode)' in creation_source
    assert '<option value="fast">' in local_settings_source
    assert '<option value="balanced">' in local_settings_source
    assert '<option value="accurate">' in local_settings_source
    assert "继续转写" in task_config_source
    assert "/transcription/resume" in api_source
    assert "resumeJobTranscription(requestJobId)" in lifecycle_source
    assert "completed_chunks" in app_source
    assert "eta_seconds" in app_source
