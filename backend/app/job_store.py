from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock

from .filenames import normalize_uploaded_filename
from .models import Artifact, FailureContext, JobPublicState, JobStatus, JobSummary
from .note_versions import load_note_version_index, resolve_job_relative_path


TERMINAL_DEBUG_STAGES = {
    "process_transcription_job",
    "continue_job_to_notes",
    "regenerate_subtitles_job",
    "regenerate_note_job",
    "regenerate_note_chunk",
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class JobStore:
    def __init__(self, outputs_root: Path) -> None:
        self.outputs_root = outputs_root
        self._lock = Lock()
        self._jobs: dict[str, JobPublicState] = {}

    def create(self, job_id: str) -> JobPublicState:
        now = _now_iso()
        state = JobPublicState(
            job_id=job_id,
            status=JobStatus.pending,
            step="等待处理",
            progress=0,
            artifacts=[],
            step_started_at=now,
            updated_at=now,
            stage_elapsed_seconds=0,
        )
        with self._lock:
            self._jobs[job_id] = state
        return state

    def get(self, job_id: str) -> JobPublicState | None:
        with self._lock:
            return self._jobs.get(job_id)

    def update(
        self,
        job_id: str,
        *,
        status: JobStatus | None = None,
        step: str | None = None,
        progress: int | None = None,
        error: str | None = None,
    ) -> None:
        with self._lock:
            state = self._jobs[job_id]
            now = _now_iso()
            old_step = state.step
            new_step = step if step is not None else old_step
            if new_step != old_step:
                state.step_started_at = now
            state.updated_at = now
            if state.step_started_at:
                started = datetime.fromisoformat(state.step_started_at)
                current = datetime.fromisoformat(now)
                state.stage_elapsed_seconds = max(0, (current - started).total_seconds())
            if status is not None:
                state.status = status
                if status != JobStatus.failed:
                    state.failure_context = None
            if step is not None:
                state.step = step
            if progress is not None:
                state.progress = max(0, min(100, progress))
            if error is not None:
                state.error = error

    def refresh_artifacts(self, job_id: str) -> list[Artifact]:
        job_dir = self.outputs_root / job_id
        artifacts: list[Artifact] = []
        candidates = [
            ("audio.mp3", "原视频音频 MP3", "audio"),
            ("subtitles.srt", "字幕 SRT", "subtitle"),
            ("subtitles.vtt", "字幕 VTT", "subtitle"),
            ("subtitles.md", "字幕 Markdown", "markdown"),
            ("transcript.json", "转写 JSON", "json"),
            ("note.md", "视频笔记 Markdown", "markdown"),
            ("metadata.json", "任务元数据", "json"),
            ("debug.log", "调试日志", "log"),
            ("download.zip", "完整结果 ZIP", "zip"),
        ]
        for path, label, kind in candidates:
            if (job_dir / path).exists():
                artifacts.append(
                    Artifact(label=label, path=path, kind=kind, asset_url=f"/api/jobs/{job_id}/assets/{path}")
                )
        frames_dir = job_dir / "frames"
        if frames_dir.exists():
            for frame_path in sorted(frames_dir.glob("*.jpg")):
                rel = frame_path.relative_to(job_dir).as_posix()
                artifacts.append(
                    Artifact(label=frame_path.stem, path=rel, kind="image", asset_url=f"/api/jobs/{job_id}/assets/{rel}")
                )
        debug_dir = job_dir / "debug"
        if debug_dir.exists():
            for debug_path in sorted(path for path in debug_dir.rglob("*") if path.is_file()):
                rel = debug_path.relative_to(job_dir).as_posix()
                artifacts.append(
                    Artifact(label=debug_path.name, path=rel, kind="log", asset_url=f"/api/jobs/{job_id}/assets/{rel}")
                )
        review_dir = job_dir / "review"
        if review_dir.exists():
            review_candidates = [
                ("quality_report.json", "质量报告 JSON", "json"),
                ("quality_report.md", "质量报告 Markdown", "markdown"),
                ("frame_candidates.json", "配图候选 JSON", "json"),
            ]
            for filename, label, kind in review_candidates:
                review_path = review_dir / filename
                if review_path.exists():
                    rel = review_path.relative_to(job_dir).as_posix()
                    artifacts.append(
                        Artifact(label=label, path=rel, kind=kind, asset_url=f"/api/jobs/{job_id}/assets/{rel}")
                    )
        with self._lock:
            state = self._jobs.get(job_id)
            if state:
                state.artifacts = artifacts
                if state.status == JobStatus.failed and state.failure_context is None:
                    state.failure_context = _latest_disk_failure_context(job_dir)
        return artifacts

    def load_from_disk(self, job_id: str) -> JobPublicState | None:
        job_dir = self.outputs_root / job_id
        if not job_dir.exists() or not job_dir.is_dir():
            return None

        metadata = self._read_metadata(job_dir)
        artifacts = self.refresh_artifacts(job_id)
        version_index = load_note_version_index(job_dir)
        timestamp = str(_job_history_activity_timestamp(job_dir) or metadata.get("created_at") or _mtime_iso(job_dir))
        status = _infer_disk_job_status(job_dir, artifacts, version_index)
        interrupted_event = _latest_interrupted_processing_event(job_dir)
        failure_error = _latest_disk_failure_error(job_dir)
        failure_context = _latest_disk_failure_context(job_dir) if status == JobStatus.failed else None
        state = JobPublicState(
            job_id=job_id,
            status=status,
            step=(
                "已从历史记录载入"
                if status == JobStatus.succeeded
                else "等待确认字幕"
                if status == JobStatus.awaiting_subtitle_confirmation
                else "最近一次处理中断"
                if interrupted_event
                else "最近一次处理失败"
                if failure_error
                else "历史任务不完整"
            ),
            progress=100,
            error=(
                None
                if status in (
                    JobStatus.succeeded,
                    JobStatus.awaiting_subtitle_confirmation,
                    JobStatus.awaiting_note_review,
                )
                else failure_error
                or "历史任务缺少完整笔记输出，可能在上次生成中断。"
            ),
            failure_context=failure_context,
            artifacts=artifacts,
            step_started_at=timestamp,
            updated_at=timestamp,
            stage_elapsed_seconds=0,
        )
        if status == JobStatus.awaiting_note_review:
            state.step = "等待复核笔记"
            state.progress = 92
        with self._lock:
            self._jobs[job_id] = state
        return state

    def list_history(self) -> list[JobSummary]:
        if not self.outputs_root.exists():
            return []

        summaries = [
            (self._summarize_job_dir(path), _job_history_activity_timestamp(path))
            for path in self._iter_job_dirs()
        ]
        return [
            summary
            for summary, _activity_timestamp in sorted(
                summaries,
                key=lambda item: (item[1] or item[0].created_at or "", item[0].created_at or ""),
                reverse=True,
            )
        ]

    def remove(self, job_id: str) -> None:
        with self._lock:
            self._jobs.pop(job_id, None)

    def _iter_job_dirs(self) -> list[Path]:
        return [
            path
            for path in self.outputs_root.iterdir()
            if path.is_dir() and not path.name.startswith(".")
        ]

    def _summarize_job_dir(self, job_dir: Path) -> JobSummary:
        metadata = self._read_metadata(job_dir)
        version_index = load_note_version_index(job_dir)
        artifacts = self.refresh_artifacts(job_dir.name)
        with self._lock:
            memory_state = self._jobs.get(job_dir.name)
        created_at = str(metadata.get("created_at") or _mtime_iso(job_dir))
        updated_at = str(_job_history_activity_timestamp(job_dir) or created_at)
        original_filename = normalize_uploaded_filename(str(metadata.get("original_filename") or job_dir.name))
        title = normalize_uploaded_filename(str(metadata.get("title") or original_filename), fallback=original_filename)
        status = memory_state.status if memory_state else _infer_disk_job_status(job_dir, artifacts, version_index)
        error = None
        failure_context = None
        if status == JobStatus.failed:
            error = memory_state.error if memory_state and memory_state.error else _latest_disk_failure_error(job_dir)
            failure_context = (
                memory_state.failure_context
                if memory_state and memory_state.failure_context
                else _latest_disk_failure_context(job_dir)
            )
        return JobSummary(
            job_id=job_dir.name,
            title=title,
            original_filename=original_filename,
            created_at=created_at,
            updated_at=memory_state.updated_at if memory_state and memory_state.updated_at else updated_at,
            status=status,
            error=error,
            failure_context=failure_context,
            duration_seconds=metadata.get("duration_seconds"),
            artifact_count=len(artifacts),
            note_version_count=len(version_index.versions),
            active_version_id=version_index.active_version_id,
        )

    def _read_metadata(self, job_dir: Path) -> dict:
        metadata_path = job_dir / "metadata.json"
        if not metadata_path.exists():
            return {}
        try:
            return json.loads(metadata_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}


def _mtime_iso(path: Path) -> str:
    return datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat()


def _job_history_activity_timestamp(job_dir: Path) -> str | None:
    timestamps = [
        record.get("ts")
        for record in _debug_log_events(job_dir)
        if isinstance(record.get("ts"), str) and record.get("ts")
    ]
    if timestamps:
        return max(timestamps)
    debug_log = job_dir / "debug.log"
    if debug_log.exists():
        return _mtime_iso(debug_log)
    return None


def _infer_disk_job_status(job_dir: Path, artifacts: list[Artifact], version_index) -> JobStatus:
    if _latest_interrupted_processing_event(job_dir):
        return JobStatus.failed

    latest_terminal_event = _latest_terminal_debug_event(job_dir)
    if latest_terminal_event and latest_terminal_event.get("message") == "failed":
        return JobStatus.failed

    artifact_paths = {artifact.path for artifact in artifacts}
    if (job_dir / ".note-review.pending").exists():
        return JobStatus.awaiting_note_review
    if "note.md" in artifact_paths:
        return JobStatus.succeeded
    if "subtitles.md" in artifact_paths and (job_dir / "subtitles.pending").exists():
        return JobStatus.awaiting_subtitle_confirmation
    for version in version_index.versions:
        try:
            note_path = resolve_job_relative_path(job_dir, version.note_path)
        except ValueError:
            continue
        if note_path.exists():
            return JobStatus.succeeded
    return JobStatus.failed


def _latest_disk_failure_error(job_dir: Path) -> str | None:
    interrupted_event = _latest_interrupted_processing_event(job_dir)
    if interrupted_event:
        return _summarize_interrupted_processing_event(interrupted_event)

    latest_terminal_event = _latest_terminal_debug_event(job_dir)
    if not latest_terminal_event or latest_terminal_event.get("message") != "failed":
        return None

    details = latest_terminal_event.get("details")
    if not isinstance(details, dict):
        return "最近一次处理失败。"
    message = str(details.get("exception_message") or details.get("error") or "").strip()
    if _is_invalid_note_json_message(message):
        finish_reason_summary = _latest_note_response_finish_reason_summary(job_dir, "content_filter")
        if finish_reason_summary:
            return _append_failure_location(
                "笔记模型输出被内容过滤（finish_reason=content_filter），导致返回的 JSON 为空或不完整。可重试生成，或减少单次内容、调整补充要求、或更换模型。",
                finish_reason_summary,
            )
    if _is_invalid_note_json_message(message):
        finish_reason_summary = _latest_note_response_finish_reason_summary(job_dir, "length")
        if finish_reason_summary:
            return _append_failure_location(
                "笔记模型输出被截断（finish_reason=length），导致返回的 JSON 不完整。可重试生成，或减少单次内容长度、提高 max_tokens、或更换模型。",
                finish_reason_summary,
            )
    summary = _summarize_failure_message(details, message)
    request_context = _latest_note_api_error_request_context(job_dir)
    if request_context:
        return _append_failure_location(summary, request_context)
    return summary


def _latest_disk_failure_context(job_dir: Path) -> FailureContext | None:
    interrupted_event = _latest_interrupted_processing_event(job_dir)
    if interrupted_event:
        return _failure_context_from_event(interrupted_event)

    relevant_events = _latest_failed_run_events(job_dir)
    for event in reversed(relevant_events):
        if event.get("stage") != "note_model_call" or event.get("message") != "api_error":
            continue
        details = event.get("details")
        if not isinstance(details, dict):
            continue
        request_details = _matching_note_request_details(relevant_events, details) or details
        return _failure_context_from_event(event, request_details)

    for event in reversed(relevant_events):
        if event.get("stage") != "note_model_call" or event.get("message") not in {
            "failed",
            "invalid_json",
            "response_received",
        }:
            continue
        details = event.get("details")
        context_details = _matching_note_model_context_details(relevant_events, details) if isinstance(details, dict) else None
        return _failure_context_from_event(event, context_details)

    latest_terminal_event = _latest_terminal_debug_event(job_dir)
    if latest_terminal_event and latest_terminal_event.get("message") == "failed":
        return _failure_context_from_event(latest_terminal_event)
    return None


def _failure_context_from_event(event: dict, request_details: dict | None = None) -> FailureContext | None:
    details = event.get("details")
    merged_details: dict[str, object] = dict(details) if isinstance(details, dict) else {}
    if isinstance(request_details, dict):
        merged_details.update(request_details)

    payload: dict[str, object] = {}
    for field in ("ts", "stage", "message"):
        value = event.get(field)
        if isinstance(value, str) and value:
            payload[field] = value
    for field in ("context", "note_base_url", "note_model", "response_file", "finish_reason"):
        value = merged_details.get(field)
        if isinstance(value, str) and value:
            payload[field] = value
    for field in ("attempt", "message_chars", "max_tokens", "response_length", "status_code"):
        value = merged_details.get(field)
        if isinstance(value, int | float):
            payload[field] = value
    payload.update(_extract_provider_error_details(merged_details))

    summary = _summarize_failure_context_payload(payload)
    if summary:
        payload["summary"] = summary

    if not payload.get("stage") and not payload.get("message"):
        return None
    return FailureContext(**payload)


def _extract_provider_error_details(details: dict[str, object]) -> dict[str, object]:
    body = details.get("body")
    if not isinstance(body, dict):
        return {}

    error = body.get("error")
    source = error if isinstance(error, dict) else body
    extracted: dict[str, object] = {}
    code = source.get("code")
    if isinstance(code, str) and code:
        extracted["error_code"] = code
    categories = source.get("flagged_categories")
    if isinstance(categories, list):
        extracted["flagged_categories"] = [str(category) for category in categories if category]
    elif isinstance(categories, dict):
        extracted["flagged_categories"] = [str(category) for category, flagged in categories.items() if flagged]
    return extracted


def _summarize_failure_context_payload(payload: dict[str, object]) -> str:
    parts: list[str] = []
    if payload.get("context"):
        parts.append(str(payload["context"]))
    if payload.get("attempt") not in (None, ""):
        parts.append(f"第 {payload['attempt']} 次请求")
    if payload.get("note_model"):
        parts.append(f"模型 {payload['note_model']}")
    if payload.get("note_base_url"):
        parts.append(f"接口 {payload['note_base_url']}")
    if payload.get("message_chars") not in (None, ""):
        parts.append(f"{payload['message_chars']} 字符")
    if payload.get("max_tokens") not in (None, ""):
        parts.append(f"max_tokens={payload['max_tokens']}")
    if payload.get("response_length") not in (None, ""):
        parts.append(f"response_length={payload['response_length']}")
    if payload.get("finish_reason"):
        parts.append(f"finish_reason={payload['finish_reason']}")
    if payload.get("response_file"):
        parts.append(f"response_file={payload['response_file']}")
    if payload.get("status_code") not in (None, ""):
        parts.append(f"HTTP {payload['status_code']}")
    if payload.get("error_code"):
        parts.append(str(payload["error_code"]))
    flagged_categories = payload.get("flagged_categories")
    if isinstance(flagged_categories, list) and flagged_categories:
        parts.append(f"分类 {', '.join(str(category) for category in flagged_categories)}")
    if parts:
        return "，".join(parts)
    stage = payload.get("stage")
    message = payload.get("message")
    if stage and message:
        return f"{stage}/{message}"
    return ""


def _append_failure_location(summary: str, location: str) -> str:
    if not location:
        return summary
    return f"{summary} 失败位置：{location}。"


def _summarize_failure_message(details: dict, message: str) -> str:
    exception_type = str(details.get("exception_type") or "").strip()
    normalized = message.casefold()
    if "content_policy_violation" in normalized:
        return "笔记模型请求被内容安全策略拦截（content_policy_violation）。可尝试重新生成、减少单次内容或更换模型。"
    if "finish_reason=content_filter" in normalized or "content filter" in normalized:
        return "笔记模型输出被内容过滤（finish_reason=content_filter）。可重试生成，或减少单次内容、调整补充要求、或更换模型。"
    if exception_type == "AuthenticationError" or "invalid token" in normalized:
        return "API 认证失败（401 invalid token）。请检查 API Key 或接口地址。"
    if (
        exception_type == "NotFoundError"
        or "model not found" in normalized
        or ("not found" in normalized and " 404 " in f" {normalized} ")
    ):
        return "模型或接口地址不存在（404/model not found）。请检查模型名称、Base URL 和供应商接口路径。"
    if exception_type == "RateLimitError" or "rate limit" in normalized or "quota" in normalized or " 429 " in f" {normalized} ":
        return "API 请求被限流或额度不足（429/rate limit）。请稍后重试，或检查账号额度、模型并发限制。"
    if exception_type == "APIConnectionError" or "connection error" in normalized or "could not connect" in normalized:
        return "无法连接到模型接口。请检查网络、代理、防火墙或接口地址后重试。"
    if exception_type == "APITimeoutError" or "timed out" in normalized or "timeout" in normalized:
        return "笔记模型请求超时。可重试生成，或减少单次内容、更换模型/接口后再试。"
    if (
        exception_type == "InternalServerError"
        or re.search(r"\b5\d\d\b", normalized)
        or "server error" in normalized
        or "service unavailable" in normalized
        or "bad gateway" in normalized
        or "gateway timeout" in normalized
    ):
        return "模型服务暂时不可用（5xx/server error）。请稍后重试，或临时更换模型/接口。"
    if _is_invalid_note_json_message(message):
        return "笔记模型返回了空内容或非 JSON，无法解析为结构化笔记。可重试生成，或更换模型、减少单次内容长度。"
    return message or "最近一次处理失败。"


def _latest_note_api_error_request_context(job_dir: Path) -> str:
    events = _debug_log_events(job_dir)
    latest_failed_index: int | None = None
    for index, event in enumerate(events):
        if event.get("stage") in TERMINAL_DEBUG_STAGES and event.get("message") == "failed":
            latest_failed_index = index
    if latest_failed_index is None:
        return ""

    latest_started_index = 0
    for index in range(latest_failed_index, -1, -1):
        event = events[index]
        if event.get("stage") in TERMINAL_DEBUG_STAGES and event.get("message") in {"started", "starting"}:
            latest_started_index = index
            break

    relevant_events = events[latest_started_index : latest_failed_index + 1]
    for event in reversed(relevant_events):
        if event.get("stage") != "note_model_call" or event.get("message") != "api_error":
            continue
        details = event.get("details")
        if not isinstance(details, dict):
            continue
        failure_context = _failure_context_from_event(
            event,
            _matching_note_request_details(relevant_events, details),
        )
        if failure_context and failure_context.summary:
            return failure_context.summary
        return _summarize_note_request_details(details)
    return ""


def _matching_note_request_details(events: list[dict], api_error_details: dict) -> dict | None:
    context = api_error_details.get("context")
    attempt = api_error_details.get("attempt")
    for event in reversed(events):
        if event.get("stage") != "note_model_call" or event.get("message") != "requesting":
            continue
        details = event.get("details")
        if not isinstance(details, dict):
            continue
        if context not in (None, "") and details.get("context") != context:
            continue
        if attempt not in (None, "") and details.get("attempt") != attempt:
            continue
        return details
    return None


def _matching_note_model_context_details(events: list[dict], details: dict) -> dict:
    merged: dict = {}
    request_details = _matching_note_request_details(events, details)
    if request_details:
        merged.update(request_details)
    response_details = _matching_note_response_details(events, details)
    if response_details:
        merged.update(response_details)
    merged.update(details)
    return merged


def _matching_note_response_details(events: list[dict], details: dict) -> dict | None:
    context = details.get("context")
    attempt = details.get("attempt")
    for event in reversed(events):
        if event.get("stage") != "note_model_call" or event.get("message") != "response_received":
            continue
        response_details = event.get("details")
        if not isinstance(response_details, dict):
            continue
        if context not in (None, "") and response_details.get("context") != context:
            continue
        if attempt not in (None, "") and response_details.get("attempt") != attempt:
            continue
        return response_details
    return None


def _summarize_note_request_details(details: dict) -> str:
    parts: list[str] = []
    if details.get("context"):
        parts.append(str(details["context"]))
    if details.get("attempt") not in (None, ""):
        parts.append(f"第 {details['attempt']} 次请求")
    if details.get("note_model"):
        parts.append(f"模型 {details['note_model']}")
    if details.get("note_base_url"):
        parts.append(f"接口 {details['note_base_url']}")
    if details.get("response_length") not in (None, ""):
        parts.append(f"response_length={details['response_length']}")
    if details.get("finish_reason"):
        parts.append(f"finish_reason={details['finish_reason']}")
    if details.get("response_file"):
        parts.append(f"response_file={details['response_file']}")
    if not parts:
        return ""
    return "，".join(parts)


def _is_invalid_note_json_message(message: str) -> bool:
    normalized = message.casefold()
    return "invalid note json" in normalized or "expecting value: line 1 column 1" in normalized


def _latest_note_response_finish_reason_summary(job_dir: Path, finish_reason: str) -> str:
    event = _latest_note_response_finish_reason_event(job_dir, finish_reason)
    if not event:
        return ""
    details = event.get("details")
    if not isinstance(details, dict):
        return ""
    events = _latest_failed_run_events(job_dir)
    return _summarize_note_request_details(_matching_note_model_context_details(events, details))


def _latest_note_response_finish_reason_event(job_dir: Path, finish_reason: str) -> dict | None:
    relevant_events = _latest_failed_run_events(job_dir)
    if not relevant_events:
        return None
    invalid_context = _latest_note_model_error_context(relevant_events)
    for event in reversed(relevant_events):
        if event.get("stage") != "note_model_call" or event.get("message") != "response_received":
            continue
        details = event.get("details")
        if not isinstance(details, dict):
            continue
        if str(details.get("finish_reason") or "").casefold() != finish_reason.casefold():
            continue
        if invalid_context and details.get("context") != invalid_context:
            continue
        return event
    return None


def _latest_failed_run_events(job_dir: Path) -> list[dict]:
    events = _debug_log_events(job_dir)
    latest_failed_index: int | None = None
    for index, event in enumerate(events):
        if event.get("stage") in TERMINAL_DEBUG_STAGES and event.get("message") == "failed":
            latest_failed_index = index
    if latest_failed_index is None:
        return []

    latest_started_index = 0
    for index in range(latest_failed_index, -1, -1):
        event = events[index]
        if event.get("stage") in TERMINAL_DEBUG_STAGES and event.get("message") in {"started", "starting"}:
            latest_started_index = index
            break
    return events[latest_started_index : latest_failed_index + 1]


def _latest_note_model_error_context(events: list[dict]) -> str | None:
    for event in reversed(events):
        if event.get("stage") != "note_model_call" or event.get("message") not in {"invalid_json", "failed"}:
            continue
        details = event.get("details")
        if isinstance(details, dict) and details.get("context"):
            return str(details["context"])
    return None


def _summarize_interrupted_processing_event(event: dict) -> str:
    stage = str(event.get("stage") or "unknown")
    message = str(event.get("message") or "unknown")
    details = event.get("details")
    context = ""
    if isinstance(details, dict) and details.get("context"):
        context = f"（{details['context']}）"
    request_details = ""
    if stage == "note_model_call" and message == "requesting" and isinstance(details, dict):
        request_details = _summarize_interrupted_model_request_details(details)
    detail_sentence = f"；{request_details}" if request_details else ""
    return f"最近一次处理在 {stage}/{message}{context} 后中断{detail_sentence}，可能是应用关闭、进程退出或模型请求长时间无响应。请查看调试日志后重试。"


def _summarize_interrupted_model_request_details(details: dict) -> str:
    parts: list[str] = []
    if details.get("attempt") not in (None, ""):
        parts.append(f"第 {details['attempt']} 次请求")
    if details.get("note_model"):
        parts.append(f"模型 {details['note_model']}")
    if details.get("note_base_url"):
        parts.append(f"接口 {details['note_base_url']}")
    if details.get("message_chars") not in (None, ""):
        parts.append(f"{details['message_chars']} 字符")
    if details.get("max_tokens") not in (None, ""):
        parts.append(f"max_tokens={details['max_tokens']}")
    if not parts:
        return ""
    return f"请求详情：{'，'.join(parts)}"


def _latest_interrupted_processing_event(job_dir: Path) -> dict | None:
    events = _debug_log_events(job_dir)
    latest_started_index: int | None = None
    latest_terminal_index: int | None = None
    latest_event: dict | None = None

    for index, record in enumerate(events):
        latest_event = record
        if record.get("stage") not in TERMINAL_DEBUG_STAGES:
            continue
        message = record.get("message")
        if message in {"started", "starting"}:
            latest_started_index = index
        elif message in {"failed", "succeeded", "awaiting_confirmation"}:
            latest_terminal_index = index

    if latest_started_index is None:
        return None
    if latest_terminal_index is not None and latest_terminal_index > latest_started_index:
        return None
    return latest_event


def _latest_terminal_debug_event(job_dir: Path) -> dict | None:
    latest: dict | None = None
    for record in _debug_log_events(job_dir):
        if (
            isinstance(record, dict)
            and record.get("stage") in TERMINAL_DEBUG_STAGES
            and record.get("message") in {"failed", "succeeded", "awaiting_confirmation"}
        ):
            latest = record
    return latest


def _debug_log_events(job_dir: Path) -> list[dict]:
    debug_log = job_dir / "debug.log"
    if not debug_log.exists():
        return []

    try:
        lines = debug_log.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []

    events: list[dict] = []
    for line in lines:
        record = _parse_debug_log_record(line)
        if isinstance(record, dict):
            events.append(record)
    return events


def _parse_debug_log_record(line: str) -> dict | None:
    try:
        record = json.loads(line)
    except json.JSONDecodeError:
        return _parse_malformed_debug_log_record(line)
    return record if isinstance(record, dict) else None


def _parse_malformed_debug_log_record(line: str) -> dict | None:
    stage = _extract_json_string_field(line, "stage")
    message = _extract_json_string_field(line, "message")
    if not stage or not message:
        return None
    record = {"stage": stage, "message": message}
    ts = _extract_json_string_field(line, "ts")
    if ts:
        record["ts"] = ts
    level = _extract_json_string_field(line, "level")
    if level:
        record["level"] = level
    details: dict[str, object] = {}
    for field in (
        "context",
        "exception_type",
        "exception_message",
        "error",
        "note_base_url",
        "note_model",
        "response_file",
        "finish_reason",
    ):
        value = _extract_json_string_field(line, field)
        if value:
            details[field] = value
    for field in ("attempt", "message_count", "message_chars", "max_tokens", "response_length"):
        value = _extract_json_number_field(line, field)
        if value is not None:
            details[field] = value
    record["details"] = details
    return record


def _extract_json_string_field(line: str, field: str) -> str | None:
    match = re.search(rf'"{re.escape(field)}"\s*:\s*"((?:\\.|[^"\\])*)"', line)
    if not match:
        return None
    raw_value = match.group(1)
    try:
        return json.loads(f'"{raw_value}"')
    except json.JSONDecodeError:
        return raw_value


def _extract_json_number_field(line: str, field: str) -> int | float | None:
    match = re.search(rf'"{re.escape(field)}"\s*:\s*(-?\d+(?:\.\d+)?)', line)
    if not match:
        return None
    raw_value = match.group(1)
    if "." in raw_value:
        return float(raw_value)
    return int(raw_value)
