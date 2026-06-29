from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .llm import LLMError, call_json_model
from .models import JobConfig, TranscriptCorrectionPreview, TranscriptCorrectionSegment, TranscriptSegment
from .subtitles import transcript_segments_from_payload, write_subtitle_files
from .time_utils import seconds_to_hhmmss


TRANSCRIPT_ORIGINAL = "transcript.json"
TRANSCRIPT_CORRECTED_PENDING = "transcript.corrected.pending.json"
TRANSCRIPT_CORRECTED = "transcript.corrected.json"


class TranscriptCorrectionError(RuntimeError):
    pass


def load_original_segments(job_dir: Path) -> list[TranscriptSegment]:
    transcript_path = job_dir / TRANSCRIPT_ORIGINAL
    if not transcript_path.exists():
        raise FileNotFoundError("Transcript is not ready. Run the full job first.")
    try:
        payload = json.loads(transcript_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise TranscriptCorrectionError(f"Transcript cannot be read: {exc}") from exc
    segments = transcript_segments_from_payload(payload)
    if not segments:
        raise TranscriptCorrectionError("Transcript has no usable segments.")
    return segments


def load_preferred_transcript_payload(job_dir: Path) -> dict:
    corrected_path = job_dir / TRANSCRIPT_CORRECTED
    transcript_path = corrected_path if corrected_path.exists() else job_dir / TRANSCRIPT_ORIGINAL
    if not transcript_path.exists():
        raise FileNotFoundError("Cannot regenerate notes because transcript.json is missing.")
    try:
        return json.loads(transcript_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise TranscriptCorrectionError(f"Transcript cannot be read: {exc}") from exc


def correct_transcript_segments(
    config: JobConfig,
    segments: list[TranscriptSegment],
    instructions: str = "",
) -> list[dict]:
    transcript_lines = [
        f"{index}. [{seconds_to_hhmmss(segment.start)} - {seconds_to_hhmmss(segment.end)}] {segment.text}"
        for index, segment in enumerate(segments)
    ]
    extra = instructions.strip()
    user_prompt = f"""
You are correcting speech-to-text transcript terminology.

Rules:
- Return strict JSON only.
- Preserve the number of segments exactly.
- Preserve every index exactly.
- Do not change timestamps.
- Only correct segment text.
- Fix proper nouns, product names, English terms, acronyms, obvious homophones, and typos.
- Do not summarize, expand, or add facts.
- If unsure, keep the original text.

Additional user terminology guidance:
{extra or "None"}

Input segments:
{chr(10).join(transcript_lines)}

Return JSON in this shape:
{{
  "segments": [
    {{"index": 0, "text": "corrected text"}}
  ]
}}
""".strip()
    payload = call_json_model(
        config,
        [
            {
                "role": "system",
                "content": "You correct transcript text conservatively and return strict JSON.",
            },
            {"role": "user", "content": user_prompt},
        ],
        max_tokens=4000,
    )
    corrections = payload.get("segments")
    if not isinstance(corrections, list):
        raise TranscriptCorrectionError("Model correction response is missing segments.")
    return corrections


def build_correction_preview(
    original_segments: list[TranscriptSegment],
    corrected_segments: list[TranscriptSegment],
) -> TranscriptCorrectionPreview:
    if len(original_segments) != len(corrected_segments):
        raise TranscriptCorrectionError("Model correction segment count does not match the transcript.")
    preview_segments: list[TranscriptCorrectionSegment] = []
    for index, (original, corrected) in enumerate(zip(original_segments, corrected_segments)):
        corrected_text = corrected.text.strip() or original.text
        changed = original.text.strip() != corrected_text
        preview_segments.append(
            TranscriptCorrectionSegment(
                index=index,
                start=original.start,
                end=original.end,
                original_text=original.text,
                corrected_text=corrected_text,
                changed=changed,
            )
        )
    return TranscriptCorrectionPreview(
        changed_count=sum(1 for segment in preview_segments if segment.changed),
        segments=preview_segments,
    )


def create_transcript_correction(
    job_dir: Path,
    config: JobConfig,
    instructions: str = "",
) -> TranscriptCorrectionPreview:
    original_segments = load_original_segments(job_dir)
    corrections = correct_transcript_segments(config, original_segments, instructions)
    corrected_segments = normalize_corrections(original_segments, corrections)
    payload = transcript_payload_from_segments(corrected_segments)
    preview = build_correction_preview(original_segments, corrected_segments)
    write_json_atomic(job_dir / TRANSCRIPT_CORRECTED_PENDING, payload)
    return preview


def apply_pending_transcript_correction(job_dir: Path) -> TranscriptCorrectionPreview:
    pending_path = job_dir / TRANSCRIPT_CORRECTED_PENDING
    if not pending_path.exists():
        raise FileNotFoundError("No pending transcript correction is available.")
    try:
        pending_payload = json.loads(pending_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise TranscriptCorrectionError(f"Pending transcript correction cannot be read: {exc}") from exc
    original_segments = load_original_segments(job_dir)
    corrected_segments = transcript_segments_from_payload(pending_payload)
    preview = build_correction_preview(original_segments, corrected_segments)
    write_json_atomic(job_dir / TRANSCRIPT_CORRECTED, transcript_payload_from_segments(corrected_segments))
    write_subtitle_files(corrected_segments, job_dir)
    return preview


def normalize_corrections(
    original_segments: list[TranscriptSegment],
    corrections: list[dict],
) -> list[TranscriptSegment]:
    if len(corrections) != len(original_segments):
        raise TranscriptCorrectionError("Model correction segment count does not match the transcript.")
    by_index: dict[int, Any] = {}
    for item in corrections:
        if not isinstance(item, dict) or "index" not in item:
            raise TranscriptCorrectionError("Model correction response has an invalid segment.")
        try:
            index = int(item["index"])
        except (TypeError, ValueError) as exc:
            raise TranscriptCorrectionError("Model correction response has an invalid segment index.") from exc
        by_index[index] = item
    corrected: list[TranscriptSegment] = []
    for index, original in enumerate(original_segments):
        item = by_index.get(index)
        if item is None:
            raise TranscriptCorrectionError("Model correction response is missing a segment index.")
        corrected_text = str(item.get("text", "")).strip() or original.text
        corrected.append(TranscriptSegment(start=original.start, end=original.end, text=corrected_text))
    return corrected


def transcript_payload_from_segments(segments: list[TranscriptSegment]) -> dict:
    return {
        "text": " ".join(segment.text for segment in segments).strip(),
        "segments": [
            {
                "start": segment.start,
                "end": segment.end,
                "text": segment.text,
            }
            for segment in segments
        ],
    }


def write_json_atomic(path: Path, payload: dict) -> None:
    tmp_path = path.with_name(f"{path.name}.tmp")
    try:
        tmp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp_path.replace(path)
    finally:
        if tmp_path.exists():
            tmp_path.unlink()
