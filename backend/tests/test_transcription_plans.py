from __future__ import annotations

from backend.app.models import JobConfig, NoteLanguage, PerformanceMode, TranscriptionMode
from backend.app.transcription_plans import HardwareProfile, plan_fingerprint, resolve_execution_plan


def make_local_config(
    *,
    performance_mode: PerformanceMode | str = PerformanceMode.balanced,
    device: str = "auto",
    compute_type: str = "default",
) -> JobConfig:
    return JobConfig(
        transcription_mode=TranscriptionMode.local_faster_whisper,
        transcription_model="small",
        local_whisper_device=device,
        local_whisper_compute_type=compute_type,
        performance_mode=performance_mode,
        note_api_key="note-key",
        note_model="gpt-5.5",
        note_language=NoteLanguage.zh,
        original_filename="lesson.mp4",
    )


def test_balanced_cpu_long_plan_uses_int8_and_checkpoints() -> None:
    plan = resolve_execution_plan(
        make_local_config(),
        duration_seconds=3 * 3600,
        hardware=HardwareProfile(8, 16 * 1024**3, False, None),
    )

    assert plan.performance_mode == PerformanceMode.balanced.value
    assert plan.device == "cpu"
    assert plan.compute_type == "int8"
    assert plan.chunk_seconds == 600
    assert (plan.beam_size, plan.best_of) == (3, 2)
    assert plan.checkpoint_enabled is True


def test_balanced_cuda_plan_prefers_float16() -> None:
    plan = resolve_execution_plan(
        make_local_config(),
        duration_seconds=3600,
        hardware=HardwareProfile(12, 32 * 1024**3, True, 8 * 1024**3),
    )

    assert (plan.device, plan.compute_type, plan.chunk_seconds) == ("cuda", "float16", 900)


def test_explicit_cpu_runtime_overrides_available_cuda() -> None:
    plan = resolve_execution_plan(
        make_local_config(performance_mode=PerformanceMode.accurate, device="cpu", compute_type="int8"),
        duration_seconds=1200,
        hardware=HardwareProfile(8, 16 * 1024**3, True, 8 * 1024**3),
    )

    assert (plan.device, plan.compute_type, plan.chunk_seconds) == ("cpu", "int8", 0)
    assert (plan.beam_size, plan.best_of) == (5, 3)


def test_fast_and_accurate_modes_choose_expected_decode_settings() -> None:
    hardware = HardwareProfile(8, 16 * 1024**3, False, None)
    fast = resolve_execution_plan(make_local_config(performance_mode=PerformanceMode.fast), 3600, hardware)
    accurate = resolve_execution_plan(make_local_config(performance_mode=PerformanceMode.accurate), 3600, hardware)

    assert (fast.beam_size, fast.best_of) == (1, 1)
    assert (accurate.beam_size, accurate.best_of) == (5, 3)


def test_plan_fingerprint_is_stable_and_changes_with_result_settings() -> None:
    hardware = HardwareProfile(8, 16 * 1024**3, False, None)
    balanced = resolve_execution_plan(make_local_config(), 3600, hardware)
    same = resolve_execution_plan(make_local_config(), 3600, hardware)
    accurate = resolve_execution_plan(make_local_config(performance_mode=PerformanceMode.accurate), 3600, hardware)

    assert plan_fingerprint(balanced) == plan_fingerprint(same)
    assert plan_fingerprint(balanced) != plan_fingerprint(accurate)
