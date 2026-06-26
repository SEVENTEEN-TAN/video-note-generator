# 可用性与稳定性改进 Implementation Plan

> **For agentic workers / 给执行 Agent:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development（推荐）or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复任务路径、版本索引、ZIP、CUDA 提交和创建任务副作用风险，并把现有任务状态、失败恢复、产物下载、笔记版本选择做成更清楚可用的工作流。

**Architecture:** 后端只在现有 `main.py`、`note_versions.py`、`processor.py`、`job_store.py` 里增加小 helper，不重构接口层。前端继续保留 `App.tsx` 单文件工作台，只抽纯函数和轻量展示组件，样式补充到 `styles.css`。

**Tech Stack:** FastAPI、Pydantic、pytest、React、TypeScript、Vite、lucide-react、Windows 本地文件系统。

---

## 假设与边界

- 本阶段执行已批准的 B 范围：稳定性 BUG + 现有功能补充。
- 不实现“字幕校正后重新生成笔记”和“时间戳联动本地视频预览”，只保留在设计规格中作为下一阶段候选。
- 后端测试使用 `python -m pytest`，不要直接运行 `pytest`，因为当前 Windows 环境的 console script 路径不稳定。
- 前端当前没有单元测试配置，本阶段前端验证以 `npm --prefix frontend run build` 和手动冒烟路径为准。
- 所有用户可见文案使用中文；代码标识符按现有英文风格。

## 文件结构

- Modify: `backend/app/main.py`
  - 加固 `safe_job_dir()`。
  - 让 `create_job()` 先构造 `JobConfig`，再创建目录和复制文件。
  - 增加本地 CUDA runtime 未就绪时的 API 层拒绝。
  - 捕获创建任务阶段的 `OSError` 并清理本次新建目录。
- Modify: `backend/app/note_versions.py`
  - 防御式读取损坏的 `versions.json`。
  - 增加版本 id、版本路径的任务目录内安全解析。
  - 原子写入 `versions.json`。
  - 激活版本时只复制安全版本路径。
- Modify: `backend/app/processor.py`
  - `create_zip()` 改成临时文件写入后替换。
  - ZIP 打包版本 note 和 frames 时复用版本路径安全 helper。
- Modify: `backend/app/job_store.py`
  - 推断磁盘任务状态时不信任版本索引里的逃逸路径。
- Modify: `backend/tests/test_job_history.py`
  - 覆盖 encoded `.` job id 不能读取或删除 `OUTPUTS_ROOT`。
  - 覆盖损坏版本索引不会拖垮历史列表。
- Modify: `backend/tests/test_job_validation.py`
  - 覆盖非法 `JobConfig` 输入不会留下孤儿目录。
  - 覆盖复制上传失败时清理本次任务目录。
  - 覆盖本地 CUDA 未就绪时后端拒绝任务。
- Modify: `backend/tests/test_note_versions.py`
  - 覆盖损坏版本索引降级为空索引。
  - 覆盖恶意版本 id / note 路径 / frame 路径不会进入 ZIP 或被激活。
  - 覆盖 ZIP 写失败时保留旧 ZIP。
- Modify: `frontend/src/App.tsx`
  - 修正本地 CUDA readiness 判断。
  - 增加开始前检查摘要。
  - 增加进度详情、失败恢复、全部产物列表、下载成功消息、版本详情、ZIP 包含开关。
- Modify: `frontend/src/styles.css`
  - 补充上述轻量 UI 的样式，沿用现有 8px 圆角、低饱和工作台风格。

## 成功标准

- `GET /api/jobs/%2E` 返回 400，不能把 `outputs` 根目录当成任务。
- `DELETE /api/jobs/%2E` 返回 400，不能删除 `OUTPUTS_ROOT`。
- 损坏或恶意 `note_versions/versions.json` 不会让 `/api/jobs`、ZIP、预览、版本激活访问任务目录外文件。
- `versions.json` 和 `download.zip` 通过临时文件写入后替换。
- 本地 Faster Whisper 选择 CUDA 但 runtime 未就绪时，前端和后端都阻止任务创建。
- `JobConfig` 校验失败或视频复制失败时，不留下这次新建的任务目录。
- 主界面能看懂：开始前还缺什么、当前进行到哪里、失败后能下载什么、全部产物有哪些、哪些笔记版本会进 ZIP。
- `python -m pytest backend/tests` 通过。
- `npm --prefix frontend run build` 通过。

---

### Task 1: 后端任务 ID 路径安全

**Files:**
- Modify: `backend/tests/test_job_history.py`
- Modify: `backend/app/main.py`

- [ ] **Step 1: 写失败测试，证明 encoded `.` 不能读取 outputs 根目录**

Add to `backend/tests/test_job_history.py`:

```python
def test_get_job_rejects_encoded_dot_job_id_without_loading_outputs_root(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(main, "OUTPUTS_ROOT", tmp_path)
    monkeypatch.setattr(main, "store", JobStore(tmp_path))
    (tmp_path / "root-sentinel.txt").write_text("keep root", encoding="utf-8")

    response = TestClient(app, raise_server_exceptions=False).get("/api/jobs/%2E")

    assert response.status_code == 400
    assert response.json()["detail"] == "Invalid job id."
    assert (tmp_path / "root-sentinel.txt").exists()
```

- [ ] **Step 2: 写失败测试，证明 encoded `.` 不能删除 outputs 根目录**

Add to `backend/tests/test_job_history.py`:

```python
def test_delete_job_rejects_encoded_dot_job_id_without_deleting_outputs_root(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(main, "OUTPUTS_ROOT", tmp_path)
    monkeypatch.setattr(main, "store", JobStore(tmp_path))
    (tmp_path / "root-sentinel.txt").write_text("keep root", encoding="utf-8")

    response = TestClient(app, raise_server_exceptions=False).delete("/api/jobs/%2E")

    assert response.status_code == 400
    assert response.json()["detail"] == "Invalid job id."
    assert tmp_path.exists()
    assert (tmp_path / "root-sentinel.txt").exists()
```

- [ ] **Step 3: 运行目标测试，确认新增测试失败**

Run:

```powershell
python -m pytest backend/tests/test_job_history.py::test_get_job_rejects_encoded_dot_job_id_without_loading_outputs_root backend/tests/test_job_history.py::test_delete_job_rejects_encoded_dot_job_id_without_deleting_outputs_root
```

Expected: 两个测试至少有一个失败，因为当前 `safe_job_dir()` 允许 `job_dir == OUTPUTS_ROOT.resolve()`。

- [ ] **Step 4: 最小实现，加固 `safe_job_dir()`**

Replace `safe_job_dir()` in `backend/app/main.py` with:

```python
def safe_job_dir(job_id: str) -> Path:
    if not job_id or job_id in {".", ".."} or "/" in job_id or "\\" in job_id:
        raise HTTPException(status_code=400, detail="Invalid job id.")

    outputs_root = OUTPUTS_ROOT.resolve()
    job_dir = (outputs_root / job_id).resolve()
    if job_dir.parent != outputs_root:
        raise HTTPException(status_code=400, detail="Invalid job id.")
    if not job_dir.exists():
        raise HTTPException(status_code=404, detail="Job not found.")
    return job_dir
```

- [ ] **Step 5: 运行目标测试，确认通过**

Run:

```powershell
python -m pytest backend/tests/test_job_history.py::test_get_job_rejects_encoded_dot_job_id_without_loading_outputs_root backend/tests/test_job_history.py::test_delete_job_rejects_encoded_dot_job_id_without_deleting_outputs_root
```

Expected: PASS。

- [ ] **Step 6: 运行历史任务测试，确认没有破坏正常历史读取和删除**

Run:

```powershell
python -m pytest backend/tests/test_job_history.py
```

Expected: PASS。

- [ ] **Step 7: 提交**

```powershell
git add backend/app/main.py backend/tests/test_job_history.py
git commit -m "fix: reject unsafe job ids"
```

---

### Task 2: 创建任务前校验、CUDA 后端保护、失败清理

**Files:**
- Modify: `backend/tests/test_job_validation.py`
- Modify: `backend/app/main.py`

- [ ] **Step 1: 写失败测试，非法 `JobConfig` 不留下目录**

Add to `backend/tests/test_job_validation.py`:

```python
def test_create_job_rejects_invalid_config_before_creating_output_dir(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(main, "OUTPUTS_ROOT", tmp_path)
    monkeypatch.setattr(main, "store", JobStore(tmp_path))

    response = TestClient(app, raise_server_exceptions=False).post(
        "/api/jobs",
        data={
            "transcription_mode": "local_faster_whisper",
            "transcription_model": "small",
            "local_whisper_device": "gpu",
            "note_api_key": "note-key",
            "note_base_url": "https://api.openai.com/v1",
            "note_model": "gpt-5.5",
            "note_language": "zh",
            "note_style": "detailed",
            "frame_limit": "6",
        },
        files={"video": ("input.mp4", b"fake video", "video/mp4")},
    )

    assert response.status_code == 400
    assert "local_whisper_device must be auto, cpu, or cuda" in response.json()["detail"]
    assert list(tmp_path.iterdir()) == []
```

- [ ] **Step 2: 写失败测试，视频复制失败会清理新目录**

Add to `backend/tests/test_job_validation.py`:

```python
def test_create_job_cleans_output_dir_when_video_copy_fails(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(main, "OUTPUTS_ROOT", tmp_path)
    monkeypatch.setattr(main, "store", JobStore(tmp_path))

    def fail_copy(_source, _target) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(main.shutil, "copyfileobj", fail_copy)

    response = TestClient(app, raise_server_exceptions=False).post(
        "/api/jobs",
        data={
            "transcription_mode": "audio_transcriptions",
            "transcription_api_key": "transcription-key",
            "transcription_base_url": "https://api.openai.com/v1",
            "transcription_model": "whisper-1",
            "note_api_key": "note-key",
            "note_base_url": "https://api.openai.com/v1",
            "note_model": "gpt-5.5",
            "note_language": "zh",
            "note_style": "detailed",
            "frame_limit": "6",
        },
        files={"video": ("input.mp4", b"fake video", "video/mp4")},
    )

    assert response.status_code == 400
    assert "Cannot create job files" in response.json()["detail"]
    assert list(tmp_path.iterdir()) == []
```

- [ ] **Step 3: 写失败测试，CUDA runtime 未就绪时后端拒绝**

Add to `backend/tests/test_job_validation.py`:

```python
def test_create_job_rejects_local_cuda_when_runtime_is_not_ready(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(main, "OUTPUTS_ROOT", tmp_path)
    monkeypatch.setattr(main, "store", JobStore(tmp_path))
    monkeypatch.setattr(main, "resolve_local_faster_whisper_model", lambda *_args, **_kwargs: "small")
    monkeypatch.setattr(
        main,
        "get_runtime_status",
        lambda: {
            "faster_whisper": {
                "ready_for_cuda": False,
                "cuda_runtime_hint": "请安装 CUDA 运行库，或切回 CPU。",
                "cuda_error": "missing ctranslate2 cuda runtime",
            }
        },
    )

    response = TestClient(app, raise_server_exceptions=False).post(
        "/api/jobs",
        data={
            "transcription_mode": "local_faster_whisper",
            "transcription_model": "small",
            "local_whisper_device": "cuda",
            "local_whisper_compute_type": "float16",
            "note_api_key": "note-key",
            "note_base_url": "https://api.openai.com/v1",
            "note_model": "gpt-5.5",
            "note_language": "zh",
            "note_style": "detailed",
            "frame_limit": "6",
        },
        files={"video": ("input.mp4", b"fake video", "video/mp4")},
    )

    assert response.status_code == 400
    assert "CUDA" in response.json()["detail"]
    assert list(tmp_path.iterdir()) == []
```

- [ ] **Step 4: 运行目标测试，确认失败**

Run:

```powershell
python -m pytest backend/tests/test_job_validation.py::test_create_job_rejects_invalid_config_before_creating_output_dir backend/tests/test_job_validation.py::test_create_job_cleans_output_dir_when_video_copy_fails backend/tests/test_job_validation.py::test_create_job_rejects_local_cuda_when_runtime_is_not_ready
```

Expected: 新增测试失败，表现为状态码不对、目录残留或 CUDA 被错误放行。

- [ ] **Step 5: 修改 import**

In `backend/app/main.py`, add:

```python
from pydantic import ValidationError
```

- [ ] **Step 6: 增加 CUDA runtime helper**

Add this helper above `create_job()` in `backend/app/main.py`:

```python
def ensure_local_cuda_ready(config: JobConfig) -> None:
    if config.transcription_mode != TranscriptionMode.local_faster_whisper:
        return
    if str(config.local_whisper_device or "").strip() != "cuda":
        return

    runtime = get_runtime_status()
    faster_whisper = runtime.get("faster_whisper", {})
    if faster_whisper.get("ready_for_cuda"):
        return

    detail = (
        faster_whisper.get("cuda_runtime_hint")
        or faster_whisper.get("cuda_error")
        or "CUDA runtime is not ready. Install CUDA dependencies or switch local transcription to CPU."
    )
    raise HTTPException(status_code=400, detail=f"CUDA 未就绪：{detail}")
```

- [ ] **Step 7: 重排 `create_job()`，先构造 config，再做副作用**

In `backend/app/main.py`, move `JobConfig(...)` construction before `job_id = uuid.uuid4().hex`, wrap validation, then wrap directory creation/copy/metadata writes:

```python
    try:
        config = JobConfig(
            transcription_mode=transcription_mode,
            transcription_api_key=transcription_api_key,
            transcription_base_url=transcription_base_url,
            transcription_model=transcription_model,
            local_whisper_device=local_whisper_device,
            local_whisper_compute_type=local_whisper_compute_type,
            note_api_key=note_api_key,
            note_base_url=note_base_url,
            note_model=note_model,
            note_language=note_language,
            note_style=note_style,
            extras=extras,
            frame_limit=frame_limit,
            original_filename=video.filename or f"input{suffix}",
        )
    except ValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if config.transcription_mode == TranscriptionMode.local_faster_whisper:
        try:
            resolve_local_faster_whisper_model(config.transcription_model, get_faster_whisper_model_root())
        except TranscriptionError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        ensure_local_cuda_ready(config)

    job_id = uuid.uuid4().hex
    job_dir = OUTPUTS_ROOT / job_id
    source_dir = job_dir / "source_video"
    video_path = source_dir / f"input{suffix}"
    try:
        source_dir.mkdir(parents=True, exist_ok=True)
        with video_path.open("wb") as target:
            shutil.copyfileobj(video.file, target)
        write_job_metadata(
            job_id=job_id,
            job_dir=job_dir,
            config=config,
            title=config.original_filename,
            duration=None,
        )
    except OSError as exc:
        shutil.rmtree(job_dir, ignore_errors=True)
        raise HTTPException(status_code=400, detail=f"Cannot create job files: {exc}") from exc
```

Remove the old duplicated `JobConfig(...)` block after video copy.

- [ ] **Step 8: 运行目标测试，确认通过**

Run:

```powershell
python -m pytest backend/tests/test_job_validation.py::test_create_job_rejects_invalid_config_before_creating_output_dir backend/tests/test_job_validation.py::test_create_job_cleans_output_dir_when_video_copy_fails backend/tests/test_job_validation.py::test_create_job_rejects_local_cuda_when_runtime_is_not_ready
```

Expected: PASS。

- [ ] **Step 9: 运行创建任务相关测试**

Run:

```powershell
python -m pytest backend/tests/test_job_validation.py
```

Expected: PASS。

- [ ] **Step 10: 提交**

```powershell
git add backend/app/main.py backend/tests/test_job_validation.py
git commit -m "fix: validate jobs before file side effects"
```

---

### Task 3: 笔记版本路径安全、损坏索引降级、索引原子写入

**Files:**
- Modify: `backend/tests/test_note_versions.py`
- Modify: `backend/app/note_versions.py`
- Modify: `backend/app/main.py`

- [ ] **Step 1: 修改测试 import**

In `backend/tests/test_note_versions.py`, add:

```python
import pytest
```

- [ ] **Step 2: 写失败测试，损坏版本索引降级为空**

Add to `backend/tests/test_note_versions.py`:

```python
def test_load_note_version_index_returns_empty_index_when_json_is_corrupt(tmp_path) -> None:
    job_dir = tmp_path
    index_path = job_dir / "note_versions" / "versions.json"
    index_path.parent.mkdir(parents=True)
    index_path.write_text("{not valid json", encoding="utf-8")

    loaded = load_note_version_index(job_dir)

    assert loaded.active_version_id is None
    assert loaded.selected_version_ids == []
    assert loaded.versions == []
```

- [ ] **Step 3: 写失败测试，恶意版本路径被过滤**

Add to `backend/tests/test_note_versions.py`:

```python
def test_load_note_version_index_filters_versions_with_unsafe_paths(tmp_path) -> None:
    job_dir = tmp_path
    unsafe_note = make_version("note_001").model_copy(update={"note_path": "../secret.md"})
    unsafe_frames = make_version("note_002").model_copy(update={"frame_dir": "../frames"})
    unsafe_id = make_version("../note_003")
    safe = make_version("note_004")
    index_path = job_dir / "note_versions" / "versions.json"
    index_path.parent.mkdir(parents=True)
    index_path.write_text(
        NoteVersionIndex(
            active_version_id="note_001",
            selected_version_ids=["note_001", "note_002", "../note_003", "note_004"],
            versions=[unsafe_note, unsafe_frames, unsafe_id, safe],
        ).model_dump_json(indent=2),
        encoding="utf-8",
    )

    loaded = load_note_version_index(job_dir)

    assert [version.id for version in loaded.versions] == ["note_004"]
    assert loaded.active_version_id is None
    assert loaded.selected_version_ids == ["note_004"]
```

- [ ] **Step 4: 写失败测试，激活恶意版本不能复制外部文件**

Add to `backend/tests/test_note_versions.py`:

```python
def test_activate_note_version_rejects_filtered_unsafe_version(tmp_path) -> None:
    job_dir = tmp_path / "job"
    job_dir.mkdir()
    secret = tmp_path / "secret.md"
    secret.write_text("# secret", encoding="utf-8")
    index_path = job_dir / "note_versions" / "versions.json"
    index_path.parent.mkdir(parents=True)
    index_path.write_text(
        NoteVersionIndex(
            active_version_id="note_001",
            selected_version_ids=["note_001"],
            versions=[make_version("note_001").model_copy(update={"note_path": "../secret.md"})],
        ).model_dump_json(indent=2),
        encoding="utf-8",
    )

    with pytest.raises(FileNotFoundError):
        activate_note_version(job_dir, "note_001")

    assert not (job_dir / "note.md").exists()
```

- [ ] **Step 5: 运行目标测试，确认失败**

Run:

```powershell
python -m pytest backend/tests/test_note_versions.py::test_load_note_version_index_returns_empty_index_when_json_is_corrupt backend/tests/test_note_versions.py::test_load_note_version_index_filters_versions_with_unsafe_paths backend/tests/test_note_versions.py::test_activate_note_version_rejects_filtered_unsafe_version
```

Expected: 新增测试失败，当前代码会抛异常或信任恶意路径。

- [ ] **Step 6: 在 `note_versions.py` 增加安全 helper 和原子写入 helper**

Add to `backend/app/note_versions.py` after constants:

```python
def safe_note_version_id(version_id: str) -> str:
    if not version_id or version_id in {".", ".."} or "/" in version_id or "\\" in version_id:
        raise ValueError(f"Unsafe note version id: {version_id}")
    return version_id


def resolve_job_relative_path(job_dir: Path, relative_path: str) -> Path:
    if not relative_path or Path(relative_path).is_absolute():
        raise ValueError(f"Unsafe note version path: {relative_path}")
    root = job_dir.resolve()
    candidate = (root / relative_path).resolve()
    if candidate == root or root not in candidate.parents:
        raise ValueError(f"Unsafe note version path: {relative_path}")
    return candidate


def is_safe_note_version(job_dir: Path, version: NoteVersion) -> bool:
    try:
        safe_note_version_id(version.id)
        resolve_job_relative_path(job_dir, version.note_path)
        resolve_job_relative_path(job_dir, version.frame_dir)
    except ValueError:
        return False
    return True


def atomic_write_text(path: Path, text: str, *, encoding: str = "utf-8") -> None:
    tmp_path = path.with_name(f"{path.name}.tmp")
    try:
        tmp_path.write_text(text, encoding=encoding)
        tmp_path.replace(path)
    finally:
        if tmp_path.exists():
            tmp_path.unlink()
```

- [ ] **Step 7: 修改 `load_note_version_index()` 防御读取和过滤恶意版本**

Replace `load_note_version_index()` with:

```python
def load_note_version_index(job_dir: Path) -> NoteVersionIndex:
    path = note_version_index_path(job_dir)
    if not path.exists():
        return NoteVersionIndex()
    try:
        raw_index = NoteVersionIndex.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return NoteVersionIndex()

    safe_versions = [version for version in raw_index.versions if is_safe_note_version(job_dir, version)]
    return normalize_note_version_index(
        NoteVersionIndex(
            active_version_id=raw_index.active_version_id,
            selected_version_ids=raw_index.selected_version_ids,
            versions=safe_versions,
        )
    )
```

- [ ] **Step 8: 修改 `write_note_version_index()` 原子写入**

Replace `write_note_version_index()` with:

```python
def write_note_version_index(job_dir: Path, index: NoteVersionIndex) -> NoteVersionIndex:
    normalized = normalize_note_version_index(
        NoteVersionIndex(
            active_version_id=index.active_version_id,
            selected_version_ids=index.selected_version_ids,
            versions=[version for version in index.versions if is_safe_note_version(job_dir, version)],
        )
    )
    path = note_version_index_path(job_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(path, normalized.model_dump_json(indent=2), encoding="utf-8")
    return normalized
```

- [ ] **Step 9: 修改 `activate_note_version()` 使用安全路径**

Replace the path reads in `activate_note_version()`:

```python
    source_note = resolve_job_relative_path(job_dir, version.note_path)
    if source_note.exists():
        shutil.copyfile(source_note, job_dir / "note.md")

    root_frames = job_dir / "frames"
    if root_frames.exists():
        shutil.rmtree(root_frames)
    source_frames = resolve_job_relative_path(job_dir, version.frame_dir)
    if source_frames.exists():
        shutil.copytree(source_frames, root_frames)
```

- [ ] **Step 10: 修改 `create_note_version_from_draft()` 保护显式 version id**

Change the version id assignment:

```python
    version_id = safe_note_version_id(version_id or next_note_version_id(job_dir))
```

- [ ] **Step 11: 让版本切换接口返回客户端错误而不是 500**

In `backend/app/main.py`, wrap `activate_note_version()` in `update_note_version_selection()`:

```python
    if selection.active_version_id:
        try:
            index = activate_note_version(job_dir, selection.active_version_id)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
```

- [ ] **Step 12: 运行目标测试，确认通过**

Run:

```powershell
python -m pytest backend/tests/test_note_versions.py::test_load_note_version_index_returns_empty_index_when_json_is_corrupt backend/tests/test_note_versions.py::test_load_note_version_index_filters_versions_with_unsafe_paths backend/tests/test_note_versions.py::test_activate_note_version_rejects_filtered_unsafe_version
```

Expected: PASS。

- [ ] **Step 13: 运行版本测试**

Run:

```powershell
python -m pytest backend/tests/test_note_versions.py
```

Expected: PASS。

- [ ] **Step 14: 提交**

```powershell
git add backend/app/note_versions.py backend/app/main.py backend/tests/test_note_versions.py
git commit -m "fix: harden note version paths"
```

---

### Task 4: ZIP 安全、ZIP 原子写入、历史任务防御

**Files:**
- Modify: `backend/tests/test_note_versions.py`
- Modify: `backend/tests/test_job_history.py`
- Modify: `backend/app/processor.py`
- Modify: `backend/app/job_store.py`

- [ ] **Step 1: 写失败测试，ZIP 不包含恶意版本路径**

Add to `backend/tests/test_note_versions.py`:

```python
def test_create_zip_ignores_unsafe_note_version_paths_from_disk_index(tmp_path) -> None:
    job_dir = tmp_path / "job"
    job_dir.mkdir()
    secret = tmp_path / "secret.md"
    secret.write_text("# secret", encoding="utf-8")
    (job_dir / "note.md").write_text("# active", encoding="utf-8")
    index_path = job_dir / "note_versions" / "versions.json"
    index_path.parent.mkdir(parents=True)
    index_path.write_text(
        NoteVersionIndex(
            active_version_id="note_001",
            selected_version_ids=["note_001"],
            versions=[make_version("note_001").model_copy(update={"note_path": "../secret.md"})],
        ).model_dump_json(indent=2),
        encoding="utf-8",
    )

    zip_path = create_zip(job_dir)

    with ZipFile(zip_path) as archive:
        names = set(archive.namelist())
        payloads = {name: archive.read(name) for name in names}

    assert "note.md" in names
    assert "notes/note_001/note.md" not in names
    assert b"# secret" not in payloads.values()
```

- [ ] **Step 2: 写失败测试，ZIP 写失败保留旧包并清理临时文件**

Add to `backend/tests/test_note_versions.py`:

```python
def test_create_zip_keeps_existing_zip_when_rebuild_fails(tmp_path, monkeypatch) -> None:
    job_dir = tmp_path
    old_zip = job_dir / "download.zip"
    old_zip.write_bytes(b"old zip")

    class BrokenZipFile:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        def __enter__(self):
            raise RuntimeError("zip writer failed")

        def __exit__(self, *_args) -> bool:
            return False

    monkeypatch.setattr("backend.app.processor.ZipFile", BrokenZipFile)

    with pytest.raises(RuntimeError):
        create_zip(job_dir)

    assert old_zip.read_bytes() == b"old zip"
    assert not (job_dir / "download.zip.tmp").exists()
```

- [ ] **Step 3: 写失败测试，损坏版本索引不影响历史列表**

Add to `backend/tests/test_job_history.py`:

```python
def test_list_jobs_ignores_corrupt_note_version_index(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(main, "OUTPUTS_ROOT", tmp_path)
    monkeypatch.setattr(main, "store", JobStore(tmp_path))
    job_dir = tmp_path / "corrupt-version-job"
    job_dir.mkdir()
    (job_dir / "audio.mp3").write_bytes(b"mp3")
    (job_dir / "metadata.json").write_text(
        json.dumps(
            {
                "job_id": "corrupt-version-job",
                "created_at": "2026-06-23T00:00:00+00:00",
                "original_filename": "input.mp4",
                "title": "Corrupt",
                "duration_seconds": None,
            }
        ),
        encoding="utf-8",
    )
    version_index_path = job_dir / "note_versions" / "versions.json"
    version_index_path.parent.mkdir(parents=True)
    version_index_path.write_text("{broken", encoding="utf-8")

    response = TestClient(app, raise_server_exceptions=False).get("/api/jobs")

    assert response.status_code == 200
    assert response.json()["jobs"][0]["job_id"] == "corrupt-version-job"
    assert response.json()["jobs"][0]["note_version_count"] == 0
    assert response.json()["jobs"][0]["status"] == "failed"
```

- [ ] **Step 4: 运行目标测试，确认失败**

Run:

```powershell
python -m pytest backend/tests/test_note_versions.py::test_create_zip_ignores_unsafe_note_version_paths_from_disk_index backend/tests/test_note_versions.py::test_create_zip_keeps_existing_zip_when_rebuild_fails backend/tests/test_job_history.py::test_list_jobs_ignores_corrupt_note_version_index
```

Expected: 新增测试失败，当前 ZIP 直接写最终文件并信任版本路径。

- [ ] **Step 5: 修改 `processor.py` import**

In `backend/app/processor.py`, extend note version imports:

```python
from .note_versions import (
    create_note_version_from_draft,
    load_note_version_index,
    note_version_index_path,
    regenerate_note_version,
    resolve_job_relative_path,
    safe_note_version_id,
)
```

- [ ] **Step 6: 原子重写 `create_zip()`**

Replace `create_zip()` in `backend/app/processor.py` with:

```python
def create_zip(job_dir: Path) -> Path:
    zip_path = job_dir / "download.zip"
    tmp_path = job_dir / "download.zip.tmp"
    include_names = [
        "note.md",
        "audio.mp3",
        "subtitles.srt",
        "subtitles.vtt",
        "subtitles.md",
        "transcript.json",
        "metadata.json",
    ]
    try:
        with ZipFile(tmp_path, "w", compression=ZIP_DEFLATED) as archive:
            for name in include_names:
                file_path = job_dir / name
                if file_path.exists():
                    archive.write(file_path, arcname=name)
            frames_dir = job_dir / "frames"
            if frames_dir.exists():
                for frame_path in sorted(frames_dir.glob("*.jpg")):
                    archive.write(frame_path, arcname=frame_path.relative_to(job_dir).as_posix())
            version_index_path = note_version_index_path(job_dir)
            if version_index_path.exists():
                archive.write(version_index_path, arcname="notes/versions.json")
            version_index = load_note_version_index(job_dir)
            selected_ids = set(version_index.selected_version_ids)
            for version in version_index.versions:
                if version.id not in selected_ids:
                    continue
                try:
                    archive_version_id = safe_note_version_id(version.id)
                    note_path = resolve_job_relative_path(job_dir, version.note_path)
                    frame_dir = resolve_job_relative_path(job_dir, version.frame_dir)
                except ValueError:
                    continue
                if note_path.exists():
                    archive.write(note_path, arcname=f"notes/{archive_version_id}/note.md")
                if frame_dir.exists():
                    for frame_path in sorted(frame_dir.glob("*.jpg")):
                        archive.write(frame_path, arcname=f"notes/{archive_version_id}/frames/{frame_path.name}")
        tmp_path.replace(zip_path)
    finally:
        if tmp_path.exists():
            tmp_path.unlink()
    return zip_path
```

- [ ] **Step 7: 修改历史状态推断不信任版本路径**

In `backend/app/job_store.py`, add import:

```python
from .note_versions import resolve_job_relative_path
```

Replace `_infer_disk_job_status()` with:

```python
def _infer_disk_job_status(job_dir: Path, artifacts: list[Artifact], version_index) -> JobStatus:
    artifact_paths = {artifact.path for artifact in artifacts}
    if "note.md" in artifact_paths:
        return JobStatus.succeeded
    for version in version_index.versions:
        try:
            note_path = resolve_job_relative_path(job_dir, version.note_path)
        except ValueError:
            continue
        if note_path.exists():
            return JobStatus.succeeded
    return JobStatus.failed
```

- [ ] **Step 8: 运行目标测试，确认通过**

Run:

```powershell
python -m pytest backend/tests/test_note_versions.py::test_create_zip_ignores_unsafe_note_version_paths_from_disk_index backend/tests/test_note_versions.py::test_create_zip_keeps_existing_zip_when_rebuild_fails backend/tests/test_job_history.py::test_list_jobs_ignores_corrupt_note_version_index
```

Expected: PASS。

- [ ] **Step 9: 运行版本与历史测试**

Run:

```powershell
python -m pytest backend/tests/test_note_versions.py backend/tests/test_job_history.py
```

Expected: PASS。

- [ ] **Step 10: 提交**

```powershell
git add backend/app/processor.py backend/app/job_store.py backend/tests/test_note_versions.py backend/tests/test_job_history.py
git commit -m "fix: write safe note archives atomically"
```

---

### Task 5: 前端开始前检查与 CUDA 提交保护

**Files:**
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/styles.css`

- [ ] **Step 1: 增加检查项类型**

Add near frontend type declarations in `frontend/src/App.tsx`:

```tsx
type PreflightStatus = "ok" | "warn" | "blocked";

type PreflightItem = {
  key: string;
  title: string;
  detail: string;
  status: PreflightStatus;
  action?: "settings" | "download-model" | "switch-cpu";
};
```

- [ ] **Step 2: 修正本地转写 readiness 判断**

Replace:

```tsx
  const localTranscriptionReady = !isLocalTranscription || !runtimeLocalStatus || runtimeLocalStatus.ready_for_cpu;
```

with:

```tsx
  const selectedLocalRuntimeReady =
    !runtimeLocalStatus ||
    (localWhisperDevice === "cuda" ? runtimeLocalStatus.ready_for_cuda : runtimeLocalStatus.ready_for_cpu);
  const localTranscriptionReady = !isLocalTranscription || selectedLocalRuntimeReady;
```

- [ ] **Step 3: 增加开始前检查构造函数**

Add below `formatVersionDetails()` in `frontend/src/App.tsx`:

```tsx
function buildPreflightChecks({
  health,
  isLocalTranscription,
  localWhisperDevice,
  noteApiKey,
  runtimeLocalStatus,
  selectedLocalModelAvailable,
  transcriptionApiKey,
  transcriptionModel
}: {
  health: HealthState | null;
  isLocalTranscription: boolean;
  localWhisperDevice: LocalWhisperDevice;
  noteApiKey: string;
  runtimeLocalStatus?: RuntimeState["faster_whisper"];
  selectedLocalModelAvailable: boolean;
  transcriptionApiKey: string;
  transcriptionModel: string;
}): PreflightItem[] {
  const items: PreflightItem[] = [
    {
      key: "backend",
      title: "后端连接",
      detail: health ? "已连接" : "未连接到后端服务",
      status: health ? "ok" : "blocked"
    },
    {
      key: "ffmpeg",
      title: "FFmpeg",
      detail: health?.runtime?.ffmpeg.available || health?.ffmpeg_available ? "可用" : "缺少 FFmpeg，无法分离音频",
      status: health?.runtime?.ffmpeg.available || health?.ffmpeg_available ? "ok" : "blocked",
      action: "settings"
    },
    {
      key: "note-key",
      title: "笔记 API Key",
      detail: noteApiKey.trim() ? "已填写" : "未填写，无法生成笔记",
      status: noteApiKey.trim() ? "ok" : "blocked",
      action: "settings"
    }
  ];

  if (isLocalTranscription) {
    const runtimeReady =
      !runtimeLocalStatus ||
      (localWhisperDevice === "cuda" ? runtimeLocalStatus.ready_for_cuda : runtimeLocalStatus.ready_for_cpu);
    items.push(
      {
        key: "local-runtime",
        title: localWhisperDevice === "cuda" ? "本地转写 CUDA" : "本地转写 CPU",
        detail: runtimeReady
          ? "环境可用"
          : localWhisperDevice === "cuda"
            ? runtimeLocalStatus?.cuda_runtime_hint || runtimeLocalStatus?.cuda_error || "CUDA 运行库未就绪，可安装 CUDA 依赖或切回 CPU"
            : runtimeLocalStatus?.install_hint || runtimeLocalStatus?.worker_error || "本地转写依赖未就绪",
        status: runtimeReady ? "ok" : "blocked",
        action: localWhisperDevice === "cuda" ? "switch-cpu" : "settings"
      },
      {
        key: "local-model",
        title: "本地模型",
        detail: selectedLocalModelAvailable ? `${transcriptionModel} 已可用` : `未发现 ${transcriptionModel}`,
        status: selectedLocalModelAvailable ? "ok" : "blocked",
        action: "download-model"
      }
    );
  } else {
    items.push({
      key: "transcription-key",
      title: "转写 API Key",
      detail: transcriptionApiKey.trim() ? "已填写" : "未填写，无法远端转写",
      status: transcriptionApiKey.trim() ? "ok" : "blocked",
      action: "settings"
    });
  }

  return items;
}
```

- [ ] **Step 4: 在 `App()` 内生成检查项**

Add after readiness constants in `App()`:

```tsx
  const preflightChecks = useMemo(
    () =>
      buildPreflightChecks({
        health,
        isLocalTranscription,
        localWhisperDevice,
        noteApiKey,
        runtimeLocalStatus,
        selectedLocalModelAvailable,
        transcriptionApiKey,
        transcriptionModel
      }),
    [
      health,
      isLocalTranscription,
      localWhisperDevice,
      noteApiKey,
      runtimeLocalStatus,
      selectedLocalModelAvailable,
      transcriptionApiKey,
      transcriptionModel
    ]
  );
```

- [ ] **Step 5: 修正 `handleSubmit()` 的 CUDA 提示**

Replace the `if (!localTranscriptionReady)` body with:

```tsx
    if (!localTranscriptionReady) {
      if (localWhisperDevice === "cuda") {
        setSubmitError(
          runtimeLocalStatus?.cuda_runtime_hint ||
            runtimeLocalStatus?.cuda_error ||
            "CUDA 运行库未就绪，请在设置里安装 CUDA 依赖，或切回 CPU。"
        );
      } else {
        setSubmitError(runtimeLocalStatus?.install_hint || runtimeLocalStatus?.worker_error || "本地转写环境未就绪，请先补齐依赖。");
      }
      return;
    }
```

- [ ] **Step 6: 增加 `PreflightChecklist` 组件**

Add above `RuntimeStatusCard()` in `frontend/src/App.tsx`:

```tsx
function PreflightChecklist({
  items,
  onDownloadModel,
  onOpenSettings,
  onSwitchCpu
}: {
  items: PreflightItem[];
  onDownloadModel: () => void;
  onOpenSettings: () => void;
  onSwitchCpu: () => void;
}) {
  return (
    <section className="preflight-card" aria-label="开始前检查">
      <div className="section-title">
        <CheckCircle2 size={16} />
        <span>开始前检查</span>
      </div>
      <div className="preflight-list">
        {items.map((item) => (
          <div className={`preflight-item ${item.status}`} key={item.key}>
            {item.status === "ok" ? <CheckCircle2 size={15} /> : <AlertTriangle size={15} />}
            <div>
              <strong>{item.title}</strong>
              <span>{item.detail}</span>
            </div>
            {item.action === "settings" && (
              <button className="small-button" onClick={onOpenSettings} type="button">
                <Settings size={14} />
                设置
              </button>
            )}
            {item.action === "download-model" && (
              <button className="small-button" onClick={onDownloadModel} type="button">
                <Download size={14} />
                下载
              </button>
            )}
            {item.action === "switch-cpu" && (
              <button className="small-button" onClick={onSwitchCpu} type="button">
                CPU
              </button>
            )}
          </div>
        ))}
      </div>
    </section>
  );
}
```

- [ ] **Step 7: 在提交按钮上方渲染开始前检查**

In the `.config-submit-block` before `{submitError && (...)}`, add:

```tsx
              <PreflightChecklist
                items={preflightChecks}
                onDownloadModel={() => void handleDownloadLocalModel()}
                onOpenSettings={() => setIsSettingsOpen(true)}
                onSwitchCpu={() => setLocalWhisperDevice("cpu")}
              />
```

- [ ] **Step 8: 添加样式**

Add to `frontend/src/styles.css` near `.runtime-card` styles:

```css
.preflight-card {
  background: #ffffff;
  border: 1px solid var(--line);
  border-radius: 8px;
  display: grid;
  gap: 10px;
  padding: 11px;
}

.preflight-list {
  display: grid;
  gap: 7px;
}

.preflight-item {
  align-items: center;
  border: 1px solid #e1e7e4;
  border-radius: 8px;
  display: grid;
  gap: 8px;
  grid-template-columns: 18px minmax(0, 1fr) auto;
  min-height: 42px;
  padding: 8px;
}

.preflight-item.ok svg {
  color: var(--green);
}

.preflight-item.warn svg,
.preflight-item.blocked svg {
  color: var(--amber);
}

.preflight-item strong,
.preflight-item span {
  display: block;
}

.preflight-item strong {
  color: #263335;
  font-size: 12px;
  line-height: 1.2;
}

.preflight-item span {
  color: var(--muted);
  font-size: 12px;
  line-height: 1.35;
  margin-top: 2px;
}
```

- [ ] **Step 9: 构建验证**

Run:

```powershell
npm --prefix frontend run build
```

Expected: PASS。

- [ ] **Step 10: 提交**

```powershell
git add frontend/src/App.tsx frontend/src/styles.css
git commit -m "feat: show preflight readiness checks"
```

---

### Task 6: 长任务进度与失败恢复面板

**Files:**
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/styles.css`

- [ ] **Step 1: 增加进度阶段 helper**

Add above `StepList()` in `frontend/src/App.tsx`:

```tsx
type ProgressStageKey = "audio" | "subtitles" | "note" | "frames" | "output";

const progressStages: Array<{ key: ProgressStageKey; label: string; threshold: number; start: number; prefixes: string[] }> = [
  { key: "audio", label: "音频分离", threshold: 15, start: 5, prefixes: ["解析视频", "音频分离"] },
  { key: "subtitles", label: "字幕生成", threshold: 35, start: 16, prefixes: ["字幕生成", "转写", "本地转写"] },
  { key: "note", label: "笔记生成", threshold: 60, start: 36, prefixes: ["笔记生成", "重新生成笔记"] },
  { key: "frames", label: "关键帧抽取", threshold: 78, start: 61, prefixes: ["关键帧", "抽取"] },
  { key: "output", label: "Markdown 输出", threshold: 90, start: 79, prefixes: ["Markdown", "输出", "打包"] }
];

function deriveProgressStage(job: JobState | null): ProgressStageKey | null {
  if (!job) {
    return null;
  }
  const matched = progressStages.find((stage) => stage.prefixes.some((prefix) => job.step.includes(prefix)));
  if (matched) {
    return matched.key;
  }
  const byProgress = [...progressStages].reverse().find((stage) => job.progress >= stage.start);
  return byProgress?.key ?? null;
}
```

- [ ] **Step 2: 修改 `StepList()` 不再依赖中文完全相等**

Replace `StepList()` with:

```tsx
function StepList({ job }: { job: JobState | null }) {
  const activeStage = deriveProgressStage(job);
  return (
    <ol className="step-list">
      {progressStages.map((step, index) => {
        const done = (job?.progress ?? 0) >= step.threshold && job?.status !== "failed";
        const active = activeStage === step.key && job?.status !== "succeeded";
        return (
          <li className={done ? "done" : active ? "active" : ""} key={step.key}>
            <strong>{index + 1}</strong>
            <span>{step.label}</span>
          </li>
        );
      })}
    </ol>
  );
}
```

- [ ] **Step 3: 增加进度详情组件**

Add above `DownloadLink()` in `frontend/src/App.tsx`:

```tsx
function ProgressDetail({ job }: { job: JobState | null }) {
  if (!job) {
    return null;
  }
  return (
    <section className="progress-detail" aria-label="任务进度">
      <div>
        <strong>{job.step || statusText[job.status]}</strong>
        <span>{statusText[job.status]} · {Math.round(job.progress)}%</span>
      </div>
      <div className="progress-track" aria-hidden="true">
        <span style={{ width: `${Math.max(0, Math.min(100, job.progress))}%` }} />
      </div>
      <span>
        当前阶段耗时：{typeof job.stage_elapsed_seconds === "number" ? formatDuration(job.stage_elapsed_seconds) : "暂无"}
      </span>
    </section>
  );
}
```

- [ ] **Step 4: 增加失败恢复组件**

Add above `ProgressDetail()` in `frontend/src/App.tsx`:

```tsx
function FailureRecoveryPanel({
  isBusy,
  isRegenerating,
  job,
  onDownloadMessage,
  onRegenerate
}: {
  isBusy: boolean;
  isRegenerating: boolean;
  job: JobState | null;
  onDownloadMessage: (message: string) => void;
  onRegenerate: () => void;
}) {
  if (!job || job.status !== "failed") {
    return null;
  }
  const artifactPaths = new Set(job.artifacts.map((artifact) => artifact.path));
  const hasTranscript = artifactPaths.has("transcript.json");
  const hasSubtitle = artifactPaths.has("subtitles.srt") || artifactPaths.has("subtitles.vtt") || artifactPaths.has("subtitles.md");
  const hasAudio = artifactPaths.has("audio.mp3");
  const message = hasTranscript
    ? "已生成转写结果，可以下载字幕，或只重新生成笔记。"
    : hasSubtitle
      ? "已生成字幕，可以先下载字幕；重新生成笔记需要 transcript.json。"
      : hasAudio
        ? "已分离音频，可以先下载音频；修复转写设置后重新跑完整任务。"
        : "当前没有可复用产物，请修复设置或依赖后重新创建任务。";

  return (
    <section className="recovery-panel" aria-label="失败恢复">
      <div>
        <strong>失败恢复</strong>
        <span>{message}</span>
      </div>
      <div className="recovery-actions">
        {hasTranscript && (
          <ArtifactDownloadButton
            filename="transcript.json"
            label="转写 JSON"
            onMessage={onDownloadMessage}
            url={`/api/jobs/${job.job_id}/assets/transcript.json`}
          />
        )}
        {hasSubtitle && <DownloadLink job={job} artifactPath="subtitles.srt" label="SRT" onDownloadMessage={onDownloadMessage} />}
        {hasAudio && <DownloadLink job={job} artifactPath="audio.mp3" label="MP3" onDownloadMessage={onDownloadMessage} />}
        {hasTranscript && (
          <button className="small-button strong" disabled={isBusy} onClick={onRegenerate} type="button">
            {isRegenerating ? <Loader2 className="spin" size={15} /> : <RefreshCw size={15} />}
            只重新生成笔记
          </button>
        )}
      </div>
    </section>
  );
}
```

- [ ] **Step 5: 同步下载组件 prop 命名**

In this task, rename `onDownloadError` and `onError` props to `onDownloadMessage` and `onMessage` in `DownloadLink` / `ArtifactDownloadButton` call sites and function signatures. The final `ArtifactDownloadButton` click handler will be completed in Task 7.

The `DownloadLink` signature should become:

```tsx
function DownloadLink({
  artifactPath,
  job,
  label,
  onDownloadMessage
}: {
  artifactPath: string;
  job: JobState | null;
  label: string;
  onDownloadMessage: (message: string) => void;
}) {
```

- [ ] **Step 6: 在页面里渲染进度和失败恢复**

Inside `<form className="workspace-grid" ...>`, after the error box, add:

```tsx
        <ProgressDetail job={job} />
        <FailureRecoveryPanel
          isBusy={isBusy}
          isRegenerating={isRegenerating}
          job={job}
          onDownloadMessage={setDownloadMessage}
          onRegenerate={handleRegenerateNote}
        />
```

- [ ] **Step 7: 添加样式**

Add to `frontend/src/styles.css` near `.error-box`:

```css
.progress-detail,
.recovery-panel {
  background: #ffffff;
  border: 1px solid var(--line);
  border-radius: 8px;
  display: grid;
  gap: 9px;
  grid-column: 1 / -1;
  margin-top: 14px;
  padding: 12px;
}

.progress-detail strong,
.recovery-panel strong {
  color: #263335;
  display: block;
  font-size: 13px;
  line-height: 1.25;
}

.progress-detail span,
.recovery-panel span {
  color: var(--muted);
  display: block;
  font-size: 12px;
  line-height: 1.4;
  margin-top: 3px;
}

.progress-track {
  background: #e6ece9;
  border-radius: 999px;
  height: 8px;
  overflow: hidden;
}

.progress-track span {
  background: var(--teal);
  display: block;
  height: 100%;
}

.recovery-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}
```

- [ ] **Step 8: 构建验证**

Run:

```powershell
npm --prefix frontend run build
```

Expected: PASS。

- [ ] **Step 9: 提交**

```powershell
git add frontend/src/App.tsx frontend/src/styles.css
git commit -m "feat: clarify progress and failure recovery"
```

---

### Task 7: 全部产物下载、下载成功消息、版本信息、ZIP 包含开关

**Files:**
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/styles.css`

- [ ] **Step 1: 增强版本选项文案**

Replace `formatVersionOption()` with:

```tsx
function formatVersionOption(version: NoteVersion): string {
  const style = noteStyleOptions.find((option) => option.value === version.note_style)?.label ?? version.note_style;
  const state = version.active ? "当前" : "历史";
  return `${version.id} · ${state} · ${style} · ${formatHistoryTime(version.created_at)}`;
}
```

- [ ] **Step 2: 增加 artifact 文件名 helper**

Add below `deriveDownloadFilename()`:

```tsx
function formatArtifactLabel(artifact: Artifact): string {
  return artifact.label || deriveDownloadFilename(artifact.path, artifact.kind);
}
```

- [ ] **Step 3: 修改下载结果处理，显示成功路径或浏览器触发消息**

Replace `downloadArtifact()` with:

```tsx
async function downloadArtifact(url: string, filename: string) {
  if (isDesktopDownloadAvailable()) {
    return window.pywebview!.api!.save_file!(filename, buildAbsoluteUrl(url));
  }
  await triggerBrowserDownload(url, filename);
  return { ok: true, path: "" };
}
```

Replace `ArtifactDownloadButton()` with:

```tsx
function ArtifactDownloadButton({
  className = "small-button",
  filename,
  label,
  onMessage,
  url
}: {
  className?: string;
  filename: string;
  label: string;
  onMessage: (message: string) => void;
  url: string;
}) {
  async function handleClick() {
    onMessage("");
    try {
      const result = await downloadArtifact(url, filename);
      if (!result.ok && result.reason !== "cancelled") {
        onMessage("下载失败，请稍后重试。");
        return;
      }
      if (result.ok) {
        onMessage(result.path ? `已保存到 ${result.path}` : `已触发下载：${filename}`);
      }
    } catch (error) {
      onMessage(error instanceof Error ? error.message : "下载失败，请稍后重试。");
    }
  }

  return (
    <button className={className} onClick={handleClick} type="button">
      <Download size={15} />
      {label}
    </button>
  );
}
```

- [ ] **Step 4: 修改所有快捷下载调用**

Update result toolbar calls to:

```tsx
                <DownloadLink job={job} artifactPath="note.md" label="Markdown" onDownloadMessage={setDownloadMessage} />
                <DownloadLink job={job} artifactPath="subtitles.srt" label="SRT" onDownloadMessage={setDownloadMessage} />
                <DownloadLink job={job} artifactPath="audio.mp3" label="MP3" onDownloadMessage={setDownloadMessage} />
```

Update ZIP button prop:

```tsx
                    onMessage={setDownloadMessage}
```

- [ ] **Step 5: 增加 ZIP 包含开关 handler**

Add inside `App()` below `handleNoteVersionChange()`:

```tsx
  async function handleNoteVersionSelectedChange(versionId: string, selected: boolean) {
    if (!job || !noteVersions) {
      return;
    }
    const previous = noteVersions;
    const selectedIds = new Set(noteVersions.selected_version_ids.length ? noteVersions.selected_version_ids : noteVersions.versions.map((version) => version.id));
    if (selected) {
      selectedIds.add(versionId);
    } else {
      selectedIds.delete(versionId);
    }
    if (previewVersionId) {
      selectedIds.add(previewVersionId);
    }

    const optimistic = {
      ...noteVersions,
      selected_version_ids: Array.from(selectedIds),
      versions: noteVersions.versions.map((version) => ({
        ...version,
        selected: selectedIds.has(version.id)
      }))
    };
    setNoteVersions(optimistic);
    setVersionError("");
    try {
      const response = await fetch(`/api/jobs/${job.job_id}/note-versions`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          active_version_id: previewVersionId || noteVersions.active_version_id,
          selected_version_ids: Array.from(selectedIds)
        })
      });
      const payload = await response.json();
      if (!response.ok) {
        throw new Error(payload.detail || "ZIP 版本选择更新失败。");
      }
      setNoteVersions(payload);
      setPreviewVersionId(payload.active_version_id ?? previewVersionId);
      setJob(await fetchJob(job.job_id));
      await refreshJobHistory();
    } catch (error) {
      setNoteVersions(previous);
      setVersionError(error instanceof Error ? error.message : "ZIP 版本选择更新失败。");
    }
  }
```

- [ ] **Step 6: 增加版本管理组件**

Add above `ArtifactList()` in `frontend/src/App.tsx`:

```tsx
function VersionSelectionList({
  isBusy,
  noteVersions,
  onSelectedChange
}: {
  isBusy: boolean;
  noteVersions: NoteVersionIndex | null;
  onSelectedChange: (versionId: string, selected: boolean) => void;
}) {
  if (!noteVersions || noteVersions.versions.length === 0) {
    return null;
  }
  return (
    <section className="version-selection-list" aria-label="ZIP 笔记版本">
      <div className="section-title">
        <FileText size={16} />
        <span>ZIP 笔记版本</span>
      </div>
      {noteVersions.versions.map((version) => (
        <label className="version-selection-item" key={version.id}>
          <input
            checked={noteVersions.selected_version_ids.includes(version.id)}
            disabled={isBusy || version.active}
            type="checkbox"
            onChange={(event) => onSelectedChange(version.id, event.target.checked)}
          />
          <div>
            <strong>
              {version.id}
              {version.active ? " · 当前" : ""}
            </strong>
            <span>{formatVersionDetails(version)}</span>
          </div>
        </label>
      ))}
    </section>
  );
}
```

- [ ] **Step 7: 增加全部产物组件**

Add above `VersionSelectionList()` in `frontend/src/App.tsx`:

```tsx
function ArtifactList({
  job,
  onDownloadMessage
}: {
  job: JobState | null;
  onDownloadMessage: (message: string) => void;
}) {
  if (!job || job.artifacts.length === 0) {
    return null;
  }
  return (
    <section className="artifact-list" aria-label="全部产物">
      <div className="section-title">
        <FolderOpen size={16} />
        <span>全部产物</span>
      </div>
      <div className="artifact-list-grid">
        {job.artifacts.map((artifact) => (
          <div className="artifact-list-item" key={artifact.path}>
            <div>
              <strong>{formatArtifactLabel(artifact)}</strong>
              <span>{artifact.path}</span>
            </div>
            <ArtifactDownloadButton
              filename={deriveDownloadFilename(artifact.path, formatArtifactLabel(artifact))}
              label="下载"
              onMessage={onDownloadMessage}
              url={artifact.asset_url}
            />
          </div>
        ))}
      </div>
    </section>
  );
}
```

- [ ] **Step 8: 在结果区渲染版本选择和全部产物**

Inside `.result-body-scroll`, before `<div className="preview-stack">`, add:

```tsx
              <VersionSelectionList
                isBusy={isBusy}
                noteVersions={noteVersions}
                onSelectedChange={(versionId, selected) => void handleNoteVersionSelectedChange(versionId, selected)}
              />
              <ArtifactList job={job} onDownloadMessage={setDownloadMessage} />
```

- [ ] **Step 9: 调整下载消息样式语义**

The existing message can keep `inline-warning`, but success text should not use the warning icon. Replace the current download message block with:

```tsx
            {downloadMessage && (
              <p className={downloadMessage.startsWith("已") ? "inline-success" : "inline-warning"}>
                {downloadMessage.startsWith("已") ? <CheckCircle2 size={15} /> : <AlertTriangle size={15} />}
                {downloadMessage}
              </p>
            )}
```

- [ ] **Step 10: 添加样式**

Add to `frontend/src/styles.css` near result panel styles:

```css
.inline-success {
  align-items: flex-start;
  color: var(--green);
  display: flex;
  font-size: 13px;
  gap: 8px;
  line-height: 1.45;
  margin: 10px 0 0;
}

.artifact-list,
.version-selection-list {
  background: #ffffff;
  border: 1px solid var(--line);
  border-radius: 8px;
  display: grid;
  gap: 10px;
  margin-bottom: 12px;
  padding: 11px;
}

.artifact-list-grid {
  display: grid;
  gap: 8px;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
}

.artifact-list-item,
.version-selection-item {
  align-items: center;
  border: 1px solid #e1e7e4;
  border-radius: 8px;
  display: grid;
  gap: 9px;
  min-height: 46px;
  padding: 9px;
}

.artifact-list-item {
  grid-template-columns: minmax(0, 1fr) auto;
}

.version-selection-item {
  grid-template-columns: 18px minmax(0, 1fr);
}

.artifact-list-item strong,
.artifact-list-item span,
.version-selection-item strong,
.version-selection-item span {
  display: block;
}

.artifact-list-item strong,
.version-selection-item strong {
  color: #263335;
  font-size: 12px;
  line-height: 1.2;
}

.artifact-list-item span,
.version-selection-item span {
  color: var(--muted);
  font-size: 12px;
  line-height: 1.35;
  margin-top: 3px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
```

- [ ] **Step 11: 构建验证**

Run:

```powershell
npm --prefix frontend run build
```

Expected: PASS。

- [ ] **Step 12: 提交**

```powershell
git add frontend/src/App.tsx frontend/src/styles.css
git commit -m "feat: expose artifacts and zip version choices"
```

---

### Task 8: 全量验证与人工冒烟

**Files:**
- No code changes unless verification reveals a failure.

- [ ] **Step 1: 运行重点后端测试**

Run:

```powershell
python -m pytest backend/tests/test_job_validation.py
python -m pytest backend/tests/test_job_history.py
python -m pytest backend/tests/test_note_versions.py
```

Expected: 三条命令全部 PASS。

- [ ] **Step 2: 运行后端全量测试**

Run:

```powershell
python -m pytest backend/tests
```

Expected: PASS，当前基线是 84 个测试，新增测试后数量会增加。

- [ ] **Step 3: 运行前端构建**

Run:

```powershell
npm --prefix frontend run build
```

Expected: PASS。

- [ ] **Step 4: 手动检查 encoded dot 安全**

Run:

```powershell
python -m pytest backend/tests/test_job_history.py::test_get_job_rejects_encoded_dot_job_id_without_loading_outputs_root backend/tests/test_job_history.py::test_delete_job_rejects_encoded_dot_job_id_without_deleting_outputs_root
```

Expected: PASS，且测试里的 sentinel 文件仍存在。

- [ ] **Step 5: 手动冒烟前端关键路径**

Start the app using the repo's existing command from `README.md` or existing scripts. Then verify:

- 开始前检查在主配置面板提交按钮上方可见。
- 缺笔记 API Key 时显示阻塞项。
- 本地 CUDA 未就绪且选择 CUDA 时显示阻塞项，点击 `CPU` 会切回 CPU。
- 上传任务运行时顶部步骤条能高亮“字幕生成中：第 N/M 段转写中”这类详细 step。
- 失败任务显示恢复面板，已有 `audio.mp3` / `subtitles.srt` / `transcript.json` 时显示对应动作。
- 结果区显示“全部产物”。
- 下载成功后显示“已保存到 ...”或“已触发下载：文件名”。
- 笔记版本下拉显示 id、当前/历史、风格、时间。
- ZIP 笔记版本开关可以改变版本是否进入 ZIP，且不改变当前预览版本。

- [ ] **Step 6: 检查工作区差异**

Run:

```powershell
git status --short
git diff --stat
```

Expected: 只包含本计划范围内文件。

- [ ] **Step 7: 最终提交**

If Step 1-6 pass and there are uncommitted verification fixes:

```powershell
git add backend/app/main.py backend/app/note_versions.py backend/app/processor.py backend/app/job_store.py backend/tests/test_job_validation.py backend/tests/test_job_history.py backend/tests/test_note_versions.py frontend/src/App.tsx frontend/src/styles.css
git commit -m "chore: verify usability stability improvements"
```

If there are no uncommitted files, do not create an empty commit.

---

## 自检

- 规格覆盖：
  - 任务 ID 路径安全：Task 1。
  - `JobConfig` 副作用前校验和复制失败清理：Task 2。
  - CUDA 前后端保护：Task 2 和 Task 5。
  - 损坏版本索引降级、版本路径安全、激活安全：Task 3。
  - ZIP 安全和原子写入、历史任务不信任版本路径：Task 4。
  - 开始前检查摘要：Task 5。
  - 长任务进度清晰度和失败恢复：Task 6。
  - 完整产物下载、下载成功消息、版本元数据和 ZIP 选择：Task 7。
  - 全量验证：Task 8。
- 占位符扫描：
  - 本计划没有使用未定义的空白步骤。
  - 每个代码改动步骤都给出目标文件、代码片段和验证命令。
- 类型一致性：
  - 前端新增类型 `PreflightItem`、`PreflightStatus`、`ProgressStageKey` 均在使用前定义。
  - `DownloadLink` 统一使用 `onDownloadMessage`，`ArtifactDownloadButton` 统一使用 `onMessage`。
  - 后端新增 helper `safe_note_version_id`、`resolve_job_relative_path` 从 `note_versions.py` 导出并被 `processor.py`、`job_store.py` 使用。
