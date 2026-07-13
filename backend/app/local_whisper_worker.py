from __future__ import annotations

import argparse
import ctypes
import json
import math
import os
import site
import sys
import tempfile
from pathlib import Path

REQUIRED_FASTER_WHISPER_FILES = ("config.json", "model.bin", "tokenizer.json")
FASTER_WHISPER_VOCABULARY_FILES = ("vocabulary.txt", "vocabulary.json")
CUDA_RUNTIME_DLLS = ("cublas64_12.dll", "cudnn64_9.dll")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Faster Whisper transcription from an external Python runtime.")
    parser.add_argument("--audio", default="")
    parser.add_argument("--session-request", default="")
    parser.add_argument("--runtime-status", action="store_true")
    parser.add_argument("--download-only", action="store_true")
    parser.add_argument("--model", default="small")
    parser.add_argument("--model-root", default="")
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--compute-type", default="int8")
    parser.add_argument("--language", default="")
    args = parser.parse_args()

    try:
        configure_cuda_dll_paths()
        if args.runtime_status:
            print(json.dumps(get_runtime_status(), ensure_ascii=False))
            return 0
        if args.session_request:
            return run_session_request(Path(args.session_request).expanduser())
        if not args.model_root:
            raise RuntimeError("--model-root is required.")
        model_root = Path(args.model_root).expanduser()
        model_root.mkdir(parents=True, exist_ok=True)
        if args.download_only:
            download_faster_whisper_model(args.model, model_root)
            print(json.dumps({"ok": True, "model": args.model}, ensure_ascii=False))
            return 0
        if not args.audio:
            raise RuntimeError("--audio is required unless --download-only is set.")
        model_identifier = resolve_local_faster_whisper_model(args.model, model_root)

        from faster_whisper import WhisperModel

        model = WhisperModel(
            model_identifier,
            device=args.device,
            compute_type=args.compute_type,
            download_root=str(model_root),
        )
        language = (args.language or "").strip() or None
        segments_raw, _info = model.transcribe(
            args.audio,
            language=language,
            vad_filter=True,
            vad_parameters={"min_silence_duration_ms": 500, "threshold": 0.5},
            beam_size=5,
            best_of=3,
        )
        segments = []
        full_text_parts = []
        for item in segments_raw:
            text = str(getattr(item, "text", "")).strip()
            if not text:
                continue
            start = max(0.0, float(getattr(item, "start", 0) or 0))
            end = float(getattr(item, "end", start) or start)
            segments.append({"start": start, "end": max(start, end), "text": text})
            full_text_parts.append(text)
        print(json.dumps({"text": " ".join(full_text_parts).strip(), "segments": segments}, ensure_ascii=False))
        return 0
    except Exception as exc:
        if args.session_request:
            emit_event({"type": "error", "message": str(exc)})
        else:
            print(str(exc), file=sys.stderr)
        return 1


def run_session_request(request_path: Path) -> int:
    request = json.loads(request_path.read_text(encoding="utf-8"))
    if not isinstance(request, dict):
        raise RuntimeError("Session request must contain a JSON object.")

    model_name = require_session_text(request, "model")
    model_root = Path(require_session_text(request, "model_root")).expanduser()
    device = require_session_text(request, "device")
    compute_type = require_session_text(request, "compute_type")
    cpu_threads = require_session_int(request, "cpu_threads", minimum=1)
    num_workers = require_session_int(request, "num_workers", minimum=1)
    language_value = request.get("language")
    if not isinstance(language_value, str):
        raise RuntimeError("Session request field 'language' must be a string.")
    language = language_value.strip() or None
    beam_size = require_session_int(request, "beam_size", minimum=1)
    best_of = require_session_int(request, "best_of", minimum=1)
    vad_filter = request.get("vad_filter")
    if not isinstance(vad_filter, bool):
        raise RuntimeError("Session request field 'vad_filter' must be a boolean.")
    vad_min_silence_ms = require_session_int(request, "vad_min_silence_ms", minimum=0)
    vad_threshold = require_session_number(request, "vad_threshold")
    chunks = validate_session_chunks(request.get("chunks"))

    model_root.mkdir(parents=True, exist_ok=True)
    model_identifier = resolve_local_faster_whisper_model(model_name, model_root)

    from faster_whisper import WhisperModel

    model = WhisperModel(
        model_identifier,
        device=device,
        compute_type=compute_type,
        download_root=str(model_root),
        cpu_threads=cpu_threads,
        num_workers=num_workers,
    )
    emit_event({"type": "ready"})

    for chunk in chunks:
        chunk_index = chunk["index"]
        segments_raw, _info = model.transcribe(
            str(chunk["audio_path"]),
            language=language,
            vad_filter=vad_filter,
            vad_parameters={
                "min_silence_duration_ms": vad_min_silence_ms,
                "threshold": vad_threshold,
            },
            beam_size=beam_size,
            best_of=best_of,
        )
        segments = []
        full_text_parts = []
        for item in segments_raw:
            start = max(0.0, float(getattr(item, "start", 0) or 0))
            end = max(start, float(getattr(item, "end", start) or start))
            emit_event({"type": "progress", "chunk_index": chunk_index, "segment_end": end})
            text = str(getattr(item, "text", "")).strip()
            if not text:
                continue
            segments.append({"start": start, "end": end, "text": text})
            full_text_parts.append(text)

        payload = {"text": " ".join(full_text_parts).strip(), "segments": segments}
        write_transcript_payload_atomic(chunk["result_path"], payload)
        emit_event({"type": "chunk_complete", "chunk_index": chunk_index})

    emit_event({"type": "complete"})
    return 0


def require_session_text(request: dict, field_name: str) -> str:
    value = request.get(field_name)
    if not isinstance(value, str) or not value.strip():
        raise RuntimeError(f"Session request field '{field_name}' must be a non-empty string.")
    return value.strip()


def require_session_int(request: dict, field_name: str, *, minimum: int) -> int:
    value = request.get(field_name)
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise RuntimeError(f"Session request field '{field_name}' must be an integer >= {minimum}.")
    return value


def require_session_number(request: dict, field_name: str) -> float:
    value = request.get(field_name)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise RuntimeError(f"Session request field '{field_name}' must be numeric.")
    number = float(value)
    if not math.isfinite(number):
        raise RuntimeError(f"Session request field '{field_name}' must be finite.")
    return number


def validate_session_chunks(raw_chunks: object) -> list[dict]:
    if not isinstance(raw_chunks, list):
        raise RuntimeError("Session request field 'chunks' must be a list.")

    chunks = []
    seen_indexes: set[int | float] = set()
    for position, raw_chunk in enumerate(raw_chunks):
        if not isinstance(raw_chunk, dict):
            raise RuntimeError(f"Session chunk at position {position} must be an object.")
        index = raw_chunk.get("index")
        if isinstance(index, bool) or not isinstance(index, (int, float)):
            raise RuntimeError(f"Session chunk at position {position} has a non-numeric index.")
        if isinstance(index, float) and not math.isfinite(index):
            raise RuntimeError(f"Session chunk at position {position} must have a finite index.")
        if index in seen_indexes:
            raise RuntimeError(f"Session request contains duplicate chunk index {index}.")
        seen_indexes.add(index)

        audio_path = require_absolute_chunk_path(raw_chunk, "audio_path", index)
        result_path = require_absolute_chunk_path(raw_chunk, "result_path", index)
        chunks.append({"index": index, "audio_path": audio_path, "result_path": result_path})

    return sorted(chunks, key=lambda chunk: chunk["index"])


def require_absolute_chunk_path(chunk: dict, field_name: str, chunk_index: int | float) -> Path:
    value = chunk.get(field_name)
    if not isinstance(value, str) or not value.strip():
        raise RuntimeError(f"Session chunk {chunk_index} field '{field_name}' must be a non-empty string.")
    path = Path(value).expanduser()
    if not path.is_absolute():
        raise RuntimeError(f"Session chunk {chunk_index} field '{field_name}' must be an absolute path.")
    return path


def write_transcript_payload_atomic(result_path: Path, payload: dict) -> None:
    result_path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=result_path.parent,
        prefix=f".{result_path.name}.",
        suffix=".tmp",
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(payload, stream, ensure_ascii=False, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_path, result_path)
    except Exception:
        try:
            temporary_path.unlink()
        except FileNotFoundError:
            pass
        raise


def emit_event(event: dict) -> None:
    print(json.dumps(event, ensure_ascii=False, allow_nan=False), flush=True)
def get_runtime_status() -> dict:
    status = {
        "python_path": sys.executable,
        "faster_whisper_available": False,
        "faster_whisper_error": "",
        "ctranslate2_available": False,
        "ctranslate2_version": "",
        "cuda_device_count": None,
        "cuda_runtime_available": False,
        "cuda_error": "",
        "cuda_dll_dirs": [str(path) for path in discover_cuda_dll_dirs()],
    }

    try:
        import ctranslate2

        status["ctranslate2_available"] = True
        status["ctranslate2_version"] = str(getattr(ctranslate2, "__version__", ""))
        status["cuda_device_count"] = int(ctranslate2.get_cuda_device_count())
    except Exception as exc:
        status["cuda_error"] = str(exc)

    try:
        import faster_whisper  # noqa: F401

        status["faster_whisper_available"] = True
    except Exception as exc:
        status["faster_whisper_error"] = str(exc)

    if status["cuda_device_count"]:
        missing = find_missing_cuda_runtime_dlls()
        if missing:
            details = "; ".join(f"{name}: {error}" for name, error in missing.items())
            status["cuda_error"] = f"CUDA device is visible, but CUDA runtime DLLs are missing or cannot be loaded. {details}"
        else:
            status["cuda_runtime_available"] = True

    return status


def configure_cuda_dll_paths() -> None:
    dll_dirs = discover_cuda_dll_dirs()
    if not dll_dirs:
        return
    current_path = os.environ.get("PATH", "")
    prefix = os.pathsep.join(str(path) for path in dll_dirs)
    os.environ["PATH"] = f"{prefix}{os.pathsep}{current_path}" if current_path else prefix
    add_dll_directory = getattr(os, "add_dll_directory", None)
    if add_dll_directory is None:
        return
    for path in dll_dirs:
        try:
            add_dll_directory(str(path))
        except OSError:
            pass


def discover_cuda_dll_dirs() -> list[Path]:
    candidates: list[Path] = []
    cuda_path = os.environ.get("CUDA_PATH", "").strip()
    if cuda_path:
        candidates.append(Path(cuda_path) / "bin")

    site_roots: list[Path] = []
    for value in sys.path:
        if value:
            site_roots.append(Path(value))
    try:
        site_roots.extend(Path(value) for value in site.getsitepackages())
    except Exception:
        pass
    try:
        site_roots.append(Path(site.getusersitepackages()))
    except Exception:
        pass

    for root in site_roots:
        nvidia_root = root / "nvidia"
        if not nvidia_root.exists():
            continue
        for package_dir in nvidia_root.iterdir():
            bin_dir = package_dir / "bin"
            if bin_dir.exists():
                candidates.append(bin_dir)

    seen: set[str] = set()
    result: list[Path] = []
    for path in candidates:
        try:
            resolved = path.resolve()
        except OSError:
            continue
        key = str(resolved).lower()
        if key not in seen and resolved.exists():
            seen.add(key)
            result.append(resolved)
    return result


def find_missing_cuda_runtime_dlls() -> dict[str, str]:
    missing: dict[str, str] = {}
    for name in CUDA_RUNTIME_DLLS:
        try:
            ctypes.WinDLL(name)
        except Exception as exc:
            missing[name] = str(exc)
    return missing


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

    raise RuntimeError(
        f"Local Faster Whisper model '{model_name}' is not available under {model_root}. "
        f"Put a complete model folder at {model_root / model_name}, copy a HuggingFace cache folder like "
        f"{model_root / huggingface_cache_repo_dir_name(model_name)}, or switch to remote transcription."
    )


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


def download_faster_whisper_model(model_name: str, model_root: Path) -> None:
    from huggingface_hub import snapshot_download

    repo_id = f"Systran/{huggingface_model_repo_name(model_name)}"
    snapshot_download(
        repo_id=repo_id,
        local_dir=None,
        cache_dir=str(model_root),
        local_files_only=False,
    )
    resolved = resolve_local_faster_whisper_model(model_name, model_root)
    if not resolved:
        raise RuntimeError(f"Downloaded model '{model_name}' could not be resolved under {model_root}.")


def huggingface_model_repo_name(model_name: str) -> str:
    normalized = model_name.strip().replace("\\", "/").split("/")[-1]
    if not normalized:
        normalized = "small"
    if normalized.startswith("faster-whisper-"):
        return normalized
    return f"faster-whisper-{normalized}"


if __name__ == "__main__":
    raise SystemExit(main())
