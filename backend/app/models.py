from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator


class JobStatus(str, Enum):
    pending = "pending"
    running = "running"
    succeeded = "succeeded"
    failed = "failed"


class NoteLanguage(str, Enum):
    zh = "zh"
    en = "en"
    follow = "follow"


class NoteStyle(str, Enum):
    minimal = "minimal"
    detailed = "detailed"
    tutorial = "tutorial"
    academic = "academic"
    task_oriented = "task_oriented"
    meeting_minutes = "meeting_minutes"


class TranscriptionMode(str, Enum):
    audio_transcriptions = "audio_transcriptions"
    chat_audio = "chat_audio"
    local_faster_whisper = "local_faster_whisper"


class LocalWhisperDevice(str, Enum):
    auto = "auto"
    cpu = "cpu"
    cuda = "cuda"


class LocalWhisperComputeType(str, Enum):
    default = "default"
    int8 = "int8"
    int8_float16 = "int8_float16"
    float16 = "float16"
    float32 = "float32"


class JobConfig(BaseModel):
    transcription_mode: TranscriptionMode = TranscriptionMode.audio_transcriptions
    transcription_api_key: str = ""
    transcription_base_url: str = "https://api.openai.com/v1"
    transcription_model: str = "whisper-1"
    local_whisper_device: LocalWhisperDevice | str = ""
    local_whisper_compute_type: LocalWhisperComputeType | str = ""
    note_api_key: str
    note_base_url: str = "https://api.openai.com/v1"
    note_model: str = "gpt-5.5"
    note_language: NoteLanguage
    note_style: NoteStyle = NoteStyle.detailed
    extras: str = ""
    frame_limit: int = Field(default=6, ge=1, le=24)
    original_filename: str

    @field_validator(
        "transcription_model",
        "note_api_key",
        "note_base_url",
        "note_model",
    )
    @classmethod
    def require_non_empty(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("This field is required.")
        return value

    @field_validator("local_whisper_device", "local_whisper_compute_type")
    @classmethod
    def normalize_local_whisper_runtime(cls, value: str | Enum) -> str:
        return str(value.value if isinstance(value, Enum) else value).strip()

    @field_validator("local_whisper_device")
    @classmethod
    def validate_local_whisper_device(cls, value: str) -> str:
        if value not in {"", "auto", "cpu", "cuda"}:
            raise ValueError("local_whisper_device must be auto, cpu, or cuda.")
        return value

    @field_validator("local_whisper_compute_type")
    @classmethod
    def validate_local_whisper_compute_type(cls, value: str) -> str:
        if value not in {"", "default", "int8", "int8_float16", "float16", "float32"}:
            raise ValueError("local_whisper_compute_type is not supported.")
        return value

    @field_validator("extras")
    @classmethod
    def normalize_extras(cls, value: str) -> str:
        value = value.strip()
        if len(value) > 2000:
            raise ValueError("extras must be 2000 characters or fewer.")
        return value

    @model_validator(mode="after")
    def require_remote_transcription_credentials(self) -> "JobConfig":
        if self.transcription_mode != TranscriptionMode.local_faster_whisper:
            if not self.transcription_api_key.strip():
                raise ValueError("Transcription API Key is required for remote transcription modes.")
            if not self.transcription_base_url.strip():
                raise ValueError("Transcription Base URL is required for remote transcription modes.")
        return self


class TranscriptSegment(BaseModel):
    start: float
    end: float
    text: str


class TranscriptPayload(BaseModel):
    text: str = ""
    segments: list[TranscriptSegment] = Field(default_factory=list)


class Chapter(BaseModel):
    title: str
    start_time: float
    end_time: float
    bullets: list[str] = Field(default_factory=list)
    detail: str = ""
    quote_times: list[str] = Field(default_factory=list)


class KeyMoment(BaseModel):
    time: float
    reason: str
    chapter_index: int | None = None
    frame_path: str | None = None


class NoteDraft(BaseModel):
    title: str
    summary: str
    chapters: list[Chapter] = Field(default_factory=list)
    key_moments: list[KeyMoment] = Field(default_factory=list)
    recommended_frame_count: int | None = Field(default=None, ge=1, le=12)
    key_takeaways: list[str] = Field(default_factory=list)
    action_items: list[str] = Field(default_factory=list)
    markdown_body: str = ""


class FrameSuggestion(BaseModel):
    recommended_frame_count: int
    candidate_count: int
    reasons: list[str] = Field(default_factory=list)


class NoteVersion(BaseModel):
    id: str
    label: str
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    note_style: NoteStyle
    note_language: str
    note_model: str
    note_base_url: str
    frame_limit: int
    note_path: str
    frame_dir: str
    selected: bool = True
    active: bool = False
    extras_present: bool = False
    extras_length: int = 0


class NoteVersionIndex(BaseModel):
    active_version_id: str | None = None
    selected_version_ids: list[str] = Field(default_factory=list)
    versions: list[NoteVersion] = Field(default_factory=list)


class NoteVersionSelection(BaseModel):
    active_version_id: str | None = None
    selected_version_ids: list[str] = Field(default_factory=list)


class Artifact(BaseModel):
    label: str
    path: str
    kind: Literal["audio", "subtitle", "markdown", "image", "json", "zip"]
    asset_url: str


class JobPublicState(BaseModel):
    job_id: str
    status: JobStatus
    step: str
    progress: int
    error: str | None = None
    artifacts: list[Artifact] = Field(default_factory=list)
    step_started_at: str | None = None
    updated_at: str | None = None
    stage_elapsed_seconds: float = 0
