from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from backend.app import local_whisper_worker
from backend.app.models import TranscriptPayload


def _write_session_request(path: Path, *, model_root: Path, chunks: list[dict]) -> None:
    path.write_text(
        json.dumps(
            {
                "model": "small",
                "model_root": str(model_root),
                "device": "cuda",
                "compute_type": "float16",
                "cpu_threads": 6,
                "num_workers": 1,
                "language": "zh",
                "beam_size": 7,
                "best_of": 4,
                "vad_filter": False,
                "vad_min_silence_ms": 321,
                "vad_threshold": 0.7,
                "chunks": chunks,
            }
        ),
        encoding="utf-8",
    )


def _run_main(monkeypatch, *args: str) -> int:
    monkeypatch.setattr(local_whisper_worker, "configure_cuda_dll_paths", lambda: None)
    monkeypatch.setattr(sys, "argv", ["local_whisper_worker.py", *args])
    return local_whisper_worker.main()


def _stdout_events(capsys) -> list[dict]:
    return [json.loads(line) for line in capsys.readouterr().out.splitlines() if line.strip()]


def test_session_loads_model_once_writes_results_in_numeric_order_and_emits_events(
    tmp_path, monkeypatch, capsys
) -> None:
    model_root = tmp_path / "models"
    first_audio = (tmp_path / "chunk-1.mp3").resolve()
    second_audio = (tmp_path / "chunk-2.mp3").resolve()
    first_result = (tmp_path / "results" / "chunk-1.json").resolve()
    second_result = (tmp_path / "results" / "chunk-2.json").resolve()
    first_audio.write_bytes(b"first")
    second_audio.write_bytes(b"second")
    request_path = tmp_path / "session.json"
    _write_session_request(
        request_path,
        model_root=model_root,
        chunks=[
            {"index": 2, "audio_path": str(second_audio), "result_path": str(second_result)},
            {"index": 1, "audio_path": str(first_audio), "result_path": str(first_result)},
        ],
    )

    model_initializations: list[tuple[tuple, dict]] = []
    transcribe_calls: list[tuple[str, dict]] = []

    class FakeWhisperModel:
        def __init__(self, *args, **kwargs) -> None:
            model_initializations.append((args, kwargs))

        def transcribe(self, audio_path: str, **kwargs):
            transcribe_calls.append((audio_path, kwargs))
            if audio_path == str(first_audio):
                return iter([SimpleNamespace(start=0.0, end=1.5, text="first text")]), object()
            return iter([SimpleNamespace(start=2.0, end=3.25, text="second text")]), object()

    monkeypatch.setitem(sys.modules, "faster_whisper", SimpleNamespace(WhisperModel=FakeWhisperModel))
    monkeypatch.setattr(
        local_whisper_worker,
        "resolve_local_faster_whisper_model",
        lambda model, root: f"resolved:{model}:{root}",
    )

    exit_code = _run_main(monkeypatch, "--session-request", str(request_path))

    assert exit_code == 0
    assert len(model_initializations) == 1
    assert model_initializations[0] == (
        (f"resolved:small:{model_root}",),
        {
            "device": "cuda",
            "compute_type": "float16",
            "download_root": str(model_root),
            "cpu_threads": 6,
            "num_workers": 1,
        },
    )
    assert [call[0] for call in transcribe_calls] == [str(first_audio), str(second_audio)]
    assert all(
        kwargs
        == {
            "language": "zh",
            "vad_filter": False,
            "vad_parameters": {"min_silence_duration_ms": 321, "threshold": 0.7},
            "beam_size": 7,
            "best_of": 4,
        }
        for _, kwargs in transcribe_calls
    )

    first_payload = TranscriptPayload.model_validate_json(first_result.read_text(encoding="utf-8"))
    second_payload = TranscriptPayload.model_validate_json(second_result.read_text(encoding="utf-8"))
    assert first_payload.text == "first text"
    assert first_payload.segments[0].end == 1.5
    assert second_payload.text == "second text"
    assert second_payload.segments[0].start == 2.0
    assert not first_result.with_name(f"{first_result.name}.tmp").exists()
    assert not second_result.with_name(f"{second_result.name}.tmp").exists()

    events = _stdout_events(capsys)
    assert [event["type"] for event in events] == [
        "ready",
        "progress",
        "chunk_complete",
        "progress",
        "chunk_complete",
        "complete",
    ]
    assert [(event.get("chunk_index"), event.get("segment_end")) for event in events if event["type"] == "progress"] == [
        (1, 1.5),
        (2, 3.25),
    ]
    assert [event["chunk_index"] for event in events if event["type"] == "chunk_complete"] == [1, 2]


def test_session_keeps_completed_result_when_later_chunk_fails(tmp_path, monkeypatch, capsys) -> None:
    model_root = tmp_path / "models"
    first_audio = (tmp_path / "chunk-0.mp3").resolve()
    second_audio = (tmp_path / "chunk-1.mp3").resolve()
    first_result = (tmp_path / "chunk-0.json").resolve()
    second_result = (tmp_path / "chunk-1.json").resolve()
    first_audio.write_bytes(b"first")
    second_audio.write_bytes(b"second")
    request_path = tmp_path / "session.json"
    _write_session_request(
        request_path,
        model_root=model_root,
        chunks=[
            {"index": 0, "audio_path": str(first_audio), "result_path": str(first_result)},
            {"index": 1, "audio_path": str(second_audio), "result_path": str(second_result)},
        ],
    )

    model_loads = 0

    class FailingSegments:
        def __iter__(self):
            raise RuntimeError("second chunk exploded")

    class FakeWhisperModel:
        def __init__(self, *args, **kwargs) -> None:
            nonlocal model_loads
            model_loads += 1

        def transcribe(self, audio_path: str, **kwargs):
            if audio_path == str(first_audio):
                return iter([SimpleNamespace(start=0, end=1, text="saved first")]), object()
            return FailingSegments(), object()

    monkeypatch.setitem(sys.modules, "faster_whisper", SimpleNamespace(WhisperModel=FakeWhisperModel))
    monkeypatch.setattr(local_whisper_worker, "resolve_local_faster_whisper_model", lambda *_args: "resolved")

    exit_code = _run_main(monkeypatch, "--session-request", str(request_path))

    assert exit_code != 0
    assert model_loads == 1
    assert TranscriptPayload.model_validate_json(first_result.read_text(encoding="utf-8")).text == "saved first"
    assert not second_result.exists()
    assert not second_result.with_name(f"{second_result.name}.tmp").exists()
    events = _stdout_events(capsys)
    assert [event["type"] for event in events] == ["ready", "progress", "chunk_complete", "error"]
    assert events[-1]["message"] == "second chunk exploded"


def test_session_temp_file_cannot_destroy_an_earlier_completed_result(tmp_path, monkeypatch, capsys) -> None:
    model_root = tmp_path / "models"
    first_audio = (tmp_path / "chunk-0.mp3").resolve()
    second_audio = (tmp_path / "chunk-1.mp3").resolve()
    second_result = (tmp_path / "chunk-1.json").resolve()
    first_result = second_result.with_name(f"{second_result.name}.tmp")
    first_audio.write_bytes(b"first")
    second_audio.write_bytes(b"second")
    request_path = tmp_path / "session.json"
    _write_session_request(
        request_path,
        model_root=model_root,
        chunks=[
            {"index": 0, "audio_path": str(first_audio), "result_path": str(first_result)},
            {"index": 1, "audio_path": str(second_audio), "result_path": str(second_result)},
        ],
    )

    class FakeWhisperModel:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def transcribe(self, audio_path: str, **kwargs):
            text = "saved first" if audio_path == str(first_audio) else "later"
            return iter([SimpleNamespace(start=0, end=1, text=text)]), object()

    real_replace = local_whisper_worker.os.replace

    def fail_second_replace(source, destination) -> None:
        if Path(destination) == second_result:
            raise OSError("second result publish failed")
        real_replace(source, destination)

    monkeypatch.setitem(sys.modules, "faster_whisper", SimpleNamespace(WhisperModel=FakeWhisperModel))
    monkeypatch.setattr(local_whisper_worker, "resolve_local_faster_whisper_model", lambda *_args: "resolved")
    monkeypatch.setattr(local_whisper_worker.os, "replace", fail_second_replace)

    exit_code = _run_main(monkeypatch, "--session-request", str(request_path))

    assert exit_code != 0
    assert TranscriptPayload.model_validate_json(first_result.read_text(encoding="utf-8")).text == "saved first"
    assert not second_result.exists()
    events = _stdout_events(capsys)
    assert events[-1] == {"type": "error", "message": "second result publish failed"}


@pytest.mark.parametrize("invalid_index", [float("nan"), float("inf"), float("-inf")])
def test_session_rejects_non_finite_chunk_indexes_before_model_loading(
    tmp_path, monkeypatch, capsys, invalid_index
) -> None:
    audio_path = (tmp_path / "chunk.mp3").resolve()
    result_path = (tmp_path / "chunk.json").resolve()
    audio_path.write_bytes(b"audio")
    request_path = tmp_path / "session.json"
    _write_session_request(
        request_path,
        model_root=tmp_path / "models",
        chunks=[{"index": invalid_index, "audio_path": str(audio_path), "result_path": str(result_path)}],
    )

    class MustNotLoadModel:
        def __init__(self, *args, **kwargs) -> None:
            raise AssertionError("invalid requests must be rejected before model loading")

    monkeypatch.setitem(sys.modules, "faster_whisper", SimpleNamespace(WhisperModel=MustNotLoadModel))
    monkeypatch.setattr(local_whisper_worker, "resolve_local_faster_whisper_model", lambda *_args: "resolved")

    exit_code = _run_main(monkeypatch, "--session-request", str(request_path))

    assert exit_code != 0
    assert "finite" in _stdout_events(capsys)[-1]["message"]


@pytest.mark.parametrize("invalid_threshold", [float("nan"), float("inf"), float("-inf")])
def test_session_rejects_non_finite_vad_threshold(tmp_path, monkeypatch, capsys, invalid_threshold) -> None:
    audio_path = (tmp_path / "chunk.mp3").resolve()
    result_path = (tmp_path / "chunk.json").resolve()
    audio_path.write_bytes(b"audio")
    request_path = tmp_path / "session.json"
    _write_session_request(
        request_path,
        model_root=tmp_path / "models",
        chunks=[{"index": 0, "audio_path": str(audio_path), "result_path": str(result_path)}],
    )
    request = json.loads(request_path.read_text(encoding="utf-8"))
    request["vad_threshold"] = invalid_threshold
    request_path.write_text(json.dumps(request), encoding="utf-8")

    exit_code = _run_main(monkeypatch, "--session-request", str(request_path))

    assert exit_code != 0
    assert "finite" in _stdout_events(capsys)[-1]["message"]


def test_legacy_single_audio_mode_still_returns_one_transcript_payload(tmp_path, monkeypatch, capsys) -> None:
    audio_path = tmp_path / "audio.mp3"
    audio_path.write_bytes(b"audio")
    model_root = tmp_path / "models"
    transcribe_calls: list[tuple[str, dict]] = []

    class FakeWhisperModel:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def transcribe(self, audio_path_arg: str, **kwargs):
            transcribe_calls.append((audio_path_arg, kwargs))
            return iter([SimpleNamespace(start=0, end=1.25, text="legacy text")]), object()

    monkeypatch.setitem(sys.modules, "faster_whisper", SimpleNamespace(WhisperModel=FakeWhisperModel))
    monkeypatch.setattr(local_whisper_worker, "resolve_local_faster_whisper_model", lambda *_args: "resolved")

    exit_code = _run_main(
        monkeypatch,
        "--audio",
        str(audio_path),
        "--model-root",
        str(model_root),
        "--language",
        "en",
    )

    assert exit_code == 0
    assert transcribe_calls == [
        (
            str(audio_path),
            {
                "language": "en",
                "vad_filter": True,
                "vad_parameters": {"min_silence_duration_ms": 500, "threshold": 0.5},
                "beam_size": 5,
                "best_of": 3,
            },
        )
    ]
    output_lines = capsys.readouterr().out.splitlines()
    assert len(output_lines) == 1
    payload = TranscriptPayload.model_validate_json(output_lines[0])
    assert payload.text == "legacy text"
    assert payload.segments[0].end == 1.25
