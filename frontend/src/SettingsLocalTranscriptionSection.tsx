import { AlertTriangle, Download, Loader2, RefreshCw } from "lucide-react";

import { formatInstallMode, formatRuntimeSource } from "./format";
import type {
  CudaDependencyInstallState,
  HealthState,
  LocalDependencyInstallState,
  LocalWhisperComputeType,
  LocalWhisperDevice,
  ModelDownloadState,
  PerformanceMode,
  PythonPackageInstallMode
} from "./types";

export type SettingsLocalTranscriptionSectionProps = {
  cudaInstall: CudaDependencyInstallState | null;
  cudaInstallError: string;
  externalPythonPath: string;
  fasterWhisperModelDir: string;
  health: HealthState | null;
  localDependencyInstall: LocalDependencyInstallState | null;
  localDependencyInstallError: string;
  localWhisperComputeType: LocalWhisperComputeType;
  localWhisperDevice: LocalWhisperDevice;
  modelDownload: ModelDownloadState | null;
  modelDownloadError: string;
  onDownloadLocalModel: () => void;
  onExternalPythonPathChange: (value: string) => void;
  onFasterWhisperModelDirChange: (value: string) => void;
  onInstallCudaDependencies: () => void;
  onInstallLocalDependencies: () => void;
  onLocalWhisperComputeTypeChange: (value: LocalWhisperComputeType) => void;
  onLocalWhisperDeviceChange: (value: LocalWhisperDevice) => void;
  onPerformanceModeChange: (value: PerformanceMode) => void;
  onPythonPackageInstallModeChange: (value: PythonPackageInstallMode) => void;
  onRefreshHealth: () => void;
  onTranscriptionModelChange: (value: string) => void;
  performanceMode: PerformanceMode;
  pythonPackageInstallMode: PythonPackageInstallMode;
  transcriptionModel: string;
};

export function SettingsLocalTranscriptionSection({
  cudaInstall,
  cudaInstallError,
  externalPythonPath,
  fasterWhisperModelDir,
  health,
  localDependencyInstall,
  localDependencyInstallError,
  localWhisperComputeType,
  localWhisperDevice,
  modelDownload,
  modelDownloadError,
  onDownloadLocalModel,
  onExternalPythonPathChange,
  onFasterWhisperModelDirChange,
  onInstallCudaDependencies,
  onInstallLocalDependencies,
  onLocalWhisperComputeTypeChange,
  onLocalWhisperDeviceChange,
  onPerformanceModeChange,
  onPythonPackageInstallModeChange,
  onRefreshHealth,
  onTranscriptionModelChange,
  performanceMode,
  pythonPackageInstallMode,
  transcriptionModel
}: SettingsLocalTranscriptionSectionProps) {
  const runtimeLocalStatus = health?.runtime?.faster_whisper;
  const runtimeProbeFailed = Boolean(runtimeLocalStatus?.worker_error_code);
  const needsLocalDependencyInstall =
    Boolean(runtimeLocalStatus) &&
    !runtimeLocalStatus?.internal_available &&
    !runtimeLocalStatus?.worker_ready &&
    !runtimeProbeFailed;
  const selectedLocalModelAvailable =
    !health?.runtime || health.runtime.local_models.models.includes(transcriptionModel);
  const canOfferCudaInstall =
    Boolean(runtimeLocalStatus?.cuda_device_count) &&
    !runtimeLocalStatus?.cuda_available &&
    !!runtimeLocalStatus?.worker_ready;

  function handleLocalWhisperDeviceChange(nextDevice: LocalWhisperDevice) {
    onLocalWhisperDeviceChange(nextDevice);
    if (nextDevice === "cuda" && localWhisperComputeType === "int8") {
      onLocalWhisperComputeTypeChange("float16");
    }
    if (nextDevice === "cpu" && localWhisperComputeType === "float16") {
      onLocalWhisperComputeTypeChange("int8");
    }
  }

  return (
              <>
                <label className="field">
                  <span className="field-label">性能档位</span>
                  <select value={performanceMode} onChange={(event) => onPerformanceModeChange(event.target.value as PerformanceMode)}>
                    <option value="fast">快速（更低延迟）</option>
                    <option value="balanced">均衡（默认）</option>
                    <option value="accurate">准确（更高质量）</option>
                  </select>
                  <span className="field-help">自动调整解码强度；长视频会分块并保存断点。</span>
                </label>
                <label className="field">
                  <span className="field-label">本地模型</span>
                  <select value={transcriptionModel} onChange={(event) => onTranscriptionModelChange(event.target.value)}>
                    <option value="small">small（默认，速度/准确率均衡）</option>
                    <option value="medium">medium（更准，更慢）</option>
                    <option value="large-v3">large-v3（质量优先）</option>
                    <option value="base">base（更快，准确率较低）</option>
                  </select>
                </label>
                <div className="two-col">
                  <label className="field">
                    <span className="field-label">运行设备</span>
                    <select value={localWhisperDevice} onChange={(event) => handleLocalWhisperDeviceChange(event.target.value as LocalWhisperDevice)}>
                      <option value="cpu">CPU（兼容优先）</option>
                      <option value="cuda">CUDA GPU（NVIDIA）</option>
                      <option value="auto">Auto（由 CTranslate2 判断）</option>
                    </select>
                  </label>

                  <label className="field">
                    <span className="field-label">计算精度</span>
                    <select
                      value={localWhisperComputeType}
                      onChange={(event) => onLocalWhisperComputeTypeChange(event.target.value as LocalWhisperComputeType)}
                    >
                      <option value="int8">int8（CPU 推荐）</option>
                      <option value="float16">float16（CUDA 推荐）</option>
                      <option value="int8_float16">int8_float16（CUDA 省显存）</option>
                      <option value="float32">float32（兼容调试）</option>
                      <option value="default">default（库默认）</option>
                    </select>
                  </label>
                </div>
                <div className="advanced-path-box">
                  <div>
                    <strong>高级本地路径</strong>
                    <span>环境变量优先于这里保存的值；留空时使用默认自动检测。</span>
                  </div>
                  <label className="field">
                    <span className="field-label">外部 Python 路径</span>
                    <input
                      placeholder="例如 C:\\Users\\me\\AppData\\Local\\Programs\\Python\\Python310\\python.exe"
                      value={externalPythonPath}
                      onChange={(event) => onExternalPythonPathChange(event.target.value)}
                    />
                  </label>
                  <label className="field">
                    <span className="field-label">Faster Whisper 模型目录</span>
                    <input
                      placeholder="例如 D:\\models\\faster-whisper"
                      value={fasterWhisperModelDir}
                      onChange={(event) => onFasterWhisperModelDirChange(event.target.value)}
                    />
                  </label>
                  <label className="field">
                    <span className="field-label">pip 安装模式</span>
                    <select
                      value={pythonPackageInstallMode}
                      onChange={(event) => onPythonPackageInstallModeChange(event.target.value as PythonPackageInstallMode)}
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
                <p className={localWhisperDevice === "cuda" && !health?.runtime?.faster_whisper.cuda_available ? "inline-warning" : "field-help"}>
                  {localWhisperDevice === "cuda"
                    ? health?.runtime?.faster_whisper.ready_for_cuda
                      ? `检测到 ${health.runtime.faster_whisper.cuda_device_count ?? 0} 个 CUDA 设备；当前可直接使用 CUDA + ${localWhisperComputeType}。`
                      : health?.runtime?.faster_whisper.cuda_error
                        ? `CUDA 不可用：${health.runtime.faster_whisper.cuda_error}`
                        : "当前后端未检测到可用 CUDA 推理环境；可先切换到 CPU 模式继续使用本地转写。"
                    : health?.runtime?.faster_whisper.ready_for_cpu
                      ? "当前本地转写 CPU 环境已就绪，可直接使用。"
                      : health?.runtime?.faster_whisper.install_hint || "当前本地转写依赖未就绪，请先补齐外部 Python 环境。"}
                </p>
                {needsLocalDependencyInstall && (
                  <div className="model-download-box">
                    <p className="inline-warning">
                      <AlertTriangle size={15} />
                      {health?.runtime?.faster_whisper.install_hint || "外部 Python 缺少本地转写依赖。"}
                    </p>
                    <button
                      className="small-button strong"
                      disabled={
                        Boolean(health?.runtime?.faster_whisper.external_python_error) ||
                        localDependencyInstall?.status === "pending" ||
                        localDependencyInstall?.status === "running"
                      }
                      onClick={onInstallLocalDependencies}
                      type="button"
                    >
                      {localDependencyInstall?.status === "pending" || localDependencyInstall?.status === "running" ? (
                        <Loader2 className="spin" size={15} />
                      ) : (
                        <Download size={15} />
                      )}
                      安装本地转写依赖
                    </button>
                    {localDependencyInstall && (
                      <p className="settings-message">
                        {localDependencyInstall.status === "pending" && "准备安装本地转写依赖..."}
                        {localDependencyInstall.status === "running" && `正在安装到 ${localDependencyInstall.python_path || "外部 Python"}，请保持网络连接...`}
                        {localDependencyInstall.status === "succeeded" && "本地转写依赖安装完成，正在刷新检测结果。"}
                        {localDependencyInstall.status === "failed" && `安装失败：${localDependencyInstall.error || localDependencyInstallError}`}
                      </p>
                    )}
                    {localDependencyInstallError && <p className="inline-error">{localDependencyInstallError}</p>}
                  </div>
                )}
                {runtimeProbeFailed && !runtimeLocalStatus?.internal_available && (
                  <div className="model-download-box">
                    <p className="inline-warning">
                      <AlertTriangle size={15} />
                      运行环境检测失败：{runtimeLocalStatus?.worker_probe_error || "外部转写进程无法验证。"}
                    </p>
                    <button className="small-button" onClick={onRefreshHealth} type="button">
                      <RefreshCw size={15} />
                      重新检测
                    </button>
                  </div>
                )}
                {canOfferCudaInstall && (
                  <div className="model-download-box">
                    <p className="inline-warning">
                      <AlertTriangle size={15} />
                      检测到 CUDA 设备，但缺少 cuBLAS/cuDNN 推理运行库。
                    </p>
                    <button
                      className="small-button strong"
                      disabled={
                        Boolean(health?.runtime?.faster_whisper.external_python_error) ||
                        cudaInstall?.status === "pending" ||
                        cudaInstall?.status === "running"
                      }
                      onClick={onInstallCudaDependencies}
                      type="button"
                    >
                      {cudaInstall?.status === "pending" || cudaInstall?.status === "running" ? (
                        <Loader2 className="spin" size={15} />
                      ) : (
                        <Download size={15} />
                      )}
                      安装 CUDA 加速依赖
                    </button>
                    {cudaInstall && (
                      <p className="settings-message">
                        {cudaInstall.status === "pending" && "准备安装 CUDA 依赖..."}
                        {cudaInstall.status === "running" && `正在安装到 ${cudaInstall.python_path || "外部 Python"}，请保持网络连接...`}
                        {cudaInstall.status === "succeeded" && "CUDA 依赖安装完成，正在刷新检测结果。"}
                        {cudaInstall.status === "failed" && `安装失败：${cudaInstall.error || cudaInstallError}`}
                      </p>
                    )}
                    {cudaInstallError && <p className="inline-error">{cudaInstallError}</p>}
                  </div>
                )}
                {!selectedLocalModelAvailable && (
                  <div className="model-download-box">
                    <p className="inline-warning">
                      <AlertTriangle size={15} />
                      当前模型目录未发现 {transcriptionModel}：{health?.runtime?.local_models.root}
                    </p>
                    <button
                      className="small-button strong"
                      disabled={modelDownload?.status === "pending" || modelDownload?.status === "running"}
                      onClick={onDownloadLocalModel}
                      type="button"
                    >
                      {modelDownload?.status === "pending" || modelDownload?.status === "running" ? (
                        <Loader2 className="spin" size={15} />
                      ) : (
                        <Download size={15} />
                      )}
                      下载 {transcriptionModel}
                    </button>
                    {modelDownload && modelDownload.model_name === transcriptionModel && (
                      <p className="settings-message">
                        {modelDownload.status === "pending" && "准备下载模型..."}
                        {modelDownload.status === "running" && "正在下载模型，完成前请保持网络连接..."}
                        {modelDownload.status === "succeeded" && "模型已下载完成，可以开始生成。"}
                        {modelDownload.status === "failed" && `下载失败：${modelDownload.error || modelDownloadError}`}
                      </p>
                    )}
                    {modelDownloadError && <p className="inline-error">{modelDownloadError}</p>}
                  </div>
                )}
              </>
  );
}
