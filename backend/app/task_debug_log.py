from __future__ import annotations

import json
import re
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SENSITIVE_KEY_PARTS = ("api_key", "authorization", "password", "secret")
MAX_LOG_STRING_LENGTH = 1000
LOG_STRING_EDGE_LENGTH = 450
SENSITIVE_STRING_PATTERNS = (
    (re.compile(r"(?i)\b(Bearer)\s+([^\s;,\]}]+)"), r"\1 [REDACTED]"),
    (re.compile(r"(?i)\b(api[_-]?key)\s*=\s*([^\s;,\]}]+)"), r"\1=[REDACTED]"),
)


class TaskDebugLog:
    def __init__(self, job_dir: Path) -> None:
        self.job_dir = job_dir
        self.path = job_dir / "debug.log"
        self.debug_dir = job_dir / "debug"

    def event(self, stage: str, message: str, **details: Any) -> None:
        self._write("INFO", stage, message, details)

    def exception(self, stage: str, message: str, exc: BaseException, **details: Any) -> None:
        payload = {
            **details,
            "exception_type": type(exc).__name__,
            "exception_message": str(exc),
            "traceback": "".join(traceback.format_exception(type(exc), exc, exc.__traceback__)),
        }
        self._write("ERROR", stage, message, payload)

    def write_debug_text(self, filename: str, text: str) -> Path:
        safe_name = _safe_relative_filename(filename)
        path = self.debug_dir / safe_name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def _write(self, level: str, stage: str, message: str, details: dict[str, Any]) -> None:
        self.job_dir.mkdir(parents=True, exist_ok=True)
        record = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "level": level,
            "stage": stage,
            "message": message,
            "details": _redact(details),
        }
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False, default=str))
            handle.write("\n")


def _redact(value: Any, key: str = "") -> Any:
    if key and _is_sensitive_key(key):
        return "[REDACTED]"
    if isinstance(value, dict):
        return {str(item_key): _redact(item_value, str(item_key)) for item_key, item_value in value.items()}
    if isinstance(value, list):
        return [_redact(item) for item in value]
    if isinstance(value, tuple):
        return [_redact(item) for item in value]
    if isinstance(value, str):
        return _truncate_log_string(_redact_sensitive_string(value))
    return value


def _is_sensitive_key(key: str) -> bool:
    normalized = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", key).lower().replace("-", "_")
    if any(part in normalized for part in SENSITIVE_KEY_PARTS):
        return True
    return normalized == "token" or normalized.endswith("_token") or normalized.startswith("token_")


def _truncate_log_string(value: str) -> str:
    if len(value) <= MAX_LOG_STRING_LENGTH:
        return value
    omitted = len(value) - (LOG_STRING_EDGE_LENGTH * 2)
    return (
        f"{value[:LOG_STRING_EDGE_LENGTH]}"
        f"\n...[truncated {omitted} chars]...\n"
        f"{value[-LOG_STRING_EDGE_LENGTH:]}"
    )


def _redact_sensitive_string(value: str) -> str:
    redacted = value
    for pattern, replacement in SENSITIVE_STRING_PATTERNS:
        redacted = pattern.sub(replacement, redacted)
    return redacted


def _safe_relative_filename(filename: str) -> Path:
    normalized = filename.replace("\\", "/").strip("/")
    parts = [
        re.sub(r"[^A-Za-z0-9._-]", "_", part)
        for part in normalized.split("/")
        if part and part not in {".", ".."}
    ]
    if not parts:
        return Path("debug.txt")
    return Path(*parts)
