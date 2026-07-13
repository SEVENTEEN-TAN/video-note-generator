import json
from pathlib import Path

from backend.app.models import TranscriptPayload, TranscriptSegment
from backend.app.transcription_checkpoints import ChunkSpec, open_checkpoint_session
from backend.app.transcription_plans import TranscriptionExecutionPlan


def make_plan(*, beam_size: int) -> TranscriptionExecutionPlan:
    return TranscriptionExecutionPlan(
        performance_mode="balanced",
        device="cpu",
        compute_type="int8",
        cpu_threads=4,
        num_workers=1,
        beam_size=beam_size,
        best_of=2,
        vad_filter=True,
        vad_min_silence_ms=500,
        vad_threshold=0.5,
        chunk_seconds=600,
        chunk_overlap_seconds=1.0,
        checkpoint_enabled=True,
    )


def payload(start: float, end: float, text: str) -> TranscriptPayload:
    return TranscriptPayload(
        text=text,
        segments=[TranscriptSegment(start=start, end=end, text=text)],
    )


def make_session(tmp_path: Path, *, plan: TranscriptionExecutionPlan):
    source_path = tmp_path / "source.mp3"
    if not source_path.exists():
        source_path.write_bytes(b"audio")
    chunk_path = tmp_path / "chunks" / "chunk_000.mp3"
    chunk_path.parent.mkdir(parents=True, exist_ok=True)
    if not chunk_path.exists():
        chunk_path.write_bytes(b"chunk")
    chunks = [ChunkSpec(index=0, start=0.0, end=600.0, path=chunk_path)]
    return open_checkpoint_session(tmp_path, source_path, plan, chunks)


def make_completed_session(tmp_path: Path, *, beam_size: int):
    session = make_session(tmp_path, plan=make_plan(beam_size=beam_size))
    session.write_result(0, payload(0, 1, "hello"))
    return session


def make_two_chunk_session(tmp_path: Path):
    source_path = tmp_path / "source.mp3"
    source_path.write_bytes(b"audio")
    chunk_dir = tmp_path / "chunks"
    chunk_dir.mkdir(parents=True, exist_ok=True)
    chunks = []
    for index, start in enumerate((0.0, 600.0)):
        chunk_path = chunk_dir / f"chunk_{index:03d}.mp3"
        chunk_path.write_bytes(b"chunk")
        chunks.append(ChunkSpec(index=index, start=start, end=start + 600.0, path=chunk_path))
    return open_checkpoint_session(
        tmp_path,
        source_path,
        plan=make_plan(beam_size=3),
        chunks=chunks,
    )


def test_completed_chunk_survives_reopen(tmp_path):
    session = make_session(tmp_path, plan=make_plan(beam_size=3))
    session.write_result(0, payload(0, 1, "hello"))

    assert make_session(tmp_path, plan=make_plan(beam_size=3)).completed_indices() == {0}


def test_changed_plan_invalidates_results_not_chunks(tmp_path):
    make_completed_session(tmp_path, beam_size=3)

    reopened = make_session(tmp_path, plan=make_plan(beam_size=5))

    assert reopened.completed_indices() == set()
    assert reopened.chunks[0].path.exists()


def test_merge_offsets_chunks_in_order(tmp_path):
    session = make_two_chunk_session(tmp_path)
    session.write_result(0, payload(0, 2, "first"))
    session.write_result(1, payload(0, 3, "second"))

    assert [segment.start for segment in session.merge_results().segments] == [0.0, 600.0]


def test_invalid_partial_result_remains_pending(tmp_path):
    session = make_session(tmp_path, plan=make_plan(beam_size=3))
    result_path = session.write_result(0, payload(0, 1, "hello"))
    result_path.write_text('{"segments": [', encoding="utf-8")

    assert session.load_result(0) is None
    assert session.completed_indices() == set()


def test_manifest_stores_job_relative_paths(tmp_path):
    session = make_session(tmp_path, plan=make_plan(beam_size=3))

    manifest = json.loads(session.manifest_path.read_text(encoding="utf-8"))

    assert not Path(manifest["source"]["path"]).is_absolute()
    assert not Path(manifest["chunks"][0]["path"]).is_absolute()
