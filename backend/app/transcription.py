from __future__ import annotations

import base64
import importlib
import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from collections.abc import Callable

from openai import OpenAI

from .ffmpeg_tools import probe_duration, split_audio
from .models import JobConfig, TranscriptPayload, TranscriptSegment, TranscriptionMode
from .runtime_paths import get_bundle_root, get_model_root
from .time_utils import seconds_to_hhmmss

MAX_TRANSCRIPTION_FILE_BYTES = 24 * 1024 * 1024
STANDARD_TRANSCRIPTION_CHUNK_SECONDS = 600
CHAT_AUDIO_CHUNK_SECONDS = 120
FASTER_WHISPER_MODEL_ROOT = get_model_root()
REQUIRED_FASTER_WHISPER_FILES = ("config.json", "model.bin", "tokenizer.json")
FASTER_WHISPER_VOCABULARY_FILES = ("vocabulary.txt", "vocabulary.json")
ProgressCallback = Callable[[str, int], None]


def load_internal_whisper_model() -> tuple[object | None, str]:
    try:
        module = importlib.import_module("faster_whisper")
        return module.WhisperModel, ""
    except Exception as exc:
        return None, str(exc)


WhisperModel, FASTER_WHISPER_IMPORT_ERROR = load_internal_whisper_model()


class TranscriptionError(RuntimeError):
    pass


def make_client(api_key: str, base_url: str) -> OpenAI:
    base_url = base_url.strip()
    if base_url:
        return OpenAI(api_key=api_key, base_url=base_url, timeout=60.0, max_retries=0)
    return OpenAI(api_key=api_key, timeout=60.0, max_retries=0)


def dump_openai_model(value: object) -> dict:
    if hasattr(value, "model_dump"):
        return value.model_dump()
    if isinstance(value, dict):
        return value
    return json.loads(json.dumps(value, default=lambda item: getattr(item, "__dict__", str(item))))


def transcribe_audio(
    audio_path: Path,
    config: JobConfig,
    work_dir: Path,
    progress_callback: ProgressCallback | None = None,
) -> dict:
    if config.transcription_mode == TranscriptionMode.chat_audio:
        payload = transcribe_with_chat_audio(audio_path, config, work_dir, progress_callback=progress_callback)
    elif config.transcription_mode == TranscriptionMode.local_faster_whisper:
        payload = transcribe_with_faster_whisper(audio_path, config, progress_callback=progress_callback)
    else:
        payload = transcribe_with_audio_endpoint(audio_path, config, work_dir, progress_callback=progress_callback)
    return payload.model_dump()


def transcribe_with_faster_whisper(
    audio_path: Path,
    config: JobConfig,
    progress_callback: ProgressCallback | None = None,
) -> TranscriptPayload:
    model_name = config.transcription_model.strip() or "small"
    model_root = get_faster_whisper_model_root()
    model_root.mkdir(parents=True, exist_ok=True)
    model_identifier = resolve_local_faster_whisper_model(model_name, model_root)
    if progress_callback:
        progress_callback(f"字幕生成中：加载 Faster Whisper 模型 {model_name}", 36)
    if WhisperModel is None:
        try:
            return transcribe_with_external_faster_whisper(
                audio_path,
                config,
                model_root,
                progress_callback=progress_callback,
            )
        except Exception as exc:
            detail = f" Import error: {FASTER_WHISPER_IMPORT_ERROR}" if FASTER_WHISPER_IMPORT_ERROR else ""
            raise TranscriptionError(
                "Local Faster Whisper is not available inside the app, and the external Python worker failed. "
                "Install Python 3.10+ and run `python -m pip install -r backend/requirements.txt`, or use remote transcription."
                f"{detail} External worker error: {exc}"
            ) from exc

    device, compute_type = resolve_local_whisper_runtime(config)

    try:
        model = WhisperModel(
            model_identifier,
            device=device,
            compute_type=compute_type,
            download_root=str(model_root),
        )
        if progress_callback:
            progress_callback("字幕生成中：本地 Faster Whisper 转写中", 38)
        segments_raw, _info = model.transcribe(str(audio_path))
        return faster_whisper_segments_to_payload(segments_raw)
    except Exception as exc:
        raise TranscriptionError(f"Local Faster Whisper transcription failed: {exc}") from exc


def get_faster_whisper_model_root() -> Path:
    return Path(os.getenv("FASTER_WHISPER_MODEL_DIR", str(FASTER_WHISPER_MODEL_ROOT))).expanduser()


def transcribe_with_external_faster_whisper(
    audio_path: Path,
    config: JobConfig,
    model_root: Path,
    progress_callback: ProgressCallback | None = None,
) -> TranscriptPayload:
    python_path = find_external_python()
    if not python_path:
        raise TranscriptionError("External Python was not found on PATH. Install Python 3.10+ or set VIDEO_NOTE_PYTHON_PATH.")

    worker_path = get_local_whisper_worker_path()
    if not worker_path.exists():
        raise TranscriptionError(f"External Faster Whisper worker script was not found: {worker_path}")

    model_name = config.transcription_model.strip() or "small"
    device, compute_type = resolve_local_whisper_runtime(config)
    if progress_callback:
        progress_callback("字幕生成中：外部 Faster Whisper worker 转写中", 38)
    completed = subprocess.run(
        [
            python_path,
            str(worker_path),
            "--audio",
            str(audio_path),
            "--model",
            model_name,
            "--model-root",
            str(model_root),
            "--device",
            device,
            "--compute-type",
            compute_type,
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=external_worker_env(),
    )
    if completed.returncode != 0:
        message = completed.stderr.strip() or completed.stdout.strip() or "External Faster Whisper worker failed."
        raise TranscriptionError(message[-2000:])
    try:
        return TranscriptPayload.model_validate(json.loads(completed.stdout))
    except Exception as exc:
        raise TranscriptionError(f"External Faster Whisper worker returned invalid JSON: {exc}") from exc


def find_external_python() -> str | None:
    override = os.getenv("VIDEO_NOTE_PYTHON_PATH", "").strip()
    if override:
        return override
    for executable in ("python", "python3", "py"):
        path = shutil.which(executable)
        if path:
            return path
    return None


def external_worker_env() -> dict[str, str]:
    return {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}


def get_local_whisper_worker_path() -> Path:
    candidates = [
        get_bundle_root() / "backend" / "app" / "local_whisper_worker.py",
        Path(__file__).resolve().with_name("local_whisper_worker.py"),
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]


def resolve_local_whisper_runtime(config: JobConfig) -> tuple[str, str]:
    configured_device = str(config.local_whisper_device or "").strip()
    configured_compute_type = str(config.local_whisper_compute_type or "").strip()
    device = configured_device or os.getenv("FASTER_WHISPER_DEVICE", "cpu").strip() or "cpu"
    compute_type = configured_compute_type or os.getenv("FASTER_WHISPER_COMPUTE_TYPE", "int8").strip() or "int8"
    if compute_type == "default":
        compute_type = "int8"
    return device, compute_type


def resolve_local_faster_whisper_model(model_name: str, model_root: Path) -> str:
    model_name = model_name.strip() or "small"
    direct_path = Path(model_name).expanduser()
    if direct_path.is_absolute() and is_complete_faster_whisper_model_dir(direct_path):
        return str(direct_path)

    flat_model_dir = model_root / model_name
    if is_complete_faster_whisper_model_dir(flat_model_dir):
        return str(flat_model_dir)

    cached_snapshot_dir = resolve_huggingface_snapshot_dir(model_name, model_root)
    if cached_snapshot_dir:
        return str(cached_snapshot_dir)

    raise TranscriptionError(
        f"Local Faster Whisper model '{model_name}' is not available under {model_root}. "
        f"Put a complete model folder at {model_root / model_name}, copy a HuggingFace cache folder like "
        f"{model_root / huggingface_cache_repo_dir_name(model_name)}, or switch to remote transcription."
    )


def discover_local_faster_whisper_models(model_root: Path) -> list[str]:
    if not model_root.exists():
        return []
    models: set[str] = set()
    for item in model_root.iterdir():
        if not item.is_dir() or item.name.startswith("."):
            continue
        if is_complete_faster_whisper_model_dir(item):
            models.add(item.name)
            continue
        prefix = "models--Systran--faster-whisper-"
        if item.name.startswith(prefix) and resolve_huggingface_snapshot_dir(item.name.removeprefix(prefix), model_root):
            models.add(item.name.removeprefix(prefix))
    return sorted(models)


def resolve_huggingface_snapshot_dir(model_name: str, model_root: Path) -> Path | None:
    repo_dir = model_root / huggingface_cache_repo_dir_name(model_name)
    snapshots_dir = repo_dir / "snapshots"
    if not snapshots_dir.exists():
        return None

    ref_path = repo_dir / "refs" / "main"
    if ref_path.exists():
        snapshot_dir = snapshots_dir / ref_path.read_text(encoding="utf-8").strip()
        if is_complete_faster_whisper_model_dir(snapshot_dir):
            return snapshot_dir

    for snapshot_dir in sorted((item for item in snapshots_dir.iterdir() if item.is_dir()), key=lambda item: item.name):
        if is_complete_faster_whisper_model_dir(snapshot_dir):
            return snapshot_dir
    return None


def huggingface_cache_repo_dir_name(model_name: str) -> str:
    normalized = model_name.strip().replace("\\", "/").split("/")[-1]
    if not normalized:
        normalized = "small"
    if not normalized.startswith("faster-whisper-"):
        normalized = f"faster-whisper-{normalized}"
    return f"models--Systran--{normalized}"


def is_complete_faster_whisper_model_dir(model_dir: Path) -> bool:
    return (
        model_dir.exists()
        and model_dir.is_dir()
        and all((model_dir / name).exists() for name in REQUIRED_FASTER_WHISPER_FILES)
        and any((model_dir / name).exists() for name in FASTER_WHISPER_VOCABULARY_FILES)
    )


def faster_whisper_segments_to_payload(segments_raw: object) -> TranscriptPayload:
    segments: list[TranscriptSegment] = []
    full_text_parts: list[str] = []
    for item in segments_raw:
        text = str(getattr(item, "text", "")).strip()
        if not text:
            continue
        start = max(0.0, float(getattr(item, "start", 0) or 0))
        end = float(getattr(item, "end", start) or start)
        segments.append(TranscriptSegment(start=start, end=max(start, end), text=text))
        full_text_parts.append(text)
    return TranscriptPayload(text=" ".join(full_text_parts).strip(), segments=segments)


def transcribe_with_audio_endpoint(
    audio_path: Path,
    config: JobConfig,
    work_dir: Path,
    progress_callback: ProgressCallback | None = None,
) -> TranscriptPayload:
    if audio_path.stat().st_size <= MAX_TRANSCRIPTION_FILE_BYTES:
        return parse_transcription_payload(call_audio_endpoint(audio_path, config))

    chunks = split_audio(audio_path, work_dir / "transcription_chunks", STANDARD_TRANSCRIPTION_CHUNK_SECONDS)
    merged_segments: list[TranscriptSegment] = []
    offset = 0.0
    chunk_count = len(chunks)
    for index, chunk in enumerate(chunks, start=1):
        if progress_callback:
            progress = 35 + int((index - 1) / max(chunk_count, 1) * 25)
            progress_callback(f"字幕生成中：第 {index}/{chunk_count} 段转写中", progress)
        payload = parse_transcription_payload(call_audio_endpoint(chunk, config))
        for segment in payload.segments:
            merged_segments.append(
                TranscriptSegment(
                    start=segment.start + offset,
                    end=segment.end + offset,
                    text=segment.text,
                )
            )
        offset += probe_duration(chunk) or STANDARD_TRANSCRIPTION_CHUNK_SECONDS
    return TranscriptPayload(
        text=" ".join(segment.text for segment in merged_segments).strip(),
        segments=merged_segments,
    )


def call_audio_endpoint(audio_path: Path, config: JobConfig) -> dict:
    client = make_client(config.transcription_api_key, config.transcription_base_url)
    with audio_path.open("rb") as audio_file:
        response = client.audio.transcriptions.create(
            model=config.transcription_model,
            file=audio_file,
            response_format="verbose_json",
            timestamp_granularities=["segment"],
        )
    return dump_openai_model(response)


def transcribe_with_chat_audio(
    audio_path: Path,
    config: JobConfig,
    work_dir: Path,
    progress_callback: ProgressCallback | None = None,
) -> TranscriptPayload:
    chunks = split_audio(audio_path, work_dir / "chat_audio_chunks", CHAT_AUDIO_CHUNK_SECONDS)
    client = make_client(config.transcription_api_key, config.transcription_base_url)
    merged_segments: list[TranscriptSegment] = []
    offset = 0.0
    chunk_count = len(chunks)
    for index, chunk in enumerate(chunks, start=1):
        if progress_callback:
            progress = 35 + int((index - 1) / max(chunk_count, 1) * 25)
            progress_callback(f"字幕生成中：第 {index}/{chunk_count} 段音频理解中", progress)
        payload = call_chat_audio_transcription(client, chunk, config.transcription_model, offset)
        for segment in payload.segments:
            merged_segments.append(segment)
        offset += probe_duration(chunk) or CHAT_AUDIO_CHUNK_SECONDS
    return TranscriptPayload(
        text=" ".join(segment.text for segment in merged_segments).strip(),
        segments=merged_segments,
    )


def call_chat_audio_transcription(
    client: OpenAI,
    chunk_path: Path,
    model: str,
    offset_seconds: float,
) -> TranscriptPayload:
    audio_b64 = base64.b64encode(chunk_path.read_bytes()).decode("ascii")
    prompt = f"""
Transcribe this audio chunk. Return strict JSON only.
The audio chunk starts at absolute video time {offset_seconds:.3f} seconds ({seconds_to_hhmmss(offset_seconds)}).
Return this shape:
{{
  "segments": [
    {{"start": 0.0, "end": 2.5, "text": "spoken text"}}
  ]
}}
Rules:
- Use absolute timestamps in seconds, not timestamps relative to the chunk.
- If there is no speech, return one segment with start={offset_seconds:.3f}, end={offset_seconds:.3f}, text="No speech detected."
- Do not translate. Preserve spoken language.
""".strip()
    response = None
    last_error: Exception | None = None
    for audio_type in ("input_audio", "audio"):
        audio_part = {"type": audio_type, audio_type: {"data": audio_b64, "format": "mp3"}}
        try:
            response = client.chat.completions.create(
                model=model,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": prompt},
                            audio_part,
                        ],
                    }
                ],
                response_format={"type": "json_object"},
                temperature=0,
                max_tokens=1200,
            )
            break
        except Exception as exc:
            last_error = exc
    if response is None:
        raise TranscriptionError(f"Chat audio transcription failed: {last_error}") from last_error
    content = response.choices[0].message.content or "{}"
    return parse_chat_audio_payload(content, offset_seconds)


def parse_chat_audio_payload(content: str, offset_seconds: float) -> TranscriptPayload:
    try:
        data = extract_json(content)
    except Exception as exc:
        raise TranscriptionError(f"Chat audio transcription returned invalid JSON: {exc}") from exc
    raw_segments = data.get("segments") or []
    segments: list[TranscriptSegment] = []
    for item in raw_segments:
        text = str(item.get("text", "")).strip()
        if not text:
            continue
        start = float(item.get("start", offset_seconds))
        end = float(item.get("end", start))
        if start < offset_seconds - 1:
            start += offset_seconds
            end += offset_seconds
        segments.append(TranscriptSegment(start=max(0, start), end=max(start, end), text=text))
    if not segments:
        segments.append(TranscriptSegment(start=offset_seconds, end=offset_seconds, text="No speech detected."))
    return TranscriptPayload(text=" ".join(segment.text for segment in segments), segments=segments)


def parse_transcription_payload(payload: dict) -> TranscriptPayload:
    raw_segments = payload.get("segments") or []
    segments: list[TranscriptSegment] = []
    for item in raw_segments:
        text = str(item.get("text", "")).strip()
        if not text:
            continue
        segments.append(
            TranscriptSegment(
                start=float(item.get("start", 0)),
                end=float(item.get("end", item.get("start", 0))),
                text=text,
            )
        )
    if not segments and payload.get("text"):
        text = str(payload["text"]).strip()
        if text:
            segments.append(TranscriptSegment(start=0, end=0, text=text))
    return TranscriptPayload(text=str(payload.get("text", "")).strip(), segments=segments)


def extract_json(text: str) -> dict:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?", "", text, flags=re.IGNORECASE).strip()
        text = re.sub(r"```$", "", text).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, flags=re.DOTALL)
        if not match:
            raise
        return json.loads(match.group(0))
