from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_runtime_background_tasks_are_owned_by_a_focused_hook() -> None:
    app_source = (ROOT / "frontend" / "src" / "App.tsx").read_text(encoding="utf-8")
    hook_source = (ROOT / "frontend" / "src" / "useRuntimeTasks.ts").read_text(encoding="utf-8")
    api_source = (ROOT / "frontend" / "src" / "api.ts").read_text(encoding="utf-8")

    assert 'from "./useRuntimeTasks"' in app_source
    assert "useRuntimeTasks({" in app_source

    for endpoint in (
        "/api/models/faster-whisper/download",
        "/api/runtime/local-dependencies/install",
        "/api/runtime/cuda-dependencies/install",
    ):
        assert endpoint not in app_source
        assert endpoint in api_source

    for local_state_setter in (
        "setModelDownload",
        "setModelDownloadError",
        "setLocalDependencyInstall",
        "setLocalDependencyInstallError",
        "setCudaInstall",
        "setCudaInstallError",
    ):
        assert local_state_setter not in app_source

    assert "usePolledRuntimeTask<ModelDownloadState>" in hook_source
    assert "usePolledRuntimeTask<LocalDependencyInstallState>" in hook_source
    assert "usePolledRuntimeTask<CudaDependencyInstallState>" in hook_source
    assert "window.setTimeout(() => void pollTask(), intervalMs)" in hook_source
    assert "window.setInterval" not in hook_source
    assert "window.clearTimeout(timer)" in hook_source
    assert "mountedRef.current" in hook_source
    assert "requestEpochRef.current" in hook_source
    assert 'status: "failed"' in hook_source
    assert 'nextTask.status === "succeeded"' in hook_source
    assert "await onSucceededRef.current();" in hook_source


def test_runtime_api_helpers_keep_generated_response_types_and_chinese_errors() -> None:
    api_source = (ROOT / "frontend" / "src" / "api.ts").read_text(encoding="utf-8")

    for helper in (
        "export async function fetchHealthState",
        "export async function startModelDownload",
        "export async function fetchModelDownload",
        "export async function startLocalDependencyInstall",
        "export async function fetchLocalDependencyInstall",
        "export async function startCudaDependencyInstall",
        "export async function fetchCudaDependencyInstall",
    ):
        assert helper in api_source

    for response_type in (
        "Promise<HealthState>",
        "Promise<ModelDownloadState>",
        "Promise<LocalDependencyInstallState>",
        "Promise<CudaDependencyInstallState>",
    ):
        assert response_type in api_source

    for message in (
        "运行环境状态读取失败。",
        "模型下载启动失败。",
        "模型下载状态读取失败。",
        "本地转写依赖安装启动失败。",
        "本地转写依赖安装状态读取失败。",
        "CUDA 依赖安装启动失败。",
        "CUDA 依赖安装状态读取失败。",
    ):
        assert message in api_source
