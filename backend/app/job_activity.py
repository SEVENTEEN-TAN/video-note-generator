from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .models import JobActivityEvent, JobActivitySnapshot


def load_job_activity(job_dir: Path, *, limit: int = 8) -> JobActivitySnapshot:
    records = _read_records(job_dir / "debug.log")
    current_context = ""
    request_count = 0
    response_count = 0
    format_failure_count = 0
    truncation_retry_count = 0
    binary_split_count = 0
    events: list[JobActivityEvent] = []

    for record in records:
        stage = str(record.get("stage") or "")
        message = str(record.get("message") or "")
        details = record.get("details") if isinstance(record.get("details"), dict) else {}
        context = str(details.get("context") or "")
        if context:
            current_context = context
        if stage == "note_model_call" and message == "requesting":
            request_count += 1
        elif stage == "note_model_call" and message == "response_received":
            response_count += 1
        elif stage == "note_model_call" and message == "invalid_json":
            format_failure_count += 1
        elif stage == "note_model_call" and message == "truncation_retry":
            truncation_retry_count += 1
        elif stage == "generate_chunked_note_draft" and message == "binary_split_retry":
            binary_split_count += 1

        summary = _event_summary(stage, message, details)
        if summary:
            events.append(
                JobActivityEvent(
                    timestamp=str(record.get("ts") or ""),
                    level=str(record.get("level") or "INFO"),
                    stage=stage,
                    message=message,
                    summary=summary,
                    context=context,
                )
            )

    return JobActivitySnapshot(
        job_id=job_dir.name,
        current_context=current_context,
        request_count=request_count,
        response_count=response_count,
        format_failure_count=format_failure_count,
        truncation_retry_count=truncation_retry_count,
        binary_split_count=binary_split_count,
        events=events[-max(1, limit) :],
    )


def _read_records(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    records: list[dict[str, Any]] = []
    try:
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                try:
                    record = json.loads(line)
                except (TypeError, ValueError):
                    continue
                if isinstance(record, dict):
                    records.append(record)
    except OSError:
        return []
    return records


def _event_summary(stage: str, message: str, details: dict[str, Any]) -> str:
    context = str(details.get("context") or "")
    context_label = _context_label(context)
    if stage == "note_model_call":
        if message == "requesting":
            attempt = _positive_int(details.get("attempt"))
            max_tokens = _positive_int(details.get("max_tokens"))
            suffixes = [f"第 {attempt} 次" if attempt else "", f"上限 {max_tokens} tokens" if max_tokens else ""]
            suffix = " · ".join(item for item in suffixes if item)
            return f"正在请求 AI · {context_label}{f' · {suffix}' if suffix else ''}"
        if message == "response_received":
            length = _non_negative_int(details.get("response_length"))
            finish_reason = str(details.get("finish_reason") or "")
            result = "AI 已返回，但正文为空" if length == 0 else f"AI 已返回 {length} 字符"
            return f"{result} · {context_label}{f' · {finish_reason}' if finish_reason else ''}"
        if message == "invalid_json":
            return f"返回格式校验失败，准备重试 · {context_label}"
        if message == "truncation_retry":
            previous = _positive_int(details.get("previous_max_tokens"))
            next_value = _positive_int(details.get("next_max_tokens"))
            if previous and next_value:
                return f"输出达到长度上限，额度 {previous} → {next_value} · {context_label}"
            return f"输出达到长度上限，正在扩大额度重试 · {context_label}"
        if message == "failed":
            return f"本轮 AI 生成失败 · {context_label}"
        if message == "api_error":
            return f"AI 服务请求异常 · {context_label}"
    if stage == "generate_chunked_note_draft":
        if message == "binary_split_retry":
            segments = _positive_int(details.get("segment_count"))
            suffix = f"（{segments} 段字幕）" if segments else ""
            return f"当前笔记块已拆分为更小块重试{suffix} · {context_label}"
        if message == "fallback_to_skipped_chunk":
            return f"当前块改用保底笔记 · {context_label}"
    if stage == "reduce_note_drafts":
        if message == "fallback_to_deterministic_merge":
            return "AI 汇总失败，已改用本地合并"
    return ""


def _context_label(context: str) -> str:
    if not context:
        return "笔记生成"
    if context == "note-reduce":
        return "整合最终笔记"
    if context.startswith("note-chunk-"):
        return context.replace("note-chunk-", "笔记块 ", 1).replace("-of-", "/").replace("-left", " · 左半").replace(
            "-right", " · 右半"
        )
    return context


def _positive_int(value: Any) -> int | None:
    parsed = _non_negative_int(value)
    return parsed if parsed and parsed > 0 else None


def _non_negative_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed >= 0 else None
