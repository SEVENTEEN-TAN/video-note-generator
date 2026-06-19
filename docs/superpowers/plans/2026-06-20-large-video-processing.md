# 大视频处理能力改造 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 1 小时级大视频处理做到可预期、可观察、可降级，并降低超长字幕/上下文导致的失败风险。

**Architecture:** 保持现有串行处理管线不重构，只在转写、LLM 分块、任务状态和前端展示上做低侵入增强。后端通过可选进度回调把长耗时阶段内部状态写入 `JobStore`，前端展示阶段耗时和长视频提示；LLM 层保留现有 chunk/reduce 架构，增强分块边界和 compact reduce 测试保护。

**Tech Stack:** FastAPI + Python backend, Vite + React frontend, pytest, TypeScript.

---

## 0. 调研结论摘要

并行调研已覆盖 4 个独立方向：

1. **音轨提取与转写链路**
   - 主流程在 `backend/app/processor.py`。
   - FFmpeg 调用同步阻塞，音频提取与分片缺少阶段内进度。
   - `chat_audio` 对 1 小时视频约 30 个 120s chunk，请求数最多，适合作为兜底。
   - `audio_transcriptions` 超过 24MB 后默认约 600s 切片，1 小时约 6 段，相对更稳。
   - `local_faster_whisper` 当前整段音频输入模型，CPU 路径耗时风险最大。

2. **长字幕与长上下文处理**
   - `backend/app/llm.py` 已有 `MAX_SINGLE_PROMPT_CHARS`、`MAX_CHUNK_TRANSCRIPT_CHARS`、`MAX_REDUCE_PROMPT_CHARS`。
   - 已有 chunk -> reduce -> compact reduce 基础降级。
   - 风险是阈值按字符而非 token，分块按长度而非语义，`markdown_body` 无长度保护。

3. **前端长任务反馈**
   - `frontend/src/App.tsx` 当前展示 `status / step / progress / error / artifacts`。
   - 进度是阶段跳点，长时间停在“字幕生成/笔记生成”时用户容易误判为卡死。
   - 缺少阶段耗时、最后更新时间、预计 chunk 数和长视频提示。

4. **测试覆盖缺口**
   - 已有 `test_llm_chunking.py`、`test_processor.py`、`test_transcription.py` 基础覆盖。
   - 缺少真正超长 transcript 触发 `generate_note_draft()` chunk 路径、compact reduce、大量字幕段集成测试。

---

## 1. 文件结构与职责

### 后端

- Modify: `backend/app/models.py`
  - 给公开 job 状态增加可选阶段耗时字段。

- Modify: `backend/app/job_store.py`
  - 在任务状态更新时维护 `step_started_at`、`updated_at`、`stage_elapsed_seconds`。

- Modify: `backend/app/processor.py`
  - 把转写阶段进度回调传入 `transcribe_audio()`。
  - 保持原有处理顺序，不拆大管线。

- Modify: `backend/app/transcription.py`
  - 为远端分片转写和 chat audio 分片转写增加可选 `progress_callback`。
  - 不改变转写结果结构。

- Modify: `backend/app/llm.py`
  - 增加 token 近似估算函数。
  - 改进 transcript chunking：语义/时间间隔优先，长度兜底。
  - 限制 chunk prompt / reduce prompt 中不必要的冗余。

- Modify/Test: `backend/tests/test_llm_chunking.py`
  - 补超长 transcript 触发 chunked generation。
  - 补 compact reduce 分支。
  - 补边界长度测试。

- Modify/Test: `backend/tests/test_processor.py`
  - 补大量字幕段集成处理。

- Modify/Test: `backend/tests/test_subtitles.py`
  - 补大量 segment 渲染测试。

### 前端

- Modify: `frontend/src/App.tsx`
  - 扩展 `JobState` 类型。
  - 展示阶段耗时、最后更新时间、长视频提示。
  - 对 `chat_audio` + 大文件给出更明确提示。

---

## 2. 实施任务

### Task 1: 后端 Job 状态增加阶段耗时与更新时间

**Files:**
- Modify: `backend/app/models.py`
- Modify: `backend/app/job_store.py`
- Test: `backend/tests/test_processor.py` 或新增 `backend/tests/test_job_store.py`

- [ ] **Step 1: 写失败测试：状态更新时记录阶段开始与更新时间**

Create `backend/tests/test_job_store.py` if it does not exist:

```python
from backend.app.job_store import JobStore


def test_job_store_tracks_step_timing(tmp_path):
    store = JobStore(tmp_path)
    job_id = store.create_job()

    store.update(job_id, step="字幕生成中", progress=35)
    first = store.get(job_id)

    assert first is not None
    assert first.step == "字幕生成中"
    assert first.step_started_at is not None
    assert first.updated_at is not None
    assert first.stage_elapsed_seconds >= 0

    first_started_at = first.step_started_at

    store.update(job_id, step="字幕生成中", progress=40)
    second = store.get(job_id)

    assert second is not None
    assert second.step_started_at == first_started_at
    assert second.updated_at is not None
    assert second.stage_elapsed_seconds >= 0

    store.update(job_id, step="笔记生成中", progress=60)
    third = store.get(job_id)

    assert third is not None
    assert third.step == "笔记生成中"
    assert third.step_started_at is not None
    assert third.step_started_at != first_started_at
```

- [ ] **Step 2: 运行失败测试**

Run:

```bash
pytest "backend/tests/test_job_store.py" -v
```

Expected:

```text
FAILED ... AttributeError: 'JobPublicState' object has no attribute 'step_started_at'
```

- [ ] **Step 3: 修改 `backend/app/models.py`**

Add optional fields to `JobPublicState`:

```python
class JobPublicState(BaseModel):
    job_id: str
    status: JobStatus
    step: str
    progress: int = Field(ge=0, le=100)
    error: str | None = None
    artifacts: list[ArtifactInfo] = Field(default_factory=list)
    step_started_at: str | None = None
    updated_at: str | None = None
    stage_elapsed_seconds: float = 0
```

- [ ] **Step 4: 修改 `backend/app/job_store.py`**

Use timezone-aware timestamps and preserve `step_started_at` while step text is unchanged:

```python
from datetime import datetime, timezone


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
```

In job creation state, initialize:

```python
now = _now_iso()
state = JobPublicState(
    job_id=job_id,
    status=JobStatus.queued,
    step="排队中",
    progress=0,
    step_started_at=now,
    updated_at=now,
    stage_elapsed_seconds=0,
)
```

In `update(...)`, before assigning fields:

```python
now = _now_iso()
old_step = state.step
new_step = kwargs.get("step", old_step)

if new_step != old_step:
    state.step_started_at = now

state.updated_at = now

if state.step_started_at:
    started = datetime.fromisoformat(state.step_started_at)
    current = datetime.fromisoformat(now)
    state.stage_elapsed_seconds = max(0, (current - started).total_seconds())
```

Then apply existing field updates as the current implementation does.

- [ ] **Step 5: 运行测试**

Run:

```bash
pytest "backend/tests/test_job_store.py" -v
pytest "backend/tests/test_processor.py" -v
```

Expected:

```text
PASSED
```

---

### Task 2: 转写阶段增加细粒度进度回调

**Files:**
- Modify: `backend/app/transcription.py`
- Modify: `backend/app/processor.py`
- Test: `backend/tests/test_transcription.py`

- [ ] **Step 1: 写失败测试：远端分片转写报告 chunk 进度**

Add to `backend/tests/test_transcription.py`:

```python
def test_audio_transcriptions_reports_chunk_progress(monkeypatch, tmp_path):
    from backend.app.models import JobConfig, TranscriptionMode
    from backend.app.transcription import transcribe_with_audio_endpoint

    audio_path = tmp_path / "audio.mp3"
    audio_path.write_bytes(b"x" * 30_000_000)

    chunk_dir = tmp_path / "chunks"
    chunk_dir.mkdir()
    chunk_a = chunk_dir / "chunk_000.mp3"
    chunk_b = chunk_dir / "chunk_001.mp3"
    chunk_a.write_bytes(b"a")
    chunk_b.write_bytes(b"b")

    monkeypatch.setattr("backend.app.transcription.split_audio", lambda *_args, **_kwargs: [chunk_a, chunk_b])
    monkeypatch.setattr("backend.app.transcription.probe_duration", lambda _path: 10.0)

    def fake_transcribe_single_audio_file(*_args, **_kwargs):
        return {"text": "hello", "segments": [{"start": 0, "end": 1, "text": "hello"}]}

    monkeypatch.setattr(
        "backend.app.transcription.transcribe_single_audio_file",
        fake_transcribe_single_audio_file,
    )

    updates = []
    config = JobConfig(
        note_style="summary",
        frame_limit=1,
        transcription_mode=TranscriptionMode.audio_transcriptions,
        transcription_api_key="test-key",
        transcription_model="whisper-1",
    )

    result = transcribe_with_audio_endpoint(
        audio_path,
        config,
        tmp_path,
        progress_callback=lambda step, progress: updates.append((step, progress)),
    )

    assert result["text"] == "hello\nhello"
    assert updates == [
        ("字幕生成中：第 1/2 段转写中", 35),
        ("字幕生成中：第 2/2 段转写中", 47),
    ]
```

- [ ] **Step 2: 运行失败测试**

Run:

```bash
pytest "backend/tests/test_transcription.py" -k "reports_chunk_progress" -v
```

Expected:

```text
FAILED ... TypeError: transcribe_with_audio_endpoint() got an unexpected keyword argument 'progress_callback'
```

- [ ] **Step 3: 修改 `backend/app/transcription.py` 函数签名**

Use a simple callback type:

```python
from collections.abc import Callable

ProgressCallback = Callable[[str, int], None]
```

Update signatures:

```python
def transcribe_audio(
    audio_path: Path,
    config: JobConfig,
    job_dir: Path,
    progress_callback: ProgressCallback | None = None,
) -> dict[str, object]:
    ...
```

```python
def transcribe_with_audio_endpoint(
    audio_path: Path,
    config: JobConfig,
    job_dir: Path,
    progress_callback: ProgressCallback | None = None,
) -> dict[str, object]:
    ...
```

```python
def transcribe_with_chat_audio(
    audio_path: Path,
    config: JobConfig,
    job_dir: Path,
    progress_callback: ProgressCallback | None = None,
) -> dict[str, object]:
    ...
```

- [ ] **Step 4: 在分片循环中上报进度**

For `audio_transcriptions` chunk loop:

```python
chunk_count = len(chunks)
for index, chunk_path in enumerate(chunks, start=1):
    if progress_callback:
        progress = 35 + int((index - 1) / max(chunk_count, 1) * 25)
        progress_callback(f"字幕生成中：第 {index}/{chunk_count} 段转写中", progress)
    chunk_payload = transcribe_single_audio_file(chunk_path, config)
    ...
```

For `chat_audio` chunk loop:

```python
chunk_count = len(chunks)
for index, chunk_path in enumerate(chunks, start=1):
    if progress_callback:
        progress = 35 + int((index - 1) / max(chunk_count, 1) * 25)
        progress_callback(f"字幕生成中：第 {index}/{chunk_count} 段音频理解中", progress)
    ...
```

- [ ] **Step 5: 修改 `backend/app/processor.py` 传入回调**

Replace the transcription call:

```python
transcript_payload = transcribe_audio(
    audio_path,
    config,
    job_dir,
    progress_callback=lambda step, progress: store.update(
        job_id,
        step=step,
        progress=progress,
    ),
)
```

- [ ] **Step 6: 运行测试**

Run:

```bash
pytest "backend/tests/test_transcription.py" -k "reports_chunk_progress" -v
pytest "backend/tests/test_processor.py" -v
```

Expected:

```text
PASSED
```

---

### Task 3: 前端展示阶段耗时、最后更新时间和长视频提示

**Files:**
- Modify: `frontend/src/App.tsx`

- [ ] **Step 1: 扩展 `JobState` 类型**

In `frontend/src/App.tsx`, add optional fields matching backend response:

```ts
type JobState = {
  job_id: string;
  status: JobStatus;
  step: string;
  progress: number;
  error?: string | null;
  artifacts: ArtifactInfo[];
  step_started_at?: string | null;
  updated_at?: string | null;
  stage_elapsed_seconds?: number;
};
```

- [ ] **Step 2: 增加格式化函数**

Add near existing helpers:

```ts
function formatElapsedSeconds(seconds?: number): string {
  if (!seconds || seconds < 1) {
    return "少于 1 秒";
  }

  const totalSeconds = Math.floor(seconds);
  const minutes = Math.floor(totalSeconds / 60);
  const restSeconds = totalSeconds % 60;

  if (minutes === 0) {
    return `${restSeconds} 秒`;
  }

  return `${minutes} 分 ${restSeconds} 秒`;
}

function formatUpdateTime(value?: string | null): string {
  if (!value) {
    return "暂无";
  }

  return new Date(value).toLocaleTimeString();
}
```

- [ ] **Step 3: 在进度面板展示阶段耗时**

In the current progress panel around `frontend/src/App.tsx:732-743`, add:

```tsx
{job && job.status === "running" && (
  <div className="progress-meta">
    <span>当前阶段耗时：{formatElapsedSeconds(job.stage_elapsed_seconds)}</span>
    <span>最后更新：{formatUpdateTime(job.updated_at)}</span>
  </div>
)}
```

If `progress-meta` class does not exist, reuse existing small/muted text style already used in the file instead of introducing a new design system.

- [ ] **Step 4: 添加长视频提示文案**

Near upload/start area around `frontend/src/App.tsx:749-820`, add a non-blocking hint:

```tsx
<p className="form-hint">
  长视频处理可能长时间停留在“字幕生成”或“笔记生成”阶段。建议 1 小时级视频优先使用本地 CUDA 转写或 audio_transcriptions；chat_audio 更适合作为兜底模式。
</p>
```

- [ ] **Step 5: 运行前端类型检查/构建**

Run:

```bash
npm --prefix "frontend" run build
```

Expected:

```text
built in ...
```

---

### Task 4: LLM 分块增加 token 近似和语义边界优先

**Files:**
- Modify: `backend/app/llm.py`
- Test: `backend/tests/test_llm_chunking.py`

- [ ] **Step 1: 写失败测试：大间隔处优先断块**

Add to `backend/tests/test_llm_chunking.py`:

```python
def test_chunk_segments_prefers_large_time_gap():
    from backend.app.llm import chunk_segments
    from backend.app.models import TranscriptSegment

    segments = [
        TranscriptSegment(start=0, end=5, text="a" * 80),
        TranscriptSegment(start=6, end=10, text="b" * 80),
        TranscriptSegment(start=120, end=125, text="c" * 80),
    ]

    chunks = chunk_segments(segments, max_chars=240)

    assert len(chunks) == 2
    assert [segment.text[0] for segment in chunks[0]] == ["a", "b"]
    assert [segment.text[0] for segment in chunks[1]] == ["c"]
```

- [ ] **Step 2: 写失败测试：token 估算函数存在且单调**

```python
def test_estimate_prompt_tokens_is_monotonic():
    from backend.app.llm import estimate_prompt_tokens

    short = estimate_prompt_tokens("hello")
    long = estimate_prompt_tokens("hello " * 100)

    assert short >= 1
    assert long > short
```

- [ ] **Step 3: 运行失败测试**

Run:

```bash
pytest "backend/tests/test_llm_chunking.py" -k "large_time_gap or estimate_prompt_tokens" -v
```

Expected:

```text
FAILED
```

- [ ] **Step 4: 实现 `estimate_prompt_tokens`**

Add to `backend/app/llm.py`:

```python
def estimate_prompt_tokens(text: str) -> int:
    """Return a conservative token estimate without adding tokenizer dependencies."""
    if not text:
        return 0
    ascii_chars = sum(1 for char in text if ord(char) < 128)
    non_ascii_chars = len(text) - ascii_chars
    return max(1, (ascii_chars + 3) // 4 + non_ascii_chars)
```

- [ ] **Step 5: 改进 `chunk_segments`**

Keep the same public signature and add semantic split by large time gap:

```python
def chunk_segments(
    segments: list[TranscriptSegment],
    max_chars: int = MAX_CHUNK_TRANSCRIPT_CHARS,
) -> list[list[TranscriptSegment]]:
    chunks: list[list[TranscriptSegment]] = []
    current: list[TranscriptSegment] = []
    current_len = 0
    large_gap_seconds = 45

    for segment in segments:
        segment_len = len(segment.text) + 32
        has_large_gap = bool(current and segment.start - current[-1].end >= large_gap_seconds)
        would_exceed = bool(current and current_len + segment_len > max_chars)

        if has_large_gap or would_exceed:
            chunks.append(current)
            current = []
            current_len = 0

        current.append(segment)
        current_len += segment_len

    if current:
        chunks.append(current)

    return chunks
```

- [ ] **Step 6: 运行测试**

Run:

```bash
pytest "backend/tests/test_llm_chunking.py" -v
```

Expected:

```text
PASSED
```

---

### Task 5: 覆盖超长 transcript 触发 chunked generation 与 compact reduce

**Files:**
- Modify: `backend/tests/test_llm_chunking.py`

- [ ] **Step 1: 新增超长 transcript 触发 chunked generation 测试**

Add:

```python
def test_generate_note_draft_uses_chunked_path_for_long_transcript(monkeypatch):
    from backend.app import llm
    from backend.app.models import JobConfig, NoteDraft, TranscriptSegment

    calls = []

    def fake_generate_chunked_note_draft(config, duration, segments):
        calls.append(len(segments))
        return NoteDraft(
            title="长视频笔记",
            summary="summary",
            chapters=[],
            key_moments=[],
            key_takeaways=[],
            action_items=[],
            markdown_body="",
        )

    monkeypatch.setattr(llm, "generate_chunked_note_draft", fake_generate_chunked_note_draft)

    segments = [TranscriptSegment(start=i, end=i + 1, text="内容" * 500) for i in range(40)]
    config = JobConfig(note_style="summary", frame_limit=1)

    draft = llm.generate_note_draft(config, duration=3600, segments=segments)

    assert draft.title == "长视频笔记"
    assert calls == [40]
```

- [ ] **Step 2: 新增 compact reduce 分支测试**

Add:

```python
def test_reduce_prompt_compacts_when_full_reduce_is_too_large(monkeypatch):
    from backend.app import llm
    from backend.app.models import JobConfig, NoteDraft

    captured_prompts = []

    def fake_call_note_model(config, messages):
        captured_prompts.append(messages[-1]["content"])
        return NoteDraft(
            title="merged",
            summary="summary",
            chapters=[],
            key_moments=[],
            key_takeaways=[],
            action_items=[],
            markdown_body="",
        )

    monkeypatch.setattr(llm, "call_note_model", fake_call_note_model)

    partials = [
        NoteDraft(
            title=f"part-{index}",
            summary="s" * 5000,
            chapters=[],
            key_moments=[],
            key_takeaways=["k" * 5000],
            action_items=[],
            markdown_body="m" * 5000,
        )
        for index in range(8)
    ]

    config = JobConfig(note_style="summary", frame_limit=1)
    llm.reduce_note_drafts(config, duration=3600, partials=partials)

    assert captured_prompts
    assert "markdown_body" not in captured_prompts[-1]
```

If `reduce_note_drafts` does not currently exist as a helper, extract the reduce part from `generate_chunked_note_draft()` into that helper during implementation. Keep behavior unchanged.

- [ ] **Step 3: 运行测试**

Run:

```bash
pytest "backend/tests/test_llm_chunking.py" -v
```

Expected:

```text
PASSED
```

---

### Task 6: 大量字幕段处理集成测试

**Files:**
- Modify: `backend/tests/test_processor.py`
- Modify: `backend/tests/test_subtitles.py`

- [ ] **Step 1: 新增 subtitle 大量 segment 测试**

Add to `backend/tests/test_subtitles.py`:

```python
def test_render_subtitle_markdown_preserves_many_segments():
    from backend.app.models import TranscriptSegment
    from backend.app.subtitles import render_subtitle_markdown

    segments = [
        TranscriptSegment(start=i * 2, end=i * 2 + 1, text=f"第 {i} 段字幕")
        for i in range(300)
    ]

    markdown = render_subtitle_markdown(segments)

    assert "第 0 段字幕" in markdown
    assert "第 299 段字幕" in markdown
    assert markdown.index("第 0 段字幕") < markdown.index("第 299 段字幕")
```

- [ ] **Step 2: 新增 processor 大量 segments 集成测试**

Add to `backend/tests/test_processor.py`:

```python
def test_process_job_handles_many_transcript_segments(monkeypatch, tmp_path):
    from backend.app.job_store import JobStore
    from backend.app.models import JobConfig, NoteDraft, TranscriptSegment
    from backend.app.processor import process_job

    job_dir = tmp_path / "job"
    job_dir.mkdir()
    video_path = job_dir / "input.mp4"
    video_path.write_bytes(b"video")

    store = JobStore(tmp_path)
    job_id = store.create_job()

    segments = [
        {"start": i * 2, "end": i * 2 + 1, "text": f"第 {i} 段字幕"}
        for i in range(300)
    ]

    monkeypatch.setattr("backend.app.processor.probe_duration", lambda _path: 600.0)
    monkeypatch.setattr("backend.app.processor.extract_mp3", lambda _video, audio: audio.write_bytes(b"audio"))
    monkeypatch.setattr(
        "backend.app.processor.transcribe_audio",
        lambda *_args, **_kwargs: {"text": "\n".join(item["text"] for item in segments), "segments": segments},
    )
    monkeypatch.setattr(
        "backend.app.processor.generate_note_draft",
        lambda *_args, **_kwargs: NoteDraft(
            title="长视频",
            summary="summary",
            chapters=[],
            key_moments=[],
            key_takeaways=[],
            action_items=[],
            markdown_body="",
        ),
    )
    monkeypatch.setattr("backend.app.processor.capture_frame", lambda *_args, **_kwargs: None)

    process_job(
        store=store,
        job_id=job_id,
        job_dir=job_dir,
        video_path=video_path,
        config=JobConfig(note_style="summary", frame_limit=1),
    )

    state = store.get(job_id)
    assert state is not None
    assert state.status == "succeeded"
    assert (job_dir / "transcript.json").exists()
    assert (job_dir / "subtitles.md").exists()
    assert "第 299 段字幕" in (job_dir / "subtitles.md").read_text(encoding="utf-8")
    assert (job_dir / "download.zip").exists()
```

- [ ] **Step 3: 运行测试**

Run:

```bash
pytest "backend/tests/test_subtitles.py" "backend/tests/test_processor.py" -v
```

Expected:

```text
PASSED
```

---

## 3. 验证命令

完成所有任务后运行：

```bash
pytest "backend/tests" -v
npm --prefix "frontend" run build
```

Expected:

```text
PASSED
built in ...
```

如果测试失败，必须报告失败输出，不得声称完成。

---

## 4. 不做范围

本计划明确不做以下事项：

- 不重构整个 `process_job()` 为可恢复 DAG。
- 不引入 Redis、Celery、数据库或任务队列。
- 不实现真正 tokenizer 依赖，先用轻量 token 估算。
- 不做转写请求并发化，避免触发 API 限流和复杂错误恢复。
- 不修改 artifact 文件名，避免破坏前端下载/预览契约。
- 不执行 git commit / git push；除非用户后续明确要求。

---

## 5. 自检

- Spec coverage:
  - 1 小时视频速率/占用：Task 2、Task 3 覆盖可观察性；调研结论已明确 `chat_audio` / `audio_transcriptions` / local whisper 差异。
  - 字幕很多：Task 4、Task 5、Task 6 覆盖 chunking、compact reduce、大量字幕段。
  - 上下文超过：Task 4、Task 5 覆盖 token 估算、语义分块、chunked generation、compact reduce。
  - 并行智能体与整合：已在前置调研阶段完成，本计划基于整合结果。

- Placeholder scan:
  - 无 TBD / TODO / implement later。
  - 每个代码变更任务包含具体路径、代码片段、命令和期望结果。

- Type consistency:
  - 后端字段名为 `step_started_at`、`updated_at`、`stage_elapsed_seconds`。
  - 前端 `JobState` 使用相同字段名。
  - 进度回调签名固定为 `Callable[[str, int], None]`。
