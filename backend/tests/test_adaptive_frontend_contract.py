from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_frontend_exposes_adaptive_modes_work_progress_and_resume() -> None:
    types_source = (ROOT / "frontend" / "src" / "types.ts").read_text(encoding="utf-8")
    app_source = (ROOT / "frontend" / "src" / "App.tsx").read_text(encoding="utf-8")

    assert 'export type PerformanceMode = "fast" | "balanced" | "accurate";' in types_source
    assert "export type TranscriptionWorkProgress" in types_source
    assert "work_progress?: TranscriptionWorkProgress | null" in types_source
    assert 'formData.append("performance_mode", performanceMode)' in app_source
    assert '<option value="fast">' in app_source
    assert '<option value="balanced">' in app_source
    assert '<option value="accurate">' in app_source
    assert "继续转写" in app_source
    assert "/transcription/resume" in app_source
    assert "completed_chunks" in app_source
    assert "eta_seconds" in app_source
