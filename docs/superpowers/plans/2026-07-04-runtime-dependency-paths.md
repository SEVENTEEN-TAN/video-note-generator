# Runtime Dependency Paths Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add user-configurable local runtime paths so dependency detection, dependency installation, model download, and job validation use the same external Python and Faster Whisper model directory.

**Architecture:** Add a small backend runtime configuration helper that resolves environment variables, saved settings, and defaults in one place. Wire transcription, runtime status, model downloads, and package installers through that helper, then expose the new settings in the existing settings modal without changing the overall layout.

**Tech Stack:** FastAPI, Pydantic, pytest, React, TypeScript, Vite.

---

## File Structure

- Create: `backend/app/runtime_config.py`
  - Resolve external Python path, Faster Whisper model root, and pip install mode from environment variables, saved settings, and defaults.
- Modify: `backend/app/settings.py`
  - Persist user-configurable runtime path fields.
- Modify: `backend/app/transcription.py`
  - Use centralized Python/model path resolution.
- Modify: `backend/app/runtime_status.py`
  - Report path sources, configured errors, and install mode.
- Modify: `backend/app/install_tasks.py`
  - Allow pip install arguments before package names.
- Modify: `backend/app/local_dependencies.py`
  - Pass configured pip install arguments to local transcription package installer.
- Modify: `backend/app/cuda_dependencies.py`
  - Pass configured pip install arguments to CUDA package installer.
- Modify: `backend/tests/test_settings.py`
  - Cover persistence of the new settings fields.
- Create: `backend/tests/test_runtime_config.py`
  - Cover runtime path priority and install args.
- Modify: `backend/tests/test_install_tasks.py`
  - Cover `--user` pip install argument placement.
- Modify: `backend/tests/test_runtime_status.py`
  - Cover runtime status path source reporting.
- Modify: `backend/tests/test_model_downloads.py`
  - Cover settings-based model directory use.
- Modify: `frontend/src/App.tsx`
  - Add runtime path settings fields, runtime source labels, and advanced local path UI.
- Modify: `frontend/src/styles.css`
  - Add compact styles for the advanced local path UI.

---

### Task 1: Backend Settings And Runtime Config Helper

**Files:**
- Modify: `backend/app/settings.py`
- Create: `backend/app/runtime_config.py`
- Modify: `backend/tests/test_settings.py`
- Create: `backend/tests/test_runtime_config.py`

- [ ] **Step 1: Write failing settings persistence test**

Append this test to `backend/tests/test_settings.py`:

```python
def test_user_settings_roundtrip_persists_runtime_path_overrides(tmp_path, monkeypatch) -> None:
    settings_path = tmp_path / "settings.json"
    python_path = tmp_path / "Python310" / "python.exe"
    model_dir = tmp_path / "custom-models"
    python_path.parent.mkdir(parents=True)
    python_path.write_text("fake python", encoding="utf-8")
    monkeypatch.setenv("VIDEO_NOTE_SETTINGS_FILE", str(settings_path))

    saved = save_user_settings(
        {
            "external_python_path": str(python_path),
            "faster_whisper_model_dir": str(model_dir),
            "python_package_install_mode": "user",
        }
    )

    loaded = load_user_settings()
    payload = json.loads(settings_path.read_text(encoding="utf-8"))

    assert saved.external_python_path == str(python_path)
    assert saved.faster_whisper_model_dir == str(model_dir)
    assert saved.python_package_install_mode == "user"
    assert loaded == saved
    assert payload["external_python_path"] == str(python_path)
    assert payload["faster_whisper_model_dir"] == str(model_dir)
    assert payload["python_package_install_mode"] == "user"
```

- [ ] **Step 2: Write failing runtime config tests**

Create `backend/tests/test_runtime_config.py` with this content:

```python
from __future__ import annotations

from backend.app.runtime_config import (
    get_configured_external_python,
    get_configured_model_root,
    get_python_package_install_args,
    get_python_package_install_mode,
)
from backend.app.settings import save_user_settings


def test_configured_external_python_uses_saved_settings(tmp_path, monkeypatch) -> None:
    settings_path = tmp_path / "settings.json"
    python_path = tmp_path / "Python310" / "python.exe"
    python_path.parent.mkdir(parents=True)
    python_path.write_text("fake python", encoding="utf-8")
    monkeypatch.setenv("VIDEO_NOTE_SETTINGS_FILE", str(settings_path))
    monkeypatch.delenv("VIDEO_NOTE_PYTHON_PATH", raising=False)
    save_user_settings({"external_python_path": str(python_path)})

    configured = get_configured_external_python()

    assert configured.value == str(python_path)
    assert configured.source == "settings"
    assert configured.error == ""


def test_configured_external_python_prefers_environment(tmp_path, monkeypatch) -> None:
    settings_path = tmp_path / "settings.json"
    settings_python = tmp_path / "settings-python.exe"
    env_python = tmp_path / "env-python.exe"
    settings_python.write_text("settings", encoding="utf-8")
    env_python.write_text("env", encoding="utf-8")
    monkeypatch.setenv("VIDEO_NOTE_SETTINGS_FILE", str(settings_path))
    monkeypatch.setenv("VIDEO_NOTE_PYTHON_PATH", str(env_python))
    save_user_settings({"external_python_path": str(settings_python)})

    configured = get_configured_external_python()

    assert configured.value == str(env_python)
    assert configured.source == "environment"
    assert configured.error == ""


def test_configured_external_python_reports_missing_configured_path(tmp_path, monkeypatch) -> None:
    settings_path = tmp_path / "settings.json"
    missing_python = tmp_path / "missing" / "python.exe"
    monkeypatch.setenv("VIDEO_NOTE_SETTINGS_FILE", str(settings_path))
    monkeypatch.delenv("VIDEO_NOTE_PYTHON_PATH", raising=False)
    save_user_settings({"external_python_path": str(missing_python)})

    configured = get_configured_external_python()

    assert configured.value == str(missing_python)
    assert configured.source == "settings"
    assert "does not exist" in configured.error


def test_configured_model_root_uses_saved_settings(tmp_path, monkeypatch) -> None:
    settings_path = tmp_path / "settings.json"
    model_root = tmp_path / "custom-models"
    monkeypatch.setenv("VIDEO_NOTE_SETTINGS_FILE", str(settings_path))
    monkeypatch.delenv("FASTER_WHISPER_MODEL_DIR", raising=False)
    save_user_settings({"faster_whisper_model_dir": str(model_root)})

    configured = get_configured_model_root()

    assert configured.as_path() == model_root
    assert configured.source == "settings"
    assert configured.error == ""


def test_configured_model_root_prefers_environment(tmp_path, monkeypatch) -> None:
    settings_path = tmp_path / "settings.json"
    settings_model_root = tmp_path / "settings-models"
    env_model_root = tmp_path / "env-models"
    monkeypatch.setenv("VIDEO_NOTE_SETTINGS_FILE", str(settings_path))
    monkeypatch.setenv("FASTER_WHISPER_MODEL_DIR", str(env_model_root))
    save_user_settings({"faster_whisper_model_dir": str(settings_model_root)})

    configured = get_configured_model_root()

    assert configured.as_path() == env_model_root
    assert configured.source == "environment"


def test_python_package_install_args_support_user_mode(tmp_path, monkeypatch) -> None:
    settings_path = tmp_path / "settings.json"
    monkeypatch.setenv("VIDEO_NOTE_SETTINGS_FILE", str(settings_path))
    save_user_settings({"python_package_install_mode": "user"})

    assert get_python_package_install_mode() == "user"
    assert get_python_package_install_args() == ["--user"]
```

- [ ] **Step 3: Run RED tests**

Run:

```powershell
python -m pytest backend/tests/test_settings.py backend/tests/test_runtime_config.py -q
```

Expected: fail because `backend.app.runtime_config` and the new settings fields do not exist.

- [ ] **Step 4: Add settings fields and validators**

Modify imports in `backend/app/settings.py`:

```python
from typing import Any, Literal
```

Add this alias near `OPENAI_BASE_URL`:

```python
PythonPackageInstallMode = Literal["default", "user"]
```

Add these fields to `UserSettings` after `local_whisper_compute_type`:

```python
    external_python_path: str = ""
    faster_whisper_model_dir: str = ""
    python_package_install_mode: PythonPackageInstallMode = "default"
```

Add these fields to `UserSettingsUpdate` after `local_whisper_compute_type`:

```python
    external_python_path: str | None = None
    faster_whisper_model_dir: str | None = None
    python_package_install_mode: PythonPackageInstallMode | None = None
```

Add `"external_python_path"` and `"faster_whisper_model_dir"` to both existing text normalizers:

```python
        "external_python_path",
        "faster_whisper_model_dir",
```

- [ ] **Step 5: Create runtime config helper**

Create `backend/app/runtime_config.py` with this content:

```python
from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from .runtime_paths import get_app_data_root
from .settings import load_user_settings


RuntimeConfigSource = Literal["environment", "settings", "default", "missing"]
PythonPackageInstallMode = Literal["default", "user"]


@dataclass(frozen=True)
class RuntimePathResolution:
    value: str
    source: RuntimeConfigSource
    error: str = ""

    def as_path(self) -> Path:
        return Path(self.value).expanduser()


def get_configured_external_python() -> RuntimePathResolution:
    env_value = os.getenv("VIDEO_NOTE_PYTHON_PATH", "").strip()
    if env_value:
        return _resolve_python_candidate(env_value, "environment")

    settings_value = load_user_settings().external_python_path.strip()
    if settings_value:
        return _resolve_python_candidate(settings_value, "settings")

    for executable in ("python", "python3", "py"):
        path = shutil.which(executable)
        if path:
            return RuntimePathResolution(value=path, source="default")
    return RuntimePathResolution(
        value="",
        source="missing",
        error="External Python was not found on PATH. Install Python 3.10+ or set VIDEO_NOTE_PYTHON_PATH.",
    )


def get_configured_model_root() -> RuntimePathResolution:
    env_value = os.getenv("FASTER_WHISPER_MODEL_DIR", "").strip()
    if env_value:
        return RuntimePathResolution(value=str(Path(env_value).expanduser()), source="environment")

    settings_value = load_user_settings().faster_whisper_model_dir.strip()
    if settings_value:
        return RuntimePathResolution(value=str(Path(settings_value).expanduser()), source="settings")

    return RuntimePathResolution(
        value=str(get_app_data_root() / "backend" / "models" / "faster-whisper"),
        source="default",
    )


def get_python_package_install_mode() -> PythonPackageInstallMode:
    return load_user_settings().python_package_install_mode


def get_python_package_install_args() -> list[str]:
    if get_python_package_install_mode() == "user":
        return ["--user"]
    return []


def _resolve_python_candidate(value: str, source: RuntimeConfigSource) -> RuntimePathResolution:
    resolved = shutil.which(value)
    if resolved:
        return RuntimePathResolution(value=resolved, source=source)

    path = Path(value).expanduser()
    looks_like_path = path.is_absolute() or "\\" in value or "/" in value
    if looks_like_path and not path.exists():
        return RuntimePathResolution(
            value=str(path),
            source=source,
            error=f"Configured external Python path does not exist: {path}",
        )
    return RuntimePathResolution(value=str(path) if looks_like_path else value, source=source)
```

- [ ] **Step 6: Run GREEN tests for settings/config**

Run:

```powershell
python -m pytest backend/tests/test_settings.py backend/tests/test_runtime_config.py -q
```

Expected: pass.

- [ ] **Step 7: Commit backend config helper**

Run:

```powershell
git add backend/app/settings.py backend/app/runtime_config.py backend/tests/test_settings.py backend/tests/test_runtime_config.py
git commit -m "feat: add runtime dependency path settings"
```

---

### Task 2: Wire Backend Detection, Install, And Model Paths

**Files:**
- Modify: `backend/app/transcription.py`
- Modify: `backend/app/runtime_status.py`
- Modify: `backend/app/install_tasks.py`
- Modify: `backend/app/local_dependencies.py`
- Modify: `backend/app/cuda_dependencies.py`
- Modify: `backend/tests/test_install_tasks.py`
- Modify: `backend/tests/test_runtime_status.py`
- Modify: `backend/tests/test_model_downloads.py`

- [ ] **Step 1: Write failing install args test**

Append this test to `backend/tests/test_install_tasks.py`:

```python
def test_package_install_controller_passes_install_args_before_packages(monkeypatch) -> None:
    calls: list[list[str]] = []
    controller = PackageInstallController(
        packages=PACKAGES,
        failure_message="install failed",
        python_finder=lambda: "python",
        install_args_provider=lambda: ["--user"],
    )

    def fake_run(command, **_kwargs):
        calls.append(command)
        return type("Completed", (), {"returncode": 0, "stdout": "", "stderr": ""})()

    monkeypatch.setattr("backend.app.install_tasks.subprocess.run", fake_run)

    controller.run()

    assert calls == [["python", "-m", "pip", "install", "--user", "demo-package"]]
```

- [ ] **Step 2: Write failing runtime status source test**

Append this test to `backend/tests/test_runtime_status.py`:

```python
def test_runtime_status_reports_configured_path_sources(tmp_path, monkeypatch) -> None:
    from backend.app.settings import save_user_settings

    settings_path = tmp_path / "settings.json"
    python_path = tmp_path / "Python310" / "python.exe"
    worker_path = tmp_path / "worker.py"
    model_root = tmp_path / "custom-models"
    python_path.parent.mkdir(parents=True)
    python_path.write_text("fake python", encoding="utf-8")
    worker_path.write_text("print('worker')", encoding="utf-8")
    write_model_files(model_root / "small")

    monkeypatch.setenv("VIDEO_NOTE_SETTINGS_FILE", str(settings_path))
    monkeypatch.delenv("VIDEO_NOTE_PYTHON_PATH", raising=False)
    monkeypatch.delenv("FASTER_WHISPER_MODEL_DIR", raising=False)
    save_user_settings(
        {
            "external_python_path": str(python_path),
            "faster_whisper_model_dir": str(model_root),
            "python_package_install_mode": "user",
        }
    )
    monkeypatch.setattr(runtime_status, "get_ffmpeg_path", lambda: "C:/ffmpeg/bin/ffmpeg.exe")
    monkeypatch.setattr(transcription, "WhisperModel", None)
    monkeypatch.setattr(transcription, "FASTER_WHISPER_IMPORT_ERROR", "No module named 'faster_whisper'")
    monkeypatch.setattr(transcription, "get_local_whisper_worker_path", lambda: worker_path)
    monkeypatch.setattr(
        runtime_status,
        "get_external_runtime_status",
        lambda *_args: {
            "python_path": str(python_path),
            "faster_whisper_available": True,
            "faster_whisper_error": "",
            "ctranslate2_available": True,
            "ctranslate2_version": "4.5.0",
            "cuda_device_count": None,
            "cuda_runtime_available": False,
            "cuda_error": "",
            "cuda_dll_dirs": [],
            "source": "external",
        },
    )

    status = runtime_status.get_runtime_status()

    assert status["faster_whisper"]["external_python_path"] == str(python_path)
    assert status["faster_whisper"]["external_python_source"] == "settings"
    assert status["faster_whisper"]["external_python_error"] == ""
    assert status["faster_whisper"]["python_package_install_mode"] == "user"
    assert status["local_models"]["root"] == str(model_root)
    assert status["local_models"]["root_source"] == "settings"
    assert status["local_models"]["models"] == ["small"]
```

- [ ] **Step 3: Write failing model download settings path test**

Append this test to `backend/tests/test_model_downloads.py`:

```python
def test_model_download_state_uses_saved_model_directory(tmp_path, monkeypatch) -> None:
    from backend.app.settings import save_user_settings

    settings_path = tmp_path / "settings.json"
    model_root = tmp_path / "settings-models"
    monkeypatch.setenv("VIDEO_NOTE_SETTINGS_FILE", str(settings_path))
    monkeypatch.delenv("FASTER_WHISPER_MODEL_DIR", raising=False)
    save_user_settings({"faster_whisper_model_dir": str(model_root)})
    write_model_files(model_root / "small")
    model_downloads.clear_model_download_states()

    state = model_downloads.get_model_download_state("small")

    assert state.status == "succeeded"
    assert state.model_root == str(model_root)
```

- [ ] **Step 4: Run RED tests**

Run:

```powershell
python -m pytest backend/tests/test_install_tasks.py backend/tests/test_runtime_status.py backend/tests/test_model_downloads.py -q
```

Expected: fail because install args and runtime status source fields are not wired.

- [ ] **Step 5: Wire pip install arguments**

Modify `backend/app/install_tasks.py`.

Update imports:

```python
from collections.abc import Callable, Sequence
```

Change `PackageInstallController.__init__` signature and body:

```python
    def __init__(
        self,
        *,
        packages: Sequence[str],
        failure_message: str,
        python_finder: Callable[[], str | None] | None = None,
        install_args_provider: Callable[[], Sequence[str]] | None = None,
    ) -> None:
        self._packages = tuple(packages)
        self._failure_message = failure_message
        self._python_finder = python_finder
        self._install_args_provider = install_args_provider
        self._state = PackageInstallState()
        self._lock = threading.Lock()
```

Change the command in `install_packages`:

```python
        install_args = list(self._install_args_provider() if self._install_args_provider else [])
        completed = subprocess.run(
            [
                python_path,
                "-m",
                "pip",
                "install",
                *install_args,
                *self._packages,
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=external_worker_env(),
        )
```

Modify `backend/app/local_dependencies.py`:

```python
from .runtime_config import get_python_package_install_args
```

Pass the provider into `_controller`:

```python
_controller = PackageInstallController(
    packages=LOCAL_TRANSCRIPTION_DEPENDENCY_PACKAGES,
    failure_message="Local transcription dependency installation failed.",
    python_finder=find_external_python,
    install_args_provider=get_python_package_install_args,
)
```

Modify `backend/app/cuda_dependencies.py` the same way:

```python
from .runtime_config import get_python_package_install_args
```

```python
_controller = PackageInstallController(
    packages=CUDA_DEPENDENCY_PACKAGES,
    failure_message="CUDA dependency installation failed.",
    python_finder=find_external_python,
    install_args_provider=get_python_package_install_args,
)
```

- [ ] **Step 6: Wire transcription path helpers**

Modify imports in `backend/app/transcription.py`:

```python
from .runtime_config import get_configured_external_python, get_configured_model_root
from .runtime_paths import get_bundle_root
```

Remove the `FASTER_WHISPER_MODEL_ROOT = get_model_root()` constant and change `get_faster_whisper_model_root()`:

```python
def get_faster_whisper_model_root() -> Path:
    return get_configured_model_root().as_path()
```

Replace `find_external_python()` with:

```python
def find_external_python() -> str | None:
    configured = get_configured_external_python()
    if configured.error:
        return None
    return configured.value or None
```

- [ ] **Step 7: Wire runtime status source fields**

Modify imports in `backend/app/runtime_status.py`:

```python
from .runtime_config import get_configured_external_python, get_configured_model_root, get_python_package_install_mode
```

Remove the import of `get_model_root`.

In `get_runtime_status()`, replace the external Python and model root setup with:

```python
    external_python = get_configured_external_python()
    external_python_path = None if external_python.error else external_python.value
    external_worker_path = transcription.get_local_whisper_worker_path()
    external_worker_available = bool(external_python_path) and external_worker_path.exists()
    external_runtime = (
        get_external_runtime_status(external_python_path, str(external_worker_path)) if external_worker_available else None
    )
    python_available = bool(external_python_path)
```

Replace model root setup with:

```python
    model_root_config = get_configured_model_root()
    model_root = model_root_config.as_path()
    local_models = transcription.discover_local_faster_whisper_models(model_root)
```

Add these fields inside the returned `"faster_whisper"` object:

```python
            "external_python_source": external_python.source,
            "external_python_error": external_python.error,
            "python_package_install_mode": get_python_package_install_mode(),
```

Add this field inside the returned `"local_models"` object:

```python
            "root_source": model_root_config.source,
```

- [ ] **Step 8: Run GREEN backend wiring tests**

Run:

```powershell
python -m pytest backend/tests/test_install_tasks.py backend/tests/test_runtime_status.py backend/tests/test_model_downloads.py backend/tests/test_transcription.py -q
```

Expected: pass.

- [ ] **Step 9: Commit backend wiring**

Run:

```powershell
git add backend/app/transcription.py backend/app/runtime_status.py backend/app/install_tasks.py backend/app/local_dependencies.py backend/app/cuda_dependencies.py backend/tests/test_install_tasks.py backend/tests/test_runtime_status.py backend/tests/test_model_downloads.py
git commit -m "feat: use configured runtime dependency paths"
```

---

### Task 3: Frontend Advanced Runtime Path Settings

**Files:**
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/styles.css`

- [ ] **Step 1: Add frontend runtime path types and state**

Modify type definitions near the top of `frontend/src/App.tsx`:

```ts
type RuntimePathSource = "environment" | "settings" | "default" | "missing";
type PythonPackageInstallMode = "default" | "user";
```

Add these fields to `RuntimeState["faster_whisper"]`:

```ts
    external_python_source: RuntimePathSource;
    external_python_error: string;
    python_package_install_mode: PythonPackageInstallMode;
```

Add this field to `RuntimeState["local_models"]`:

```ts
    root_source: RuntimePathSource;
```

Add these fields to `UserSettings`:

```ts
  external_python_path: string;
  faster_whisper_model_dir: string;
  python_package_install_mode: PythonPackageInstallMode;
```

Add state in `App()` after local whisper runtime state:

```ts
  const [externalPythonPath, setExternalPythonPath] = useState("");
  const [fasterWhisperModelDir, setFasterWhisperModelDir] = useState("");
  const [pythonPackageInstallMode, setPythonPackageInstallMode] = useState<PythonPackageInstallMode>("default");
```

- [ ] **Step 2: Wire settings collection and application**

In `collectSettings()`, add:

```ts
      external_python_path: externalPythonPath,
      faster_whisper_model_dir: fasterWhisperModelDir,
      python_package_install_mode: pythonPackageInstallMode,
```

In `applySettings(settings: UserSettings)`, add:

```ts
    setExternalPythonPath(settings.external_python_path ?? "");
    setFasterWhisperModelDir(settings.faster_whisper_model_dir ?? "");
    setPythonPackageInstallMode(settings.python_package_install_mode ?? "default");
```

In `handleSaveSettings()`, refresh runtime after applying settings:

```ts
      applySettings(payload);
      await refreshHealth();
      setSettingsMessage("设置已保存到本地配置文件。");
```

In `handleClearSettings()`, refresh runtime after applying defaults:

```ts
      applySettings(payload);
      await refreshHealth();
      setSettingsMessage("本地设置已清除。");
```

- [ ] **Step 3: Add source label helpers**

Add these helper functions near `formatVersionDetails()`:

```ts
function formatRuntimeSource(source?: RuntimePathSource): string {
  if (source === "environment") return "环境变量";
  if (source === "settings") return "本地设置";
  if (source === "default") return "默认检测";
  return "未找到";
}

function formatInstallMode(mode?: PythonPackageInstallMode): string {
  if (mode === "user") return "用户目录 (--user)";
  return "默认 pip 安装";
}
```

- [ ] **Step 4: Add advanced local path UI**

Insert this block inside the `isLocalTranscription` fragment after the device/compute `two-col` block and before the runtime help paragraph:

```tsx
                    <div className="advanced-path-box">
                      <div>
                        <strong>高级本地路径</strong>
                        <span>
                          环境变量优先于这里保存的值；留空时使用默认自动检测。
                        </span>
                      </div>
                      <label className="field">
                        <span className="field-label">外部 Python 路径</span>
                        <input
                          placeholder="例如 C:\\Users\\me\\AppData\\Local\\Programs\\Python\\Python310\\python.exe"
                          value={externalPythonPath}
                          onChange={(event) => setExternalPythonPath(event.target.value)}
                        />
                      </label>
                      <label className="field">
                        <span className="field-label">Faster Whisper 模型目录</span>
                        <input
                          placeholder="例如 D:\\models\\faster-whisper"
                          value={fasterWhisperModelDir}
                          onChange={(event) => setFasterWhisperModelDir(event.target.value)}
                        />
                      </label>
                      <label className="field">
                        <span className="field-label">pip 安装模式</span>
                        <select
                          value={pythonPackageInstallMode}
                          onChange={(event) => setPythonPackageInstallMode(event.target.value as PythonPackageInstallMode)}
                        >
                          <option value="default">默认 pip 安装</option>
                          <option value="user">用户目录 (--user)</option>
                        </select>
                      </label>
                      {health?.runtime && (
                        <p className="field-help">
                          当前 Python：{health.runtime.faster_whisper.external_python_path || "未找到"} · 来源：
                          {formatRuntimeSource(health.runtime.faster_whisper.external_python_source)} · pip：
                          {formatInstallMode(health.runtime.faster_whisper.python_package_install_mode)}
                        </p>
                      )}
                      {health?.runtime?.faster_whisper.external_python_error && (
                        <p className="inline-warning">
                          <AlertTriangle size={15} />
                          {health.runtime.faster_whisper.external_python_error}
                        </p>
                      )}
                      {health?.runtime && (
                        <p className="field-help">
                          当前模型目录：{health.runtime.local_models.root} · 来源：
                          {formatRuntimeSource(health.runtime.local_models.root_source)}
                        </p>
                      )}
                    </div>
```

- [ ] **Step 5: Update install button disabled state for invalid configured Python**

Replace the local dependency install button `disabled` prop with:

```tsx
                          disabled={
                            Boolean(health?.runtime?.faster_whisper.external_python_error) ||
                            localDependencyInstall?.status === "pending" ||
                            localDependencyInstall?.status === "running"
                          }
```

Replace the CUDA dependency install button `disabled` prop with:

```tsx
                          disabled={
                            Boolean(health?.runtime?.faster_whisper.external_python_error) ||
                            cudaInstall?.status === "pending" ||
                            cudaInstall?.status === "running"
                          }
```

- [ ] **Step 6: Update runtime status detail text**

In `RuntimeStatusCard`, replace `pythonDetail` and `modelDetail` with:

```ts
  const pythonSource = formatRuntimeSource(runtime.faster_whisper.external_python_source);
  const modelSource = formatRuntimeSource(runtime.local_models.root_source);
  const pythonDetail = runtime.faster_whisper.external_python_error
    ? runtime.faster_whisper.external_python_error
    : !runtime.faster_whisper.python_available
      ? "未检测到外部 Python 3.10+，本地转写无法启用"
      : runtime.faster_whisper.worker_ready
        ? `${runtime.faster_whisper.external_python_path ?? "外部 Python"} · ${pythonSource} · ${formatInstallMode(runtime.faster_whisper.python_package_install_mode)}`
        : `${runtime.faster_whisper.worker_error || runtime.faster_whisper.install_hint} · ${pythonSource}`;
  const modelDetail = runtime.faster_whisper.model_available
    ? `${runtime.local_models.models.join(", ")} · ${runtime.local_models.root} · ${modelSource}`
    : `未发现已缓存模型 · ${runtime.local_models.root} · ${modelSource}`;
```

Update `fasterWhisperDetail` worker-ready branch to include the source:

```ts
        ? `外部 Python worker：${runtime.faster_whisper.external_python_path ?? "已发现"} · ${formatRuntimeSource(runtime.faster_whisper.external_python_source)}`
```

- [ ] **Step 7: Add CSS for advanced path box**

Add this block to `frontend/src/styles.css` near `.model-download-box`:

```css
.advanced-path-box {
  background: #f8faf9;
  border: 1px solid var(--line);
  border-radius: 8px;
  display: grid;
  gap: 10px;
  margin-top: 12px;
  padding: 11px;
}

.advanced-path-box > div:first-child {
  display: grid;
  gap: 4px;
}

.advanced-path-box strong {
  color: #263335;
  font-size: 13px;
}

.advanced-path-box span {
  color: var(--muted);
  font-size: 12px;
  line-height: 1.45;
}

.advanced-path-box .field {
  margin-top: 0;
}
```

- [ ] **Step 8: Run frontend build**

Run:

```powershell
npm --prefix frontend run build
```

Expected: TypeScript and Vite build pass.

- [ ] **Step 9: Commit frontend settings UI**

Run:

```powershell
git add frontend/src/App.tsx frontend/src/styles.css
git commit -m "feat: configure local runtime paths in settings"
```

---

### Task 4: Full Verification

**Files:**
- No source changes unless verification reveals a failure.

- [ ] **Step 1: Run focused backend tests**

Run:

```powershell
python -m pytest backend/tests/test_settings.py backend/tests/test_runtime_config.py backend/tests/test_install_tasks.py backend/tests/test_runtime_status.py backend/tests/test_model_downloads.py backend/tests/test_transcription.py -q
```

Expected: pass.

- [ ] **Step 2: Run full backend suite**

Run:

```powershell
python -m pytest backend/tests -q
```

Expected: pass.

- [ ] **Step 3: Run frontend build**

Run:

```powershell
npm --prefix frontend run build
```

Expected: pass.

- [ ] **Step 4: Inspect diff scope**

Run:

```powershell
git diff --stat HEAD~3..HEAD
```

Expected: changes are limited to runtime config, settings, runtime status/install/model path tests, and the settings modal UI.

- [ ] **Step 5: Report outcome**

Report:

- Which runtime path fields were added.
- Which backend modules now share the same path resolution.
- Which tests/build commands passed.
- Whether any verification could not be run locally because dependencies were missing.
