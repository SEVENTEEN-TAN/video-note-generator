import { AlertTriangle, CheckCircle2, Server } from "lucide-react";

import { formatInstallMode, formatRuntimeSource } from "./format";
import type {
  HealthState,
  LocalWhisperDevice,
  RuntimeState,
  TranscriptionMode
} from "./types";

export function RuntimeStatusCard({ runtime }: { runtime: RuntimeState | null }) {
  if (!runtime) {
    return (
      <section className="runtime-card">
        <div className="runtime-item muted">
          <Server size={16} />
          <div>
            <strong>运行环境</strong>
            <span>等待后端状态</span>
          </div>
        </div>
      </section>
    );
  }

  const fasterWhisperDetail = runtime.faster_whisper.internal_available
    ? "内置 Faster Whisper 可用"
    : !runtime.faster_whisper.python_available
      ? runtime.faster_whisper.install_hint
      : runtime.faster_whisper.worker_ready
        ? `外部 Python worker：${runtime.faster_whisper.external_python_path ?? "已发现"} · ${formatRuntimeSource(runtime.faster_whisper.external_python_source)}`
        : runtime.faster_whisper.worker_probe_error ||
          runtime.faster_whisper.worker_error ||
          runtime.faster_whisper.install_hint;
  const cudaDetail = runtime.faster_whisper.cuda_available
    ? `CTranslate2 检测到 ${runtime.faster_whisper.cuda_device_count ?? 0} 个 CUDA 设备 · ${runtime.faster_whisper.cuda_source ?? "runtime"}`
    : runtime.faster_whisper.cuda_error
      ? `检测到 ${runtime.faster_whisper.cuda_device_count ?? 0} 个 CUDA 设备，但 CUDA 推理运行库不可用：${runtime.faster_whisper.cuda_error}`
      : runtime.faster_whisper.cuda_runtime_hint || "未检测到 CUDA 设备；CPU 模式仍可使用";
  const pythonSource = formatRuntimeSource(runtime.faster_whisper.external_python_source);
  const modelSource = formatRuntimeSource(runtime.local_models.root_source);
  const pythonDetail = runtime.faster_whisper.external_python_error
    ? runtime.faster_whisper.external_python_error
    : !runtime.faster_whisper.python_available
      ? "未检测到外部 Python 3.10+，本地转写无法启用"
      : runtime.faster_whisper.worker_ready
        ? `${runtime.faster_whisper.external_python_path ?? "外部 Python"} · ${pythonSource} · ${formatInstallMode(runtime.faster_whisper.python_package_install_mode)}`
        : `${runtime.faster_whisper.worker_probe_error ||
            runtime.faster_whisper.worker_error ||
            runtime.faster_whisper.install_hint} · ${pythonSource}`;
  const modelDetail = runtime.faster_whisper.model_available
    ? `${runtime.local_models.models.join(", ")} · ${runtime.local_models.root} · ${modelSource}`
    : `未发现已缓存模型 · ${runtime.local_models.root} · ${modelSource}`;

  return (
    <section className="runtime-card" aria-label="运行环境检测">
      <RuntimeItem
        ok={runtime.ffmpeg.available}
        title="FFmpeg"
        detail={runtime.ffmpeg.available ? runtime.ffmpeg.path || "可用" : runtime.ffmpeg.install_hint}
      />
      <RuntimeItem
        ok={runtime.capabilities.audio_transcriptions.available}
        soft
        title="远端转写流程"
        detail={runtime.capabilities.audio_transcriptions.reason}
      />
      <RuntimeItem ok={runtime.faster_whisper.available} title="本地转写引擎" detail={fasterWhisperDetail} />
      <RuntimeItem
        ok={runtime.faster_whisper.python_available && runtime.faster_whisper.worker_ready}
        title="外部 Python 环境"
        detail={pythonDetail}
      />
      <RuntimeItem ok={runtime.faster_whisper.cuda_available} soft title="CUDA 加速" detail={cudaDetail} />
      <RuntimeItem
        ok={runtime.faster_whisper.model_available}
        soft
        title="本地模型目录"
        detail={modelDetail}
      />
      <RuntimeItem soft ok title="配置文件" detail={runtime.settings.path} />
    </section>
  );
}

export function HealthBadge({
  hasUploadedSubtitle,
  health,
  localWhisperDevice,
  transcriptionMode
}: {
  hasUploadedSubtitle: boolean;
  health: HealthState | null;
  localWhisperDevice: LocalWhisperDevice;
  transcriptionMode: TranscriptionMode;
}) {
  if (!health) {
    return <span className="badge muted">后端未连接</span>;
  }
  if (health.runtime) {
    const capability = hasUploadedSubtitle
      ? health.runtime.capabilities.uploaded_subtitle
      : transcriptionMode === "local_faster_whisper"
        ? localWhisperDevice === "cuda"
          ? health.runtime.capabilities.local_transcription_cuda
          : health.runtime.capabilities.local_transcription_cpu
        : health.runtime.capabilities[transcriptionMode];
    return (
      <span className={capability.available ? "badge ok" : "badge warn"} title={capability.reason}>
        {capability.available ? "当前流程可用" : "当前流程缺依赖"}
      </span>
    );
  }
  return (
    <span className={health.ffmpeg_available ? "badge ok" : "badge warn"} title={health.ffmpeg_path ?? undefined}>
      {health.ffmpeg_available ? "FFmpeg 可用" : "缺少 FFmpeg"}
    </span>
  );
}

function RuntimeItem({
  detail,
  ok,
  soft,
  title
}: {
  detail: string;
  ok: boolean;
  soft?: boolean;
  title: string;
}) {
  return (
    <div className={`runtime-item ${ok ? "ok" : soft ? "soft" : "warn"}`} title={detail}>
      {ok ? <CheckCircle2 size={16} /> : <AlertTriangle size={16} />}
      <div>
        <strong>{title}</strong>
        <span>{detail}</span>
      </div>
    </div>
  );
}
