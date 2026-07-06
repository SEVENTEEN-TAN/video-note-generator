from __future__ import annotations

import re
from datetime import datetime, timezone
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field, ValidationInfo, field_validator, model_validator


class JobStatus(str, Enum):
    pending = "pending"
    running = "running"
    awaiting_subtitle_confirmation = "awaiting_subtitle_confirmation"
    awaiting_note_review = "awaiting_note_review"
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


class TranscriptionLanguage(str, Enum):
    auto = "auto"
    zh = "zh"
    en = "en"


class JobConfig(BaseModel):
    transcription_mode: TranscriptionMode = TranscriptionMode.audio_transcriptions
    transcription_api_key: str = ""
    transcription_base_url: str = "https://api.openai.com/v1"
    transcription_model: str = "whisper-1"
    local_whisper_device: LocalWhisperDevice | str = ""
    local_whisper_compute_type: LocalWhisperComputeType | str = ""
    transcription_language: TranscriptionLanguage | str = TranscriptionLanguage.auto
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

    @field_validator("transcription_language")
    @classmethod
    def normalize_transcription_language(cls, value: TranscriptionLanguage | str) -> str:
        return str(value.value if isinstance(value, Enum) else value).strip()

    @field_validator("transcription_language")
    @classmethod
    def validate_transcription_language(cls, value: str) -> str:
        if value not in {"auto", "zh", "en"}:
            raise ValueError("transcription_language must be auto, zh, or en.")
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


class QualityScores(BaseModel):
    coverage: float = Field(ge=0, le=1)
    structure: float = Field(ge=0, le=1)
    frames: float = Field(ge=0, le=1)
    stability: float = Field(ge=0, le=1)


class QualityIssue(BaseModel):
    severity: Literal["info", "warning", "error"]
    type: str
    message: str
    chapter_index: int | None = None
    frame_ids: list[str] = Field(default_factory=list)


class ChapterQualityReport(BaseModel):
    chapter_index: int
    title: str
    start_time: float
    end_time: float
    transcript_chars: int
    note_chars: int
    selected_frame_count: int
    issues: list[str] = Field(default_factory=list)


class QualityReport(BaseModel):
    status: Literal["ready", "review_recommended", "needs_attention"]
    scores: QualityScores
    issues: list[QualityIssue] = Field(default_factory=list)
    chapter_reports: list[ChapterQualityReport] = Field(default_factory=list)


class FrameCandidate(BaseModel):
    id: str
    chapter_index: int
    time: float
    path: str
    reason: str
    source: Literal["note_key_moment", "chapter_fallback"]
    hash: str
    duplicate_of: str | None = None
    similarity: float = Field(ge=0, le=1)
    risk_flags: list[str] = Field(default_factory=list)
    selected: bool = False
    rejected: bool = False


class FrameCandidateChapterContext(BaseModel):
    chapter_index: int
    title: str
    start_time: float
    end_time: float
    note_excerpt: str = ""
    subtitle_excerpt: str = ""


class FrameCandidateIndex(BaseModel):
    candidates: list[FrameCandidate] = Field(default_factory=list)
    chapter_contexts: list[FrameCandidateChapterContext] = Field(default_factory=list)


class TranscriptCorrectionRequest(BaseModel):
    note_api_key: str
    note_base_url: str = "https://api.openai.com/v1"
    note_model: str = "gpt-5.5"
    instructions: str = ""


class TranscriptCorrectionSegment(BaseModel):
    index: int
    start: float
    end: float
    original_text: str
    corrected_text: str
    changed: bool = False


class TranscriptCorrectionPreview(BaseModel):
    job_id: str = ""
    changed_count: int
    segments: list[TranscriptCorrectionSegment] = Field(default_factory=list)


class TranscriptCorrectionApplyRequest(BaseModel):
    note_language: NoteLanguage
    note_style: NoteStyle = NoteStyle.detailed
    extras: str = ""
    note_api_key: str
    note_base_url: str = "https://api.openai.com/v1"
    note_model: str = "gpt-5.5"
    frame_limit: int = Field(default=6, ge=1, le=24)


def _parse_model_timestamp(value: object, range_part: str | None = None) -> object:
    if not isinstance(value, str):
        return value
    stripped = value.strip().replace("：", ":")
    if range_part:
        parts = re.split(r"\s*(?:-|–|—|~|至|到)\s*", stripped, maxsplit=1)
        if len(parts) == 2:
            stripped = parts[1 if range_part == "end" else 0].strip()
    match = re.fullmatch(r"(?:(\d+):)?(\d{1,2}):(\d{2})(?:\.(\d+))?", stripped)
    if not match:
        return value
    hours, minutes, seconds, fraction = match.groups()
    hour_value = int(hours or 0)
    minute_value = int(minutes)
    second_value = int(seconds)
    if minute_value >= 60 or second_value >= 60:
        raise ValueError("Timestamp minutes and seconds must be below 60.")
    total = hour_value * 3600 + minute_value * 60 + second_value
    if fraction:
        return total + float(f"0.{fraction}")
    return float(total)


def _list_if_single_object(value: object) -> object:
    if value is None:
        return []
    if isinstance(value, dict):
        return [value]
    return value


def _string_list_if_scalar(value: object) -> object:
    if value is None:
        return []
    if isinstance(value, str):
        value = value.strip()
        return [value] if value else []
    return value


def _empty_string_if_none(value: object) -> object:
    return "" if value is None else value


class Chapter(BaseModel):
    title: str
    start_time: float = 0.0
    end_time: float = 0.0
    bullets: list[str] = Field(default_factory=list)
    detail: str = ""
    quote_times: list[str] = Field(default_factory=list)

    @field_validator("start_time", "end_time", mode="before")
    @classmethod
    def normalize_model_timestamps(cls, value: object, info: ValidationInfo) -> object:
        return _parse_model_timestamp(value, range_part="end" if info.field_name == "end_time" else "start")

    @field_validator("bullets", "quote_times", mode="before")
    @classmethod
    def normalize_string_lists(cls, value: object) -> object:
        return _string_list_if_scalar(value)

    @field_validator("detail", mode="before")
    @classmethod
    def normalize_null_detail(cls, value: object) -> object:
        return _empty_string_if_none(value)


class KeyMoment(BaseModel):
    time: float
    reason: str
    chapter_index: int | None = None
    frame_path: str | None = None

    @field_validator("time", mode="before")
    @classmethod
    def normalize_model_timestamp(cls, value: object) -> object:
        return _parse_model_timestamp(value, range_part="start")


class NoteDraft(BaseModel):
    title: str
    summary: str = ""
    chapters: list[Chapter] = Field(default_factory=list)
    key_moments: list[KeyMoment] = Field(default_factory=list)
    recommended_frame_count: int | None = Field(default=None, ge=1, le=24)
    key_takeaways: list[str] = Field(default_factory=list)
    action_items: list[str] = Field(default_factory=list)
    markdown_body: str = ""

    @field_validator("recommended_frame_count", mode="before")
    @classmethod
    def normalize_empty_frame_recommendation(cls, value: object) -> object:
        if value == 0:
            return None
        if isinstance(value, str):
            stripped = value.strip()
            if stripped in {"", "0"}:
                return None
            match = re.search(r"\d+", stripped)
            if match:
                parsed = int(match.group(0))
                return None if parsed == 0 else parsed
        return value

    @field_validator("chapters", "key_moments", mode="before")
    @classmethod
    def normalize_null_lists(cls, value: object) -> object:
        return _list_if_single_object(value)

    @field_validator("key_takeaways", "action_items", mode="before")
    @classmethod
    def normalize_string_lists(cls, value: object) -> object:
        return _string_list_if_scalar(value)

    @field_validator("markdown_body", mode="before")
    @classmethod
    def normalize_null_markdown_body(cls, value: object) -> object:
        return _empty_string_if_none(value)


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
    kind: Literal["audio", "subtitle", "markdown", "image", "json", "zip", "log"]
    asset_url: str


class FailureContext(BaseModel):
    ts: str | None = Field(default=None, exclude_if=lambda value: value is None)
    stage: str | None = Field(default=None, exclude_if=lambda value: value is None)
    message: str | None = Field(default=None, exclude_if=lambda value: value is None)
    context: str | None = Field(default=None, exclude_if=lambda value: value is None)
    attempt: int | float | None = Field(default=None, exclude_if=lambda value: value is None)
    note_base_url: str | None = Field(default=None, exclude_if=lambda value: value is None)
    note_model: str | None = Field(default=None, exclude_if=lambda value: value is None)
    response_file: str | None = Field(default=None, exclude_if=lambda value: value is None)
    finish_reason: str | None = Field(default=None, exclude_if=lambda value: value is None)
    message_chars: int | float | None = Field(default=None, exclude_if=lambda value: value is None)
    max_tokens: int | float | None = Field(default=None, exclude_if=lambda value: value is None)
    response_length: int | float | None = Field(default=None, exclude_if=lambda value: value is None)
    status_code: int | float | None = Field(default=None, exclude_if=lambda value: value is None)
    error_code: str | None = Field(default=None, exclude_if=lambda value: value is None)
    flagged_categories: list[str] = Field(default_factory=list, exclude_if=lambda value: not value)
    summary: str | None = Field(default=None, exclude_if=lambda value: value is None)


class JobPublicState(BaseModel):
    job_id: str
    status: JobStatus
    step: str
    progress: int
    error: str | None = None
    failure_context: FailureContext | None = Field(default=None, exclude_if=lambda value: value is None)
    artifacts: list[Artifact] = Field(default_factory=list)
    step_started_at: str | None = None
    updated_at: str | None = None
    stage_elapsed_seconds: float = 0
    download_filename: str | None = None


class JobSummary(BaseModel):
    job_id: str
    title: str
    original_filename: str
    created_at: str | None = None
    updated_at: str | None = None
    status: JobStatus
    error: str | None = Field(default=None, exclude_if=lambda value: value is None)
    failure_context: FailureContext | None = Field(default=None, exclude_if=lambda value: value is None)
    duration_seconds: float | None = None
    artifact_count: int = 0
    note_version_count: int = 0
    active_version_id: str | None = None


class JobHistory(BaseModel):
    jobs: list[JobSummary] = Field(default_factory=list)
