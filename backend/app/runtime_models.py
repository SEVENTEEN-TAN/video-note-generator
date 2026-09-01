from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


RuntimePathSource = Literal["environment", "settings", "default", "missing"]
PythonPackageInstallMode = Literal["default", "user"]
RuntimeProbeSource = Literal["internal", "external"]


class RuntimeCapability(BaseModel):
    available: bool
    reason: str
    requires_credentials: bool = False


class RuntimeCapabilities(BaseModel):
    video_processing: RuntimeCapability
    uploaded_subtitle: RuntimeCapability
    local_transcription_cpu: RuntimeCapability
    local_transcription_cuda: RuntimeCapability
    audio_transcriptions: RuntimeCapability
    chat_audio: RuntimeCapability
    note_generation: RuntimeCapability


class FFmpegRuntimeStatus(BaseModel):
    available: bool
    path: str | None = None
    install_hint: str


class FasterWhisperRuntimeStatus(BaseModel):
    available: bool
    internal_available: bool
    internal_import_error: str
    python_available: bool
    external_python_path: str | None = None
    external_python_source: RuntimePathSource
    external_python_error: str
    python_package_install_mode: PythonPackageInstallMode
    external_worker_path: str
    external_worker_available: bool
    worker_ready: bool
    worker_error: str
    worker_error_code: str
    worker_probe_error: str
    ctranslate2_available: bool
    ctranslate2_version: str
    cuda_available: bool
    cuda_device_count: int | None = None
    cuda_runtime_available: bool
    cuda_error: str
    cuda_source: RuntimeProbeSource
    cuda_runtime_hint: str
    cuda_dll_dirs: list[str] = Field(default_factory=list)
    import_error: str
    install_hint: str
    model_available: bool
    ready_for_cpu: bool
    ready_for_cuda: bool


class LocalModelsRuntimeStatus(BaseModel):
    root: str
    root_source: RuntimePathSource
    models: list[str] = Field(default_factory=list)
    hint: str


class SettingsStorageStatus(BaseModel):
    path: str
    schema_version: int
    secret_provider: str
    secrets_encrypted: bool
    warning: str
    error: str = ""


class RuntimeState(BaseModel):
    ok: bool
    capabilities: RuntimeCapabilities
    ffmpeg: FFmpegRuntimeStatus
    faster_whisper: FasterWhisperRuntimeStatus
    local_models: LocalModelsRuntimeStatus
    settings: SettingsStorageStatus


class HealthState(BaseModel):
    ok: bool
    runtime_ok: bool
    ffmpeg_available: bool
    ffmpeg_path: str | None = None
    runtime: RuntimeState
