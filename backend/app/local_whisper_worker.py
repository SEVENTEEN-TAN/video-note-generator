from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REQUIRED_FASTER_WHISPER_FILES = ("config.json", "model.bin", "tokenizer.json", "vocabulary.txt")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Faster Whisper transcription from an external Python runtime.")
    parser.add_argument("--audio", default="")
    parser.add_argument("--download-only", action="store_true")
    parser.add_argument("--model", required=True)
    parser.add_argument("--model-root", required=True)
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--compute-type", default="int8")
    args = parser.parse_args()

    try:
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
        segments_raw, _info = model.transcribe(args.audio)
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
        print(str(exc), file=sys.stderr)
        return 1


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
    return model_dir.exists() and model_dir.is_dir() and all((model_dir / name).exists() for name in REQUIRED_FASTER_WHISPER_FILES)


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
