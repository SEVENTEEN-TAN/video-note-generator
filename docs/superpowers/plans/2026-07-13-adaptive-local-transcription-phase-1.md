# Adaptive Local Transcription Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a resumable, observable local Faster Whisper path that selects deterministic presets, loads one model per long task, persists completed chunks, and preserves existing artifacts and review flows.

**Architecture:** Add focused plan and checkpoint modules around `transcription.py`. The processor supplies cancellation and progress callbacks; internal and external implementations consume one immutable plan and write chunk results atomically. Existing artifact names and review contracts remain stable.

**Tech Stack:** Python 3.10+, FastAPI, Pydantic v2, Faster Whisper/CTranslate2, FFmpeg, React/TypeScript, pytest.

## Global Constraints

- Preserve unrelated dirty-worktree changes.
- Keep existing audio, transcript, subtitle, note, frame and ZIP names stable.
- Never persist API keys in plans, checkpoints, metadata, logs or ZIPs.
- Old jobs without `work/asr` and settings without `performance_mode` keep working.
- Modes are exactly `fast`, `balanced`, `accurate`; default is `balanced`.
- One long task creates one compatible model, not one per chunk.
- Compatible successful chunks are never retranscribed after restart.
- Checkpoint and final transcript writes use temporary-file replacement.
- Internal cancellation is cooperative; external cancellation terminates the worker.
- Remote transcription behavior is unchanged.

## File Structure

- Create `backend/app/transcription_plans.py`: hardware profile, execution plan and fingerprint.
- Create `backend/app/transcription_checkpoints.py`: manifests, atomic results and merge.
- Modify models/settings/API for mode, progress and resume contracts.
- Modify FFmpeg/transcription/worker/processor for session execution.
- Modify frontend types and app for mode, progress and resume UI.
- Add focused plan, checkpoint, worker and structural performance tests.

---

### Task 1: Deterministic Performance Modes and Plans

**Files:** Create `backend/app/transcription_plans.py`, `backend/tests/test_transcription_plans.py`; modify `models.py`, `settings.py`, `test_settings.py`.

**Interfaces:** Produces `PerformanceMode`, `HardwareProfile`, `TranscriptionExecutionPlan`, `resolve_execution_plan(config: JobConfig, duration_seconds: float, hardware: HardwareProfile) -> TranscriptionExecutionPlan`, and `plan_fingerprint(plan: TranscriptionExecutionPlan) -> str`.

- [ ] **Step 1: Write failing tests**

```python
def test_balanced_cpu_long_plan_uses_int8_checkpoints():
    plan = resolve_execution_plan(make_config("balanced", "auto", "default"), 10800, HardwareProfile(8, 16*1024**3, False, None))
    assert (plan.device, plan.compute_type, plan.chunk_seconds, plan.beam_size) == ("cpu", "int8", 600, 3)
    assert plan.checkpoint_enabled

def test_balanced_cuda_plan_prefers_float16():
    plan = resolve_execution_plan(make_config("balanced", "auto", "default"), 3600, HardwareProfile(12, 32*1024**3, True, 8*1024**3))
    assert (plan.device, plan.compute_type, plan.chunk_seconds) == ("cuda", "float16", 900)
```

- [ ] **Step 2: Run `pytest backend/tests/test_transcription_plans.py -q`**; expect import failure.

- [ ] **Step 3: Implement exact interfaces**

```python
class PerformanceMode(str, Enum):
    fast = "fast"
    balanced = "balanced"
    accurate = "accurate"

@dataclass(frozen=True)
class HardwareProfile:
    cpu_count: int
    memory_bytes: int | None
    cuda_available: bool
    cuda_memory_bytes: int | None

@dataclass(frozen=True)
class TranscriptionExecutionPlan:
    performance_mode: str
    device: str
    compute_type: str
    cpu_threads: int
    num_workers: int
    beam_size: int
    best_of: int
    vad_filter: bool
    vad_min_silence_ms: int
    vad_threshold: float
    chunk_seconds: int
    chunk_overlap_seconds: float
    checkpoint_enabled: bool
```

Fast uses beam/best-of 1/1, balanced 3/2, accurate 5/3. All phase-one presets enable VAD with 500 ms minimum silence and threshold 0.5; these values are part of the fingerprint because changing them can change transcript output. Up to 1800 seconds uses one chunk, up to 7200 uses 900-second chunks, longer uses 600-second chunks. Explicit runtime values override auto; auto CUDA uses float16, auto CPU int8. Persist mode with balanced default.

- [ ] **Step 4: Run `pytest backend/tests/test_transcription_plans.py backend/tests/test_settings.py -q`**; expect pass.

- [ ] **Step 5: Commit `feat: add adaptive transcription execution plans`.**

---

### Task 2: Atomic Chunk Checkpoints

**Files:** Create `backend/app/transcription_checkpoints.py`, `backend/tests/test_transcription_checkpoints.py`.

**Interfaces:** Produces `ChunkSpec`, `open_checkpoint_session(work_dir: Path, source_path: Path, plan: TranscriptionExecutionPlan, chunks: list[ChunkSpec]) -> TranscriptionCheckpointSession`, `completed_indices() -> set[int]`, `write_result(index: int, payload: TranscriptPayload) -> Path`, `load_result(index: int) -> TranscriptPayload | None`, and `merge_results() -> TranscriptPayload`.

- [ ] **Step 1: Write failing tests**

```python
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
    assert [s.start for s in session.merge_results().segments] == [0.0, 600.0]
```

- [ ] **Step 2: Run `pytest backend/tests/test_transcription_checkpoints.py -q`**; expect import failure.

- [ ] **Step 3: Implement job-relative manifests, size/mtime signatures, canonical plan fingerprints and atomic writes.**

```python
def atomic_write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f"{path.suffix}.tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)
```

Validate saved results with `TranscriptPayload.model_validate_json`; invalid partial files remain pending.

- [ ] **Step 4: Run checkpoint tests**; expect pass.

- [ ] **Step 5: Commit `feat: add resumable transcription checkpoints`.**

---

### Task 3: Direct ASR Audio Preparation

**Files:** Modify `backend/app/ffmpeg_tools.py`, `backend/tests/test_ffmpeg_tools.py`.

**Interfaces:** Produces `prepare_audio_artifacts(video_path, mp3_path, asr_dir, chunk_seconds) -> PreparedAudio` with ordered `ChunkSpec` values.

- [ ] **Step 1: Write failing tests**

```python
def test_long_asr_chunks_are_created_from_source_not_audio_mp3(tmp_path, monkeypatch):
    commands = capture_commands(monkeypatch)
    prepared = prepare_audio_artifacts(Path("input.mp4"), tmp_path/"audio.mp3", tmp_path/"work/asr", 600)
    assert all(command[command.index("-i") + 1] != str(tmp_path/"audio.mp3") for command in commands)
    assert prepared.chunks[0].path.suffix == ".flac"

def test_short_audio_creates_one_flac_chunk(tmp_path, monkeypatch):
    prepared = prepare_audio_artifacts(Path("input.mp4"), tmp_path/"audio.mp3", tmp_path/"work/asr", 0)
    assert [chunk.path.name for chunk in prepared.chunks] == ["chunk_000.flac"]
```

- [ ] **Step 2: Run focused FFmpeg tests**; expect missing function.

- [ ] **Step 3: Implement source-based 16kHz mono FLAC preparation.** Long inputs use the segment muxer; short inputs create `chunk_000.flac`. The local path must not call `split_audio(audio.mp3, ...)`.

- [ ] **Step 4: Run `pytest backend/tests/test_ffmpeg_tools.py -q`**; expect pass.

- [ ] **Step 5: Commit `perf: prepare local ASR audio directly from video`.**

---

### Task 4: One In-Process Model and Timestamp Progress

**Files:** Modify `backend/app/transcription.py`, `backend/tests/test_transcription.py`.

**Interfaces:** Consumes a plan, checkpoint session, `is_cancelled()` and progress callback; produces normal `TranscriptPayload` or raises `TranscriptionCancelled`.

- [ ] **Step 1: Write failing tests**

```python
def test_long_internal_transcription_loads_model_once(monkeypatch, tmp_path):
    factory = FakeWhisperModelFactory()
    monkeypatch.setattr(transcription, "WhisperModel", factory)
    transcribe_with_faster_whisper(audio_path, config, tmp_path)
    assert factory.load_count == 1

def test_completed_checkpoint_skips_model_call(monkeypatch, tmp_path):
    seed_first_chunk_checkpoint(tmp_path)
    model = install_fake_model(monkeypatch)
    transcribe_with_faster_whisper(audio_path, config, tmp_path)
    assert model.transcribed_names == ["chunk_001.flac"]
```

- [ ] **Step 2: Run focused tests**; expect model count greater than one or missing checkpoint integration.

- [ ] **Step 3: Create the model before pending-chunk iteration.** Manually consume segment iterators, check cancellation before each segment, report `completed_before + segment.end`, and atomically save each completed chunk.

- [ ] **Step 4: Run transcription and checkpoint tests**; expect pass.

- [ ] **Step 5: Commit `perf: reuse local whisper model across chunks`.**

---

### Task 5: One External Worker Session Per Task

**Files:** Modify `backend/app/local_whisper_worker.py`, `backend/app/transcription.py`; create `backend/tests/test_local_whisper_worker.py`; modify `test_transcription.py`.

**Interfaces:** Preserve legacy CLI. Add `--session-request <json>` and JSON Lines events: `ready`, `progress`, `chunk_complete`, `error`, `complete`.

- [ ] **Step 1: Write failing tests proving two chunks load one model and cancellation terminates `Popen`.**

```python
assert run_session_worker(two_chunk_request).model_load_count == 1
with pytest.raises(TranscriptionCancelled):
    run_external_session(
        request_path=request_path,
        python_path=python,
        worker_path=worker_path,
        is_cancelled=lambda: True,
        report=lambda event: None,
    )
assert fake_process.terminate_called
```

- [ ] **Step 2: Run worker/transcription tests**; expect missing protocol.

- [ ] **Step 3: Implement additive session mode.** Worker writes each result atomically and flushes events. Parent reads events, updates progress, validates results, polls cancellation, terminates then kills after timeout. Preserve `--runtime-status`, `--download-only`, and `--audio`.

- [ ] **Step 4: Run worker, transcription and runtime tests**; expect pass.

- [ ] **Step 5: Commit `perf: add single-load external whisper sessions`.**

---

### Task 6: Processor Integration and Resume API

**Files:** Modify `models.py`, `job_store.py`, `processor.py`, `main.py`, and processor/store/API tests.

**Interfaces:** Adds `TranscriptionWorkProgress` to public state and `POST /api/jobs/{job_id}/transcription/resume` for cancelled/interrupted local jobs.

- [ ] **Step 1: Write failing tests** proving the processor passes a live cancellation callback, a cancelled local job resumes, and remote/running jobs are rejected.

```python
response = client.post(f"/api/jobs/{local_cancelled}/transcription/resume")
assert response.status_code == 200
assert response.json()["resumed"] is True
assert client.post(f"/api/jobs/{remote_job}/transcription/resume").status_code == 409
```

- [ ] **Step 2: Run focused tests**; expect missing callback/endpoint.

- [ ] **Step 3: Add public progress model** with completed/total seconds, chunks, current chunk, realtime factor, ETA, resumable, cache hits, device and compute type. Add optional progress to `JobStore.update`.

- [ ] **Step 4: Integrate processor cancellation/checkpoints.** Catch `TranscriptionCancelled` separately and mark cancelled. Persist transcription language and performance mode. Resume only local inactive jobs with source video.

- [ ] **Step 5: Run processor/store/API/history tests**; expect pass.

- [ ] **Step 6: Commit `feat: resume interrupted local transcriptions`.**

---

### Task 7: Frontend Mode, Detailed Progress and Resume

**Files:** Modify `frontend/src/types.ts`, `App.tsx`, `constants.ts`, and frontend source-contract tests.

- [ ] **Step 1: Write failing tests** requiring all three mode values, `performance_mode` form submission, `work_progress`, and the text `继续转写`.

- [ ] **Step 2: Run `pytest backend/tests/test_frontend_styles.py -q`**; expect failure.

- [ ] **Step 3: Add exact TypeScript contracts**

```ts
export type PerformanceMode = "fast" | "balanced" | "accurate";
export type TranscriptionWorkProgress = {
  completed_seconds: number; total_seconds: number;
  completed_chunks: number; total_chunks: number;
  current_chunk?: number | null; realtime_factor?: number | null;
  eta_seconds?: number | null; resumable: boolean; cache_hits: number;
  device: string; compute_type: string;
};
```

Show mode only for local Faster Whisper, default balanced. Show processed duration, chunks, device and ETA. Show “继续转写” only when resumable; keep restart as a separate action.

- [ ] **Step 4: Run frontend tests and `npm --prefix frontend run build`**; expect pass.

- [ ] **Step 5: Commit `feat: expose adaptive local transcription controls`.**

---

### Task 8: Structural Performance Regression

**Files:** Create `backend/tests/test_local_transcription_performance.py`; modify `README.md`.

- [ ] **Step 1: Add tests proving a simulated two-hour job loads once, restart transcribes zero completed chunks, ASR chunks originate from source video, and external cancel terminates promptly.**

- [ ] **Step 2: Run `pytest backend/tests`**; expect all pass.

- [ ] **Step 3: Run `npm --prefix frontend run build`**; expect success.

- [ ] **Step 4: Run desktop/runtime tests**: `pytest backend/tests/test_desktop_launcher.py backend/tests/test_build_desktop_script.py backend/tests/test_runtime_api.py -q`.

- [ ] **Step 5: Document modes, checkpoint/resume behavior, internal cancellation limitations and cleanup without requiring users to understand low-level parameters.**

- [ ] **Step 6: Commit `test: verify resumable local transcription performance`.**

## Plan Self-Review Coverage

- Plans/modes: Task 1.
- Atomic compatible checkpoints: Task 2.
- No MP3-to-ASR second encode: Task 3.
- One internal model and real progress: Task 4.
- One external model and hard cancel: Task 5.
- Processor/public resume: Task 6.
- User-accessible controls: Task 7.
- Full regression evidence: Task 8.

Resource-aware stage scheduling, frame deduplication, lazy ZIP, disk estimation and cross-task model caching remain in the umbrella design and will use separate phase-two/phase-three plans after this independently testable phase is complete.
