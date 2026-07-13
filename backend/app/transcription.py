from __future__ import annotations

import base64
import importlib
import json
import os
import re
import subprocess
from pathlib import Path
from collections.abc import Callable

from openai import OpenAI

from . import local_whisper_worker
from .ffmpeg_tools import PreparedAudio, probe_duration, split_audio
from .models import JobConfig, TranscriptPayload, TranscriptSegment, TranscriptionMode
from .runtime_config import get_configured_external_python, get_configured_model_root
from .runtime_paths import get_bundle_root
from .time_utils import seconds_to_hhmmss
from .transcription_checkpoints import ChunkSpec, open_checkpoint_session
from .transcription_plans import HardwareProfile, TranscriptionExecutionPlan, resolve_execution_plan

MAX_TRANSCRIPTION_FILE_BYTES = 24 * 1024 * 1024
STANDARD_TRANSCRIPTION_CHUNK_SECONDS = 600
CHAT_AUDIO_CHUNK_SECONDS = 120
LOCAL_WHISPER_CHUNK_THRESHOLD_SECONDS = 1800  # chunk long audio above 30 minutes
REQUIRED_FASTER_WHISPER_FILES = ("config.json", "model.bin", "tokenizer.json")
FASTER_WHISPER_VOCABULARY_FILES = ("vocabulary.txt", "vocabulary.json")
TRANSCRIPTION_WRAPPER_KEYS = ("data", "result", "output", "transcript")
ProgressCallback = Callable[[str, int], None]
CancellationCallback = Callable[[], bool]


def load_internal_whisper_model() -> tuple[object | None, str]:
    try:
        module = importlib.import_module("faster_whisper")
        return module.WhisperModel, ""
    except Exception as exc:
        return None, str(exc)


WhisperModel, FASTER_WHISPER_IMPORT_ERROR = load_internal_whisper_model()


class TranscriptionError(RuntimeError):
    pass


class TranscriptionCancelled(TranscriptionError):
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
    *,
    prepared_audio: PreparedAudio | None = None,
    is_cancelled: CancellationCallback | None = None,
    hardware_profile: HardwareProfile | None = None,
) -> dict:
    if config.transcription_mode == TranscriptionMode.chat_audio:
        payload = transcribe_with_chat_audio(audio_path, config, work_dir, progress_callback=progress_callback)
    elif config.transcription_mode == TranscriptionMode.local_faster_whisper:
        payload = transcribe_with_faster_whisper(
            audio_path,
            config,
            work_dir,
            progress_callback=progress_callback,
            prepared_audio=prepared_audio,
            is_cancelled=is_cancelled,
            hardware_profile=hardware_profile,
        )
    else:
        payload = transcribe_with_audio_endpoint(audio_path, config, work_dir, progress_callback=progress_callback)
    return payload.model_dump()


def transcribe_with_faster_whisper(
    audio_path: Path,
    config: JobConfig,
    work_dir: Path,
    progress_callback: ProgressCallback | None = None,
    *,
    prepared_audio: PreparedAudio | None = None,
    is_cancelled: CancellationCallback | None = None,
    hardware_profile: HardwareProfile | None = None,
) -> TranscriptPayload:
    cancellation = is_cancelled or (lambda: False)
    _raise_if_transcription_cancelled(cancellation)
    model_name = config.transcription_model.strip() or "small"
    model_root = get_faster_whisper_model_root()
    model_root.mkdir(parents=True, exist_ok=True)
    model_identifier = resolve_local_faster_whisper_model(model_name, model_root)

    if WhisperModel is None:
        try:
            return transcribe_with_external_faster_whisper(
                audio_path,
                config,
                model_root,
                work_dir=work_dir,
                progress_callback=progress_callback,
            )
        except TranscriptionCancelled:
            raise
        except Exception as exc:
            detail = f" Import error: {FASTER_WHISPER_IMPORT_ERROR}" if FASTER_WHISPER_IMPORT_ERROR else ""
            raise TranscriptionError(
                "Local Faster Whisper is not available inside the app, and the external Python worker failed. "
                "Install Python 3.10+ and run `python -m pip install -r backend/requirements.txt`, or use remote transcription."
                f"{detail} External worker error: {exc}"
            ) from exc

    duration = float(prepared_audio.duration if prepared_audio else (probe_duration(audio_path) or 0.0))
    profile = hardware_profile or _default_hardware_profile(config)
    plan = resolve_execution_plan(config, duration, profile)
    chunks = _local_chunk_specs(
        audio_path,
        work_dir,
        plan,
        duration,
        prepared_audio=prepared_audio,
        progress_callback=progress_callback,
    )
    session = open_checkpoint_session(work_dir / "work" / "asr", audio_path, plan, chunks)
    completed = session.completed_indices()
    pending = [chunk for chunk in session.chunks if chunk.index not in completed]
    if not pending:
        return session.merge_results()

    _raise_if_transcription_cancelled(cancellation)
    if progress_callback:
        progress_callback(f"字幕生成中：加载 Faster Whisper 模型 {model_name}", 36)
    configure_internal_cuda_dll_paths(plan.device)
    try:
        model = WhisperModel(
            model_identifier,
            device=plan.device,
            compute_type=plan.compute_type,
            download_root=str(model_root),
            cpu_threads=plan.cpu_threads,
            num_workers=plan.num_workers,
        )
        if progress_callback:
            progress_callback("字幕生成中：本地 Faster Whisper 转写中", 38)
        for ordinal, chunk in enumerate(pending, start=1):
            _raise_if_transcription_cancelled(cancellation)
            if progress_callback and len(chunks) > 1:
                progress_callback(
                    f"字幕生成中：第 {ordinal}/{len(pending)} 个待处理块",
                    _transcription_percent(chunk.start, duration),
                )
            payload = _transcribe_chunk_with_model(
                model,
                chunk,
                plan,
                config,
                total_duration=duration,
                is_cancelled=cancellation,
                progress_callback=progress_callback,
            )
            _raise_if_transcription_cancelled(cancellation)
            session.write_result(chunk.index, payload)
        return session.merge_results()
    except TranscriptionCancelled:
        raise
    except Exception as exc:
        raise TranscriptionError(f"Local Faster Whisper transcription failed: {exc}") from exc


def _transcribe_chunk_with_model(
    model: object,
    chunk: ChunkSpec,
    plan: TranscriptionExecutionPlan,
    config: JobConfig,
    *,
    total_duration: float,
    is_cancelled: CancellationCallback,
    progress_callback: ProgressCallback | None,
) -> TranscriptPayload:
    language = resolve_transcription_language(config)
    segments_raw, _info = model.transcribe(
        str(chunk.path),
        language=language or None,
        vad_filter=plan.vad_filter,
        vad_parameters={
            "min_silence_duration_ms": plan.vad_min_silence_ms,
            "threshold": plan.vad_threshold,
        },
        beam_size=plan.beam_size,
        best_of=plan.best_of,
    )
    return faster_whisper_segments_to_payload(
        segments_raw,
        is_cancelled=is_cancelled,
        on_segment=(
            lambda end: progress_callback(
                f"字幕生成中：已处理 {seconds_to_hhmmss(min(total_duration, chunk.start + end))} / "
                f"{seconds_to_hhmmss(total_duration)}",
                _transcription_percent(chunk.start + end, total_duration),
            )
            if progress_callback and total_duration > 0
            else None
        ),
    )


def _local_chunk_specs(
    audio_path: Path,
    work_dir: Path,
    plan: TranscriptionExecutionPlan,
    duration: float,
    *,
    prepared_audio: PreparedAudio | None,
    progress_callback: ProgressCallback | None,
) -> list[ChunkSpec]:
    if prepared_audio is not None:
        return list(prepared_audio.chunks)
    if plan.chunk_seconds <= 0:
        return [ChunkSpec(index=0, start=0.0, end=max(0.0, duration), path=audio_path)]
    if progress_callback:
        progress_callback("字幕生成中：正在切分长音频…", 37)
    paths = split_audio(audio_path, work_dir / "whisper_chunks", plan.chunk_seconds)
    chunks: list[ChunkSpec] = []
    offset = 0.0
    for index, path in enumerate(paths):
        measured = float(probe_duration(path) or plan.chunk_seconds)
        chunks.append(ChunkSpec(index=index, start=offset, end=offset + measured, path=path))
        offset += measured
    return chunks


def _default_hardware_profile(config: JobConfig) -> HardwareProfile:
    configured = str(config.local_whisper_device or "").strip()
    cuda_available = configured == "cuda"
    if configured in {"", "auto"}:
        try:
            import ctranslate2

            cuda_available = int(ctranslate2.get_cuda_device_count()) > 0
        except Exception:
            cuda_available = False
    return HardwareProfile(
        cpu_count=max(1, os.cpu_count() or 1),
        memory_bytes=None,
        cuda_available=cuda_available,
        cuda_memory_bytes=None,
    )


def _raise_if_transcription_cancelled(is_cancelled: CancellationCallback) -> None:
    if is_cancelled():
        raise TranscriptionCancelled("Local transcription was cancelled.")


def _transcription_percent(completed_seconds: float, total_seconds: float) -> int:
    if total_seconds <= 0:
        return 38
    fraction = max(0.0, min(1.0, completed_seconds / total_seconds))
    return max(38, min(60, 35 + int(fraction * 25)))



def get_faster_whisper_model_root() -> Path:
    return get_configured_model_root().as_path()


def transcribe_with_external_faster_whisper(
    audio_path: Path,
    config: JobConfig,
    model_root: Path,
    *,
    work_dir: Path | None = None,
    progress_callback: ProgressCallback | None = None,
) -> TranscriptPayload:
    duration = probe_duration(audio_path) or 0.0
    if duration > LOCAL_WHISPER_CHUNK_THRESHOLD_SECONDS and work_dir is not None:
        if progress_callback:
            progress_callback("字幕生成中：正在切分长音频…", 37)
        chunks = split_audio(audio_path, work_dir / "whisper_chunks", STANDARD_TRANSCRIPTION_CHUNK_SECONDS)
        if progress_callback:
            progress_callback(f"字幕生成中：已切分为 {len(chunks)} 块，开始逐块转写", 38)
        merged_segments: list[TranscriptSegment] = []
        offset = 0.0
        chunk_count = len(chunks)
        for index, chunk in enumerate(chunks, start=1):
            if progress_callback:
                progress = 35 + int((index - 1) / max(chunk_count, 1) * 25)
                progress_callback(f"字幕生成中：第 {index}/{chunk_count} 块转写中", progress)
            chunk_payload = _transcribe_single_external_chunk(chunk, config, model_root, python_path=None)
            for segment in chunk_payload.segments:
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

    return _transcribe_single_external_chunk(audio_path, config, model_root, python_path=None, progress_callback=progress_callback)


def _transcribe_single_external_chunk(
    chunk_path: Path,
    config: JobConfig,
    model_root: Path,
    *,
    python_path: str | None = None,
    progress_callback: ProgressCallback | None = None,
) -> TranscriptPayload:
    resolved_python = python_path or find_external_python()
    if not resolved_python:
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
            resolved_python,
            str(worker_path),
            "--audio",
            str(chunk_path),
            "--model",
            model_name,
            "--model-root",
            str(model_root),
            "--device",
            device,
            "--compute-type",
            compute_type,
            "--language",
            resolve_transcription_language(config),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=external_worker_env(model_root=model_root),
    )
    if completed.returncode != 0:
        message = completed.stderr.strip() or completed.stdout.strip() or "External Faster Whisper worker failed."
        raise TranscriptionError(message[-2000:])
    try:
        return TranscriptPayload.model_validate(json.loads(completed.stdout))
    except Exception as exc:
        raise TranscriptionError(f"External Faster Whisper worker returned invalid JSON: {exc}") from exc


def find_external_python() -> str | None:
    configured = get_configured_external_python()
    if configured.error:
        return None
    return configured.value or None


def external_worker_env(model_root: Path | None = None) -> dict[str, str]:
    env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}
    if model_root is not None:
        model_root_str = str(model_root)
        env.setdefault("FASTER_WHISPER_MODEL_DIR", model_root_str)
        env.setdefault("HUGGINGFACE_HUB_CACHE", model_root_str)
    return env


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


def configure_internal_cuda_dll_paths(device: str) -> None:
    if device.lower() in {"auto", "cuda"}:
        local_whisper_worker.configure_cuda_dll_paths()


def resolve_transcription_language(config: JobConfig) -> str:
    value = str(config.transcription_language or "").strip()
    return "" if value in {"", "auto"} else value


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


def faster_whisper_segments_to_payload(
    segments_raw: object,
    *,
    is_cancelled: CancellationCallback | None = None,
    on_segment: Callable[[float], None] | None = None,
) -> TranscriptPayload:
    segments: list[TranscriptSegment] = []
    full_text_parts: list[str] = []
    for item in segments_raw:
        if is_cancelled is not None:
            _raise_if_transcription_cancelled(is_cancelled)
        start = max(0.0, float(getattr(item, "start", 0) or 0))
        end = max(start, float(getattr(item, "end", start) or start))
        if on_segment is not None:
            on_segment(end)
        text = str(getattr(item, "text", "")).strip()
        if not text:
            continue
        segments.append(TranscriptSegment(start=start, end=end, text=text))
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
        language = resolve_transcription_language(config)
        kwargs: dict[str, object] = {
            "model": config.transcription_model,
            "file": audio_file,
            "response_format": "verbose_json",
            "timestamp_granularities": ["segment"],
        }
        if language:
            kwargs["language"] = language
        response = client.audio.transcriptions.create(**kwargs)
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
        payload = call_chat_audio_transcription(client, chunk, config.transcription_model, offset, config)
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
    config: JobConfig,
) -> TranscriptPayload:
    audio_b64 = base64.b64encode(chunk_path.read_bytes()).decode("ascii")
    transcription_language = resolve_transcription_language(config)
    language_hint = f" — the spoken language is {transcription_language}" if transcription_language else ""

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
- Do not translate. Preserve the spoken language{language_hint}.
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
    if not segments and data.get("text"):
        text = str(data["text"]).strip()
        if text:
            segments.append(TranscriptSegment(start=offset_seconds, end=offset_seconds, text=text))
    if not segments:
        segments.append(TranscriptSegment(start=offset_seconds, end=offset_seconds, text="No speech detected."))
    return TranscriptPayload(text=" ".join(segment.text for segment in segments), segments=segments)


def parse_transcription_payload(payload: dict) -> TranscriptPayload:
    payload = _find_transcript_json(payload) or payload
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
        value = json.loads(text)
        if isinstance(value, dict):
            return _find_transcript_json(value) or value
        return value
    except json.JSONDecodeError as original_error:
        candidates: list[dict] = []
        decoder = json.JSONDecoder()
        for match in re.finditer(r"\{", text):
            try:
                value, _end = decoder.raw_decode(text[match.start() :])
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict):
                candidates.append(value)
        if not candidates:
            raise original_error
        for candidate in candidates:
            transcript_payload = _find_transcript_json(candidate)
            if transcript_payload is not None:
                return transcript_payload
        return candidates[0]


def _find_transcript_json(payload: dict) -> dict | None:
    candidates = [payload]
    for candidate in candidates:
        if "segments" in candidate or "text" in candidate:
            return candidate
        for key in TRANSCRIPTION_WRAPPER_KEYS:
            nested = candidate.get(key)
            if isinstance(nested, dict):
                candidates.append(nested)
            elif isinstance(nested, str):
                nested_payload = _parse_json_object(nested)
                if nested_payload is not None:
                    candidates.append(nested_payload)
    return None


def _parse_json_object(text: str) -> dict | None:
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None
