from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass

from .models import JobConfig, PerformanceMode


@dataclass(frozen=True)
class HardwareProfile:
    cpu_count: int
    memory_bytes: int | None
    cuda_available: bool
    cuda_memory_bytes: int | None


@dataclass(frozen=True)
class TranscriptionExecutionPlan:
    performance_mode: str
    device: str
    compute_type: str
    cpu_threads: int
    num_workers: int
    beam_size: int
    best_of: int
    vad_filter: bool
    vad_min_silence_ms: int
    vad_threshold: float
    chunk_seconds: int
    chunk_overlap_seconds: float
    checkpoint_enabled: bool
    transcription_model: str = ""
    transcription_language: str = "auto"


_DECODE_PRESETS: dict[str, tuple[int, int]] = {
    PerformanceMode.fast.value: (1, 1),
    PerformanceMode.balanced.value: (3, 2),
    PerformanceMode.accurate.value: (5, 3),
}


def resolve_execution_plan(
    config: JobConfig,
    duration_seconds: float,
    hardware: HardwareProfile,
) -> TranscriptionExecutionPlan:
    mode = _performance_mode_value(config.performance_mode)
    device = _resolve_device(str(config.local_whisper_device or "").strip(), hardware)
    compute_type = _resolve_compute_type(
        str(config.local_whisper_compute_type or "").strip(),
        device,
    )
    beam_size, best_of = _DECODE_PRESETS[mode]
    chunk_seconds = _chunk_seconds(max(0.0, float(duration_seconds or 0.0)))
    cpu_count = max(1, int(hardware.cpu_count or 1))

    return TranscriptionExecutionPlan(
        performance_mode=mode,
        device=device,
        compute_type=compute_type,
        cpu_threads=max(1, min(cpu_count, 8)),
        num_workers=1,
        beam_size=beam_size,
        best_of=best_of,
        vad_filter=True,
        vad_min_silence_ms=500,
        vad_threshold=0.5,
        chunk_seconds=chunk_seconds,
        chunk_overlap_seconds=0.0 if chunk_seconds == 0 else 1.0,
        checkpoint_enabled=True,
        transcription_model=config.transcription_model.strip() or "small",
        transcription_language=str(config.transcription_language or "auto"),
    )


def plan_fingerprint(plan: TranscriptionExecutionPlan) -> str:
    payload = json.dumps(asdict(plan), sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _performance_mode_value(value: PerformanceMode | str) -> str:
    normalized = value.value if isinstance(value, PerformanceMode) else str(value).strip()
    if normalized not in _DECODE_PRESETS:
        return PerformanceMode.balanced.value
    return normalized


def _resolve_device(configured: str, hardware: HardwareProfile) -> str:
    if configured in {"cpu", "cuda"}:
        return configured
    return "cuda" if hardware.cuda_available else "cpu"


def _resolve_compute_type(configured: str, device: str) -> str:
    if configured and configured != "default":
        return configured
    return "float16" if device == "cuda" else "int8"


def _chunk_seconds(duration_seconds: float) -> int:
    if duration_seconds <= 1800:
        return 0
    if duration_seconds <= 7200:
        return 900
    return 600
