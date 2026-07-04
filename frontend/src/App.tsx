import {
  AlertTriangle,
  Captions,
  CheckCircle2,
  Download,
  FileText,
  FolderOpen,
  History,
  Image,
  KeyRound,
  Loader2,
  Play,
  RefreshCw,
  Server,
  Settings,
  Trash2,
  X,
  Upload
} from "lucide-react";
import { FormEvent, useEffect, useMemo, useRef, useState } from "react";
import type { ChangeEvent, Dispatch, SetStateAction } from "react";

type NoteLanguage = "zh" | "en" | "follow";
type NoteStyle = "minimal" | "detailed" | "tutorial" | "academic" | "task_oriented" | "meeting_minutes";
type TranscriptionMode = "audio_transcriptions" | "chat_audio" | "local_faster_whisper";
type LocalWhisperDevice = "auto" | "cpu" | "cuda";
type LocalWhisperComputeType = "default" | "int8" | "int8_float16" | "float16" | "float32";
type RuntimePathSource = "environment" | "settings" | "default" | "missing";
type PythonPackageInstallMode = "default" | "user";
type JobStatus = "pending" | "running" | "succeeded" | "failed";

type Artifact = {
  label: string;
  path: string;
  kind: "audio" | "subtitle" | "markdown" | "image" | "json" | "zip" | "log";
  asset_url: string;
};

type JobState = {
  job_id: string;
  status: JobStatus;
  step: string;
  progress: number;
  error?: string | null;
  artifacts: Artifact[];
  step_started_at?: string | null;
  updated_at?: string | null;
  stage_elapsed_seconds?: number;
};

type JobSummary = {
  job_id: string;
  title: string;
  original_filename: string;
  created_at?: string | null;
  status: JobStatus;
  duration_seconds?: number | null;
  artifact_count: number;
  note_version_count: number;
  active_version_id?: string | null;
};

type NoteVersion = {
  id: string;
  label: string;
  created_at: string;
  note_style: NoteStyle;
  note_language: string;
  note_model: string;
  note_base_url: string;
  frame_limit: number;
  note_path: string;
  frame_dir: string;
  selected: boolean;
  active: boolean;
  extras_present: boolean;
  extras_length: number;
};

type NoteVersionIndex = {
  active_version_id?: string | null;
  selected_version_ids: string[];
  versions: NoteVersion[];
};

type TranscriptCorrectionSegment = {
  index: number;
  start: number;
  end: number;
  original_text: string;
  corrected_text: string;
  changed: boolean;
};

type TranscriptCorrectionPreview = {
  job_id: string;
  changed_count: number;
  segments: TranscriptCorrectionSegment[];
};

type HealthState = {
  ok: boolean;
  runtime_ok?: boolean;
  ffmpeg_available: boolean;
  ffmpeg_path?: string | null;
  runtime?: RuntimeState;
};

type RuntimeState = {
  ok: boolean;
  ffmpeg: {
    available: boolean;
    path?: string | null;
    install_hint: string;
  };
  faster_whisper: {
    available: boolean;
    internal_available: boolean;
    internal_import_error: string;
    python_available: boolean;
    external_python_path?: string | null;
    external_python_source: RuntimePathSource;
    external_python_error: string;
    python_package_install_mode: PythonPackageInstallMode;
    external_worker_path: string;
    external_worker_available: boolean;
    worker_ready: boolean;
    worker_error: string;
    ctranslate2_available: boolean;
    ctranslate2_version: string;
    cuda_available: boolean;
    cuda_device_count?: number | null;
    cuda_runtime_available?: boolean;
    cuda_error?: string;
    cuda_source?: string;
    cuda_runtime_hint?: string;
    cuda_dll_dirs: string[];
    import_error: string;
    install_hint: string;
    model_available: boolean;
    ready_for_cpu: boolean;
    ready_for_cuda: boolean;
  };
  local_models: {
    root: string;
    root_source: RuntimePathSource;
    models: string[];
    hint: string;
  };
  settings: {
    path: string;
    warning: string;
  };
};

type UserSettings = {
  transcription_mode: TranscriptionMode;
  transcription_api_key: string;
  transcription_base_url: string;
  transcription_model: string;
  local_whisper_device: LocalWhisperDevice;
  local_whisper_compute_type: LocalWhisperComputeType;
  external_python_path: string;
  faster_whisper_model_dir: string;
  python_package_install_mode: PythonPackageInstallMode;
  note_api_key: string;
  note_base_url: string;
  note_model: string;
  note_language: NoteLanguage;
  note_style: NoteStyle;
  extras: string;
  frame_limit: number;
};

type LocalDependencyInstallState = {
  status: "idle" | "pending" | "running" | "succeeded" | "failed";
  progress: number;
  error: string;
  python_path: string;
};

type PollableTaskState = {
  status: "idle" | "pending" | "running" | "succeeded" | "failed";
};

type ModelDownloadState = {
  model_name: string;
  status: "idle" | "pending" | "running" | "succeeded" | "failed";
  progress: number;
  error: string;
  model_root: string;
};

type CudaDependencyInstallState = {
  status: "idle" | "pending" | "running" | "succeeded" | "failed";
  progress: number;
  error: string;
  python_path: string;
};

type MarkdownBlock =
  | { type: "heading"; level: number; text: string }
  | { type: "list"; ordered: boolean; items: string[] }
  | { type: "paragraph"; text: string }
  | { type: "image"; alt: string; src: string };

type PreviewImage = {
  label: string;
  path: string;
  asset_url: string;
};

declare global {
  interface Window {
    pywebview?: {
      api?: {
        save_file?: (suggestedName: string, sourceUrl: string) => Promise<{ ok: boolean; path?: string; reason?: string }>;
      };
    };
  }
}

const OPENAI_BASE_URL = "https://api.openai.com/v1";
const QWEN_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1";

const statusText: Record<JobStatus, string> = {
  pending: "等待",
  running: "处理中",
  succeeded: "完成",
  failed: "失败"
};

const noteStyleOptions: Array<{ value: NoteStyle; label: string }> = [
  { value: "minimal", label: "minimal（极简）" },
  { value: "detailed", label: "detailed（详细）" },
  { value: "tutorial", label: "tutorial（教程）" },
  { value: "academic", label: "academic（学术）" },
  { value: "task_oriented", label: "task_oriented（任务导向）" },
  { value: "meeting_minutes", label: "meeting_minutes（会议纪要）" }
];

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

function formatSecondsRange(start: number, end: number): string {
  const format = (value: number) => {
    const totalSeconds = Math.max(0, Math.floor(value));
    const hours = Math.floor(totalSeconds / 3600);
    const minutes = Math.floor((totalSeconds % 3600) / 60);
    const seconds = totalSeconds % 60;
    return [hours, minutes, seconds].map((part) => String(part).padStart(2, "0")).join(":");
  };
  return `${format(start)} - ${format(end)}`;
}

function formatUpdateTime(value?: string | null): string {
  if (!value) {
    return "暂无";
  }

  return new Date(value).toLocaleTimeString();
}

function formatHistoryTime(value?: string | null): string {
  if (!value) {
    return "未知时间";
  }
  return new Date(value).toLocaleString();
}

function formatVersionOption(version: NoteVersion): string {
  return version.id;
}

function formatVersionDetails(version: NoteVersion): string {
  const createdAt = formatHistoryTime(version.created_at);
  const style = noteStyleOptions.find((option) => option.value === version.note_style)?.label ?? version.note_style;
  return `${style} · ${createdAt} · ${version.note_model}`;
}

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

export function App() {
  const [transcriptionApiKey, setTranscriptionApiKey] = useState("");
  const [transcriptionMode, setTranscriptionMode] = useState<TranscriptionMode>("local_faster_whisper");
  const [transcriptionBaseUrl, setTranscriptionBaseUrl] = useState(OPENAI_BASE_URL);
  const [transcriptionModel, setTranscriptionModel] = useState("small");
  const [localWhisperDevice, setLocalWhisperDevice] = useState<LocalWhisperDevice>("cpu");
  const [localWhisperComputeType, setLocalWhisperComputeType] = useState<LocalWhisperComputeType>("int8");
  const [externalPythonPath, setExternalPythonPath] = useState("");
  const [fasterWhisperModelDir, setFasterWhisperModelDir] = useState("");
  const [pythonPackageInstallMode, setPythonPackageInstallMode] = useState<PythonPackageInstallMode>("default");
  const [noteApiKey, setNoteApiKey] = useState("");
  const [noteBaseUrl, setNoteBaseUrl] = useState(OPENAI_BASE_URL);
  const [noteModel, setNoteModel] = useState("gpt-5.5");
  const [noteLanguage, setNoteLanguage] = useState<NoteLanguage>("zh");
  const [noteStyle, setNoteStyle] = useState<NoteStyle>("detailed");
  const [extras, setExtras] = useState("");
  const [frameLimit, setFrameLimit] = useState(6);
  const [video, setVideo] = useState<File | null>(null);
  const [job, setJob] = useState<JobState | null>(null);
  const [notePreview, setNotePreview] = useState("");
  const [subtitlePreview, setSubtitlePreview] = useState("");
  const [health, setHealth] = useState<HealthState | null>(null);
  const [submitError, setSubmitError] = useState("");
  const [versionError, setVersionError] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [isRegenerating, setIsRegenerating] = useState(false);
  const [isSavingSettings, setIsSavingSettings] = useState(false);
  const [settingsMessage, setSettingsMessage] = useState("");
  const [modelDownload, setModelDownload] = useState<ModelDownloadState | null>(null);
  const [modelDownloadError, setModelDownloadError] = useState("");
  const [localDependencyInstall, setLocalDependencyInstall] = useState<LocalDependencyInstallState | null>(null);
  const [localDependencyInstallError, setLocalDependencyInstallError] = useState("");
  const [cudaInstall, setCudaInstall] = useState<CudaDependencyInstallState | null>(null);
  const [cudaInstallError, setCudaInstallError] = useState("");
  const [noteVersions, setNoteVersions] = useState<NoteVersionIndex | null>(null);
  const [previewVersionId, setPreviewVersionId] = useState("");
  const [jobHistory, setJobHistory] = useState<JobSummary[]>([]);
  const [historyError, setHistoryError] = useState("");
  const [isHistoryLoading, setIsHistoryLoading] = useState(false);
  const [isDeletingJobId, setIsDeletingJobId] = useState("");
  const [isSettingsOpen, setIsSettingsOpen] = useState(false);
  const [downloadMessage, setDownloadMessage] = useState("");
  const [correctionPreview, setCorrectionPreview] = useState<TranscriptCorrectionPreview | null>(null);
  const [correctionError, setCorrectionError] = useState("");
  const [isCorrectingTranscript, setIsCorrectingTranscript] = useState(false);
  const [isApplyingCorrection, setIsApplyingCorrection] = useState(false);
  const videoInputRef = useRef<HTMLInputElement | null>(null);

  async function pollTaskState<T extends PollableTaskState>(
    url: string,
    setTask: Dispatch<SetStateAction<T | null>>,
    setError: (message: string) => void,
    errorMessage: string
  ): Promise<void> {
    try {
      const response = await fetch(url);
      const payload = (await response.json()) as T;
      if (!response.ok) {
        throw new Error((payload as { detail?: string }).detail || errorMessage);
      }
      setTask(payload);
      if (payload.status === "succeeded") {
        await refreshHealth();
      }
    } catch (error) {
      setError(error instanceof Error ? error.message : errorMessage);
    }
  }

  async function startTask<T extends PollableTaskState>({
    request,
    optimisticState,
    setTask,
    setError,
    errorMessage
  }: {
    request: () => Promise<Response>;
    optimisticState: T;
    setTask: Dispatch<SetStateAction<T | null>>;
    setError: (message: string) => void;
    errorMessage: string;
  }): Promise<void> {
    setTask(optimisticState);
    try {
      const response = await request();
      const payload = (await response.json()) as T;
      if (!response.ok) {
        throw new Error((payload as { detail?: string }).detail || errorMessage);
      }
      setTask(payload);
      if (payload.status === "succeeded") {
        await refreshHealth();
      }
    } catch (error) {
      const message = error instanceof Error ? error.message : errorMessage;
      setError(message);
      setTask((current) =>
        current
          ? {
              ...current,
              status: "failed",
              error: message
            }
          : null
      );
    }
  }

  const isTranscriptCorrectionActive = isCorrectingTranscript || isApplyingCorrection || Boolean(correctionPreview);
  const isBusy = job?.status === "pending" || job?.status === "running" || isSubmitting || isRegenerating || isTranscriptCorrectionActive;
  const isLocalTranscription = transcriptionMode === "local_faster_whisper";
  const runtimeLocalStatus = health?.runtime?.faster_whisper;
  const selectedLocalModelAvailable =
    !isLocalTranscription || !health?.runtime || health.runtime.local_models.models.includes(transcriptionModel);
  const localTranscriptionReady = !isLocalTranscription || !runtimeLocalStatus || runtimeLocalStatus.ready_for_cpu;
  const canOfferCudaInstall =
    isLocalTranscription &&
    Boolean(runtimeLocalStatus?.cuda_device_count) &&
    !runtimeLocalStatus?.cuda_available &&
    !!runtimeLocalStatus?.worker_ready;
  const images = useMemo(() => job?.artifacts.filter((artifact) => artifact.kind === "image") ?? [], [job]);
  const previewVersion = useMemo(
    () => noteVersions?.versions.find((version) => version.id === previewVersionId) ?? null,
    [noteVersions, previewVersionId]
  );
  const previewAssetBasePath = previewVersion ? `note_versions/${previewVersion.id}` : undefined;
  const previewImages = useMemo<PreviewImage[]>(() => {
    if (job && previewVersion) {
      return extractMarkdownImages(notePreview, job.job_id, previewAssetBasePath);
    }
    return images.map((artifact) => ({
      label: artifact.label,
      path: artifact.path,
      asset_url: artifact.asset_url
    }));
  }, [images, job, notePreview, previewAssetBasePath, previewVersion]);

  function resetTaskContext() {
    setJob(null);
    setNotePreview("");
    setSubtitlePreview("");
    setNoteVersions(null);
    setPreviewVersionId("");
    setVersionError("");
    setDownloadMessage("");
    setCorrectionPreview(null);
    setCorrectionError("");
    setIsCorrectingTranscript(false);
    setIsApplyingCorrection(false);
    setIsRegenerating(false);
  }

  function clearVideoInput() {
    if (videoInputRef.current) {
      videoInputRef.current.value = "";
    }
  }

  function hasTaskContext() {
    return Boolean(job || notePreview || subtitlePreview || noteVersions);
  }

  useEffect(() => {
    void refreshHealth();
    void refreshJobHistory();
  }, []);

  useEffect(() => {
    if (!modelDownload || (modelDownload.status !== "pending" && modelDownload.status !== "running")) {
      return;
    }
    const timer = window.setInterval(() => {
      void pollTaskState(
        `/api/models/faster-whisper/download/${encodeURIComponent(modelDownload.model_name)}`,
        setModelDownload,
        setModelDownloadError,
        "模型下载状态读取失败。"
      );
    }, 1400);
    return () => window.clearInterval(timer);
  }, [modelDownload]);

  useEffect(() => {
    if (!localDependencyInstall || (localDependencyInstall.status !== "pending" && localDependencyInstall.status !== "running")) {
      return;
    }
    const timer = window.setInterval(() => {
      void pollTaskState(
        "/api/runtime/local-dependencies/install",
        setLocalDependencyInstall,
        setLocalDependencyInstallError,
        "本地转写依赖安装状态读取失败。"
      );
    }, 1600);
    return () => window.clearInterval(timer);
  }, [localDependencyInstall]);

  useEffect(() => {
    if (!cudaInstall || (cudaInstall.status !== "pending" && cudaInstall.status !== "running")) {
      return;
    }
    const timer = window.setInterval(() => {
      void pollTaskState(
        "/api/runtime/cuda-dependencies/install",
        setCudaInstall,
        setCudaInstallError,
        "CUDA 依赖安装状态读取失败。"
      );
    }, 1800);
    return () => window.clearInterval(timer);
  }, [cudaInstall]);

  useEffect(() => {
    fetch("/api/settings")
      .then((response) => (response.ok ? response.json() : null))
      .then((settings: UserSettings | null) => {
        if (settings) {
          applySettings(settings);
        }
      })
      .catch(() => undefined);
  }, []);

  useEffect(() => {
    if (!job || (job.status !== "pending" && job.status !== "running")) {
      return;
    }
    let cancelled = false;
    const timer = window.setInterval(async () => {
      const nextJob = await fetchJob(job.job_id);
      if (!cancelled) {
        setJob((current) => (current?.job_id === job.job_id ? nextJob : current));
      }
    }, 1600);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [job]);

  useEffect(() => {
    if (!job) {
      setNoteVersions(null);
      setPreviewVersionId("");
      return;
    }
    if (job.status === "succeeded" || job.status === "failed") {
      setIsRegenerating(false);
    }
    if (!job.artifacts.some((artifact) => artifact.path === "note.md")) {
      setNoteVersions(null);
      setPreviewVersionId("");
      return;
    }

    let cancelled = false;
    fetchNoteVersions(job.job_id)
      .then((index) => {
        if (cancelled) {
          return;
        }
        setNoteVersions(index);
        setPreviewVersionId((current) => {
          if (current && index.versions.some((version) => version.id === current)) {
            return current;
          }
          return index.active_version_id ?? index.versions[0]?.id ?? "";
        });
      })
      .catch(() => {
        if (!cancelled) {
          setNoteVersions(null);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [job]);

  useEffect(() => {
    if (job?.status === "succeeded" || job?.status === "failed") {
      void refreshJobHistory();
    }
  }, [job?.job_id, job?.status]);

  useEffect(() => {
    if (!job || !job.artifacts.some((artifact) => artifact.path === "subtitles.md")) {
      setSubtitlePreview("");
      return;
    }
    let cancelled = false;
    fetch(`/api/jobs/${job.job_id}/preview/subtitles`)
      .then((response) => (response.ok ? response.text() : ""))
      .then((text) => {
        if (!cancelled) {
          setSubtitlePreview(text);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [job]);

  useEffect(() => {
    if (!job || !job.artifacts.some((artifact) => artifact.path === "note.md")) {
      setNotePreview("");
      return;
    }
    let cancelled = false;
    const url = previewVersionId
      ? `/api/jobs/${job.job_id}/preview/note/${encodeURIComponent(previewVersionId)}`
      : `/api/jobs/${job.job_id}/preview/note`;
    fetch(url)
      .then((response) => (response.ok ? response.text() : ""))
      .then((text) => {
        if (!cancelled) {
          setNotePreview(text);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [job, previewVersionId]);

  function handleVideoChange(event: ChangeEvent<HTMLInputElement>) {
    const selectedVideo = event.target.files?.[0] ?? null;
    if (!selectedVideo) {
      return;
    }

    if (
      hasTaskContext() &&
      !window.confirm("当前页面已有任务内容。选择新视频会清空当前页面并准备创建新任务，历史任务仍可在左侧重新载入。是否继续？")
    ) {
      event.currentTarget.value = "";
      return;
    }

    setSubmitError("");
    resetTaskContext();
    setVideo(selectedVideo);
    event.currentTarget.value = "";
  }

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    setSubmitError("");

    if (!video) {
      setSubmitError("请先选择视频文件。");
      return;
    }
    if (!isLocalTranscription && !transcriptionApiKey.trim()) {
      setSubmitError("请填写字幕转写 API Key。");
      return;
    }
    if (!noteApiKey.trim()) {
      setSubmitError("请填写笔记生成 API Key。");
      return;
    }
    if (!transcriptionModel.trim() || !noteModel.trim()) {
      setSubmitError("字幕转写模型和笔记生成模型都不能为空。");
      return;
    }
    if (!selectedLocalModelAvailable) {
      const shouldDownload = window.confirm(
        `当前模型目录未发现 ${transcriptionModel}。是否现在下载到 ${health?.runtime?.local_models.root ?? "本地模型目录"}？`
      );
      if (shouldDownload) {
        void handleDownloadLocalModel();
      } else {
        setSubmitError(`请先下载 ${transcriptionModel}，或切换远端字幕转写。`);
      }
      return;
    }
    if (!localTranscriptionReady) {
      setSubmitError(runtimeLocalStatus?.install_hint || runtimeLocalStatus?.worker_error || "本地转写环境未就绪，请先补齐依赖。");
      return;
    }

    resetTaskContext();

    const formData = new FormData();
    formData.append("video", video);
    formData.append("transcription_mode", transcriptionMode);
    formData.append("transcription_api_key", isLocalTranscription ? "" : transcriptionApiKey);
    formData.append("transcription_base_url", isLocalTranscription ? "" : transcriptionBaseUrl);
    formData.append("transcription_model", transcriptionModel);
    formData.append("local_whisper_device", isLocalTranscription ? localWhisperDevice : "");
    formData.append("local_whisper_compute_type", isLocalTranscription ? localWhisperComputeType : "");
    formData.append("note_api_key", noteApiKey);
    formData.append("note_base_url", noteBaseUrl);
    formData.append("note_model", noteModel);
    formData.append("note_language", noteLanguage);
    formData.append("note_style", noteStyle);
    formData.append("extras", extras);
    formData.append("frame_limit", String(frameLimit));

    setIsSubmitting(true);
    try {
      const response = await fetch("/api/jobs", {
        method: "POST",
        body: formData
      });
      const payload = await response.json();
      if (!response.ok) {
        throw new Error(payload.detail || "任务创建失败。");
      }
      setJob(await fetchJob(payload.job_id));
      await refreshJobHistory();
    } catch (error) {
      setSubmitError(error instanceof Error ? error.message : "任务创建失败。");
    } finally {
      setIsSubmitting(false);
    }
  }

  async function refreshHealth() {
    try {
      const response = await fetch("/api/health");
      setHealth(response.ok ? await response.json() : null);
    } catch {
      setHealth(null);
    }
  }

  async function refreshJobHistory() {
    setIsHistoryLoading(true);
    setHistoryError("");
    try {
      const payload = await fetchJobHistory();
      setJobHistory(payload.jobs);
    } catch (error) {
      setHistoryError(error instanceof Error ? error.message : "历史任务读取失败。");
    } finally {
      setIsHistoryLoading(false);
    }
  }

  async function handleDownloadLocalModel() {
    setModelDownloadError("");
    setSubmitError("");
    await startTask({
      request: () =>
        fetch("/api/models/faster-whisper/download", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ model_name: transcriptionModel })
        }),
      optimisticState: {
        model_name: transcriptionModel,
        status: "pending",
        progress: 0,
        error: "",
        model_root: health?.runtime?.local_models.root ?? ""
      } as ModelDownloadState,
      setTask: setModelDownload,
      setError: setModelDownloadError,
      errorMessage: "模型下载启动失败。"
    });
  }

  async function handleInstallLocalDependencies() {
    setLocalDependencyInstallError("");
    setSubmitError("");
    await startTask({
      request: () =>
        fetch("/api/runtime/local-dependencies/install", {
          method: "POST"
        }),
      optimisticState: {
        status: "pending",
        progress: 0,
        error: "",
        python_path: runtimeLocalStatus?.external_python_path ?? ""
      } as LocalDependencyInstallState,
      setTask: setLocalDependencyInstall,
      setError: setLocalDependencyInstallError,
      errorMessage: "本地转写依赖安装启动失败。"
    });
  }

  async function handleInstallCudaDependencies() {
    setCudaInstallError("");
    const shouldInstall = window.confirm(
      "CUDA 加速依赖包含 NVIDIA cuBLAS/cuDNN，下载体积约 1GB+。是否现在安装到当前外部 Python 环境？"
    );
    if (!shouldInstall) {
      return;
    }
    await startTask({
      request: () =>
        fetch("/api/runtime/cuda-dependencies/install", {
          method: "POST"
        }),
      optimisticState: {
        status: "pending",
        progress: 0,
        error: "",
        python_path: health?.runtime?.faster_whisper.external_python_path ?? ""
      } as CudaDependencyInstallState,
      setTask: setCudaInstall,
      setError: setCudaInstallError,
      errorMessage: "CUDA 依赖安装启动失败。"
    });
  }

  function collectSettings(): UserSettings {
    return {
      transcription_mode: transcriptionMode,
      transcription_api_key: transcriptionApiKey,
      transcription_base_url: transcriptionBaseUrl,
      transcription_model: transcriptionModel,
      local_whisper_device: localWhisperDevice,
      local_whisper_compute_type: localWhisperComputeType,
      external_python_path: externalPythonPath,
      faster_whisper_model_dir: fasterWhisperModelDir,
      python_package_install_mode: pythonPackageInstallMode,
      note_api_key: noteApiKey,
      note_base_url: noteBaseUrl,
      note_model: noteModel,
      note_language: noteLanguage,
      note_style: noteStyle,
      extras,
      frame_limit: frameLimit
    };
  }

  function applySettings(settings: UserSettings) {
    setTranscriptionMode(settings.transcription_mode);
    setTranscriptionApiKey(settings.transcription_api_key);
    setTranscriptionBaseUrl(settings.transcription_base_url);
    setTranscriptionModel(settings.transcription_model);
    setLocalWhisperDevice(settings.local_whisper_device ?? "cpu");
    setLocalWhisperComputeType(settings.local_whisper_compute_type ?? "int8");
    setExternalPythonPath(settings.external_python_path ?? "");
    setFasterWhisperModelDir(settings.faster_whisper_model_dir ?? "");
    setPythonPackageInstallMode(settings.python_package_install_mode ?? "default");
    setNoteApiKey(settings.note_api_key);
    setNoteBaseUrl(settings.note_base_url);
    setNoteModel(settings.note_model);
    setNoteLanguage(settings.note_language);
    setNoteStyle(settings.note_style);
    setExtras(settings.extras);
    setFrameLimit(settings.frame_limit);
  }

  async function handleSaveSettings() {
    setIsSavingSettings(true);
    setSettingsMessage("");
    try {
      const response = await fetch("/api/settings", {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(collectSettings())
      });
      const payload = await response.json();
      if (!response.ok) {
        throw new Error(payload.detail || "设置保存失败。");
      }
      applySettings(payload);
      await refreshHealth();
      setSettingsMessage("设置已保存到本地配置文件。");
    } catch (error) {
      setSettingsMessage(error instanceof Error ? error.message : "设置保存失败。");
    } finally {
      setIsSavingSettings(false);
    }
  }

  async function handleClearSettings() {
    setIsSavingSettings(true);
    setSettingsMessage("");
    try {
      const response = await fetch("/api/settings", { method: "DELETE" });
      const payload = await response.json();
      if (!response.ok) {
        throw new Error(payload.detail || "设置清除失败。");
      }
      applySettings(payload);
      await refreshHealth();
      setSettingsMessage("本地设置已清除。");
    } catch (error) {
      setSettingsMessage(error instanceof Error ? error.message : "设置清除失败。");
    } finally {
      setIsSavingSettings(false);
    }
  }

  async function handleRegenerateNote() {
    if (!job) {
      return;
    }
    setVersionError("");
    if (!noteApiKey.trim()) {
      setVersionError("请填写笔记 API Key，再重新生成笔记。");
      return;
    }
    if (!noteBaseUrl.trim() || !noteModel.trim()) {
      setVersionError("笔记 Base URL 和模型不能为空。");
      return;
    }

    const formData = new FormData();
    formData.append("note_api_key", noteApiKey);
    formData.append("note_base_url", noteBaseUrl);
    formData.append("note_model", noteModel);
    formData.append("note_language", noteLanguage);
    formData.append("note_style", noteStyle);
    formData.append("extras", extras);
    formData.append("frame_limit", String(frameLimit));

    setIsRegenerating(true);
    try {
      const response = await fetch(`/api/jobs/${job.job_id}/note-versions`, {
        method: "POST",
        body: formData
      });
      const payload = await response.json();
      if (!response.ok) {
        throw new Error(payload.detail || "重新生成笔记失败。");
      }
      setJob({
        ...job,
        status: "running",
        step: "重新生成笔记",
        progress: Math.max(job.progress, 62),
        error: null
      });
    } catch (error) {
      setVersionError(error instanceof Error ? error.message : "重新生成笔记失败。");
      setIsRegenerating(false);
    }
  }

  async function handleCreateTranscriptCorrection() {
    if (!job) {
      return;
    }
    const requestJobId = job.job_id;
    setCorrectionError("");
    if (!noteApiKey.trim()) {
      setCorrectionError("请填写笔记 API Key，再修正字幕。");
      return;
    }
    if (!noteBaseUrl.trim() || !noteModel.trim()) {
      setCorrectionError("笔记 Base URL 和模型不能为空。");
      return;
    }
    setIsCorrectingTranscript(true);
    try {
      const response = await fetch(`/api/jobs/${requestJobId}/transcript-corrections`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          note_api_key: noteApiKey,
          note_base_url: noteBaseUrl,
          note_model: noteModel,
          instructions: extras
        })
      });
      const payload = await response.json();
      if (!response.ok) {
        throw new Error(payload.detail || "字幕修正失败。");
      }
      if (payload.job_id !== requestJobId) {
        throw new Error("字幕修正结果与当前任务不匹配。");
      }
      setCorrectionPreview(payload);
    } catch (error) {
      setCorrectionError(error instanceof Error ? error.message : "字幕修正失败。");
    } finally {
      setIsCorrectingTranscript(false);
    }
  }

  async function handleApplyTranscriptCorrection() {
    if (!job || !correctionPreview) {
      return;
    }
    const requestJobId = correctionPreview.job_id;
    if (job.job_id !== requestJobId) {
      setCorrectionError("当前任务与字幕修正结果不匹配，请重新发起修正。");
      return;
    }
    setCorrectionError("");
    setIsApplyingCorrection(true);
    try {
      const response = await fetch(`/api/jobs/${requestJobId}/transcript-corrections/apply`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          note_language: noteLanguage,
          note_style: noteStyle,
          extras,
          note_api_key: noteApiKey,
          note_base_url: noteBaseUrl,
          note_model: noteModel,
          frame_limit: frameLimit
        })
      });
      const payload = await response.json();
      if (!response.ok) {
        throw new Error(payload.detail || "采用字幕修正失败。");
      }
      setCorrectionPreview(null);
      const nextJob = await fetchJob(requestJobId);
      setJob({
        ...nextJob,
        status: "running",
        step: "重新生成笔记",
        progress: Math.max(nextJob.progress, 62),
        error: null
      });
      await refreshJobHistory();
    } catch (error) {
      setCorrectionError(error instanceof Error ? error.message : "采用字幕修正失败。");
    } finally {
      setIsApplyingCorrection(false);
    }
  }

  async function handleLoadHistoryJob(jobId: string) {
    setHistoryError("");
    setSubmitError("");
    resetTaskContext();
    setVideo(null);
    clearVideoInput();
    try {
      setJob(await fetchJob(jobId));
    } catch (error) {
      setHistoryError(error instanceof Error ? error.message : "历史任务载入失败。");
    }
  }

  async function handleDeleteHistoryJob(jobId: string) {
    if (!window.confirm("删除后会移除该任务及其所有笔记版本，是否继续？")) {
      return;
    }
    setIsDeletingJobId(jobId);
    setHistoryError("");
    try {
      const response = await fetch(`/api/jobs/${encodeURIComponent(jobId)}`, { method: "DELETE" });
      if (!response.ok) {
        throw new Error(await readResponseError(response, "历史任务删除失败。"));
      }
      if (job?.job_id === jobId) {
        resetTaskContext();
        setVideo(null);
        clearVideoInput();
      }
      await refreshJobHistory();
    } catch (error) {
      setHistoryError(error instanceof Error ? error.message : "历史任务删除失败。");
    } finally {
      setIsDeletingJobId("");
    }
  }

  async function handleNoteVersionChange(event: ChangeEvent<HTMLSelectElement>) {
    if (!job || !noteVersions) {
      return;
    }
    const nextVersionId = event.target.value;
    const previousVersionId = previewVersionId;
    setPreviewVersionId(nextVersionId);
    setVersionError("");
    try {
      const response = await fetch(`/api/jobs/${job.job_id}/note-versions`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          active_version_id: nextVersionId,
          selected_version_ids: noteVersions.selected_version_ids.length
            ? noteVersions.selected_version_ids
            : noteVersions.versions.map((version) => version.id)
        })
      });
      const payload = await response.json();
      if (!response.ok) {
        throw new Error(payload.detail || "笔记版本切换失败。");
      }
      setNoteVersions(payload);
      setPreviewVersionId(payload.active_version_id ?? nextVersionId);
      setJob(await fetchJob(job.job_id));
      await refreshJobHistory();
    } catch (error) {
      setPreviewVersionId(previousVersionId);
      setVersionError(error instanceof Error ? error.message : "笔记版本切换失败。");
    }
  }

  return (
    <main className="app-shell">
      <header className="topbar">
        <div className="topbar-brand">
          <p className="eyebrow">OpenAI-Compatible Video Notes</p>
          <h1>视频笔记生成器</h1>
        </div>
        <div className="topbar-stepper">
          <StepList job={job} />
        </div>
        <div className="topbar-actions">
          <HealthBadge health={health} />
          <StatusBadge job={job} isSubmitting={isSubmitting} />
          <button className="icon-button" onClick={() => setIsSettingsOpen(true)} title="打开设置" type="button">
            <Settings size={17} />
          </button>
        </div>
      </header>

      <form className="workspace-grid" onSubmit={handleSubmit}>
        {job?.error && (
          <div className="error-box">
            <AlertTriangle size={18} />
            <span>{job.error}</span>
          </div>
        )}

        <section className="panel config-panel task-config-panel" aria-label="任务配置">
          <PanelTitle icon={<Upload size={18} />} title="视频与笔记要求" />

          <div className="config-main">
            <div className="field video-config-block">
              <span className="field-label">视频文件</span>
              <label className="drop-zone">
                <input
                  accept=".mp4,.mov,.mkv,.webm,.avi,video/*"
                  ref={videoInputRef}
                  type="file"
                  onChange={handleVideoChange}
                />
                <Upload size={18} />
                <span>{video ? video.name : "选择文件"}</span>
              </label>
            </div>

            <div className="quick-settings">
              <label className="field">
                <span className="field-label">笔记语言</span>
                <select value={noteLanguage} onChange={(event) => setNoteLanguage(event.target.value as NoteLanguage)}>
                  <option value="zh">中文</option>
                  <option value="en">英文</option>
                  <option value="follow">跟随原文</option>
                </select>
              </label>

              <label className="field">
                <span className="field-label">笔记风格</span>
                <select value={noteStyle} onChange={(event) => setNoteStyle(event.target.value as NoteStyle)}>
                  {noteStyleOptions.map((option) => (
                    <option key={option.value} value={option.value}>
                      {option.label}
                    </option>
                  ))}
                </select>
              </label>

              <label className="field">
                <span className="field-label">关键帧上限</span>
                <input
                  max={24}
                  min={1}
                  type="number"
                  value={frameLimit}
                  onChange={(event) => setFrameLimit(Number(event.target.value))}
                />
              </label>
            </div>

            <label className="field extras-field">
              <span className="field-label">额外笔记要求</span>
              <input
                maxLength={2000}
                onChange={(event) => setExtras(event.target.value)}
                placeholder="例如：突出操作步骤、保留关键术语、最后补一组行动项"
                type="text"
                value={extras}
              />
            </label>

            <div className="config-submit-block">
              {submitError && (
                <p className="inline-error">
                  <AlertTriangle size={15} />
                  {submitError}
                </p>
              )}

              <button className="primary-button" disabled={isBusy} type="submit">
                {isBusy ? <Loader2 className="spin" size={18} /> : <Play size={18} />}
                开始生成
              </button>
            </div>
          </div>
        </section>

        <div className="workspace-bottom">
          <section className="panel history-panel history-column" aria-label="历史任务">
            <div className="history-header">
              <div className="section-title">
                <History size={16} />
                <span>历史任务</span>
              </div>
              <button className="small-button" disabled={isHistoryLoading} onClick={() => void refreshJobHistory()} type="button">
                {isHistoryLoading ? <Loader2 className="spin" size={15} /> : <RefreshCw size={15} />}
                刷新
              </button>
            </div>
            {historyError && (
              <p className="inline-error">
                <AlertTriangle size={15} />
                {historyError}
              </p>
            )}
            {jobHistory.length === 0 ? (
              <p className="empty-history">完成任务后会显示在这里。</p>
            ) : (
              <div className="history-list">
                {jobHistory.map((item) => (
                  <article className={`history-item ${job?.job_id === item.job_id ? "active" : ""}`} key={item.job_id}>
                    <div className="history-item-main">
                      <div>
                        <strong>{item.title || item.original_filename}</strong>
                        <span>{item.original_filename}</span>
                      </div>
                      <span className={`badge ${item.status}`}>{statusText[item.status]}</span>
                    </div>
                    <div className="history-meta">
                      <span>{formatHistoryTime(item.created_at)}</span>
                      <span>{item.note_version_count} 个版本</span>
                      <span>{item.artifact_count} 个产物</span>
                    </div>
                    <div className="history-actions">
                      <button className="small-button" disabled={isBusy} onClick={() => void handleLoadHistoryJob(item.job_id)} type="button">
                        <FolderOpen size={15} />
                        载入
                      </button>
                      <button
                        className="small-button danger"
                        disabled={isBusy || isDeletingJobId === item.job_id}
                        onClick={() => void handleDeleteHistoryJob(item.job_id)}
                        type="button"
                      >
                        {isDeletingJobId === item.job_id ? <Loader2 className="spin" size={15} /> : <Trash2 size={15} />}
                        删除
                      </button>
                    </div>
                  </article>
                ))}
              </div>
            )}
          </section>

          <section className="panel result-panel" aria-label="结果预览">
            <div className="panel-title result-panel-title">
              <div className="panel-title-main">
                <FileText size={18} />
                <h2>结果预览</h2>
              </div>
              {previewVersion && <span className="result-version-summary">{formatVersionDetails(previewVersion)}</span>}
            </div>
            <div className="download-row">
              <div className="download-actions">
                <DownloadLink job={job} artifactPath="note.md" label="Markdown" onDownloadError={setDownloadMessage} />
                <DownloadLink job={job} artifactPath="subtitles.srt" label="SRT" onDownloadError={setDownloadMessage} />
                <DownloadLink job={job} artifactPath="audio.mp3" label="MP3" onDownloadError={setDownloadMessage} />
                <DownloadLink job={job} artifactPath="debug.log" label="调试日志" onDownloadError={setDownloadMessage} />
                {job?.artifacts.some((artifact) => artifact.path === "download.zip") && job && (
                  <ArtifactDownloadButton
                    className="small-button strong"
                    filename={`video-note-${job.job_id}.zip`}
                    label="ZIP"
                    onError={setDownloadMessage}
                    url={`/api/jobs/${job.job_id}/download.zip`}
                  />
                )}
              </div>
              <div className="result-toolbar-right">
                {noteVersions && noteVersions.versions.length > 0 && (
                  <label className="version-inline">
                    <span>版本</span>
                    <select disabled={isBusy} value={previewVersionId} onChange={handleNoteVersionChange}>
                      {noteVersions.versions.map((version) => (
                        <option key={version.id} value={version.id}>
                          {formatVersionOption(version)}
                        </option>
                      ))}
                    </select>
                    {previewVersion?.active && <span className="mini-badge ok">当前</span>}
                  </label>
                )}
                <button className="small-button strong" disabled={!job || isBusy} onClick={handleRegenerateNote} type="button">
                  {isRegenerating ? <Loader2 className="spin" size={15} /> : <RefreshCw size={15} />}
                  重新生成笔记
                </button>
              </div>
            </div>
            {downloadMessage && (
              <p className="inline-warning">
                <AlertTriangle size={15} />
                {downloadMessage}
              </p>
            )}
            {versionError && (
              <p className="inline-error">
                <AlertTriangle size={15} />
                {versionError}
              </p>
            )}
            {correctionError && !correctionPreview && (
              <p className="inline-error">
                <AlertTriangle size={15} />
                {correctionError}
              </p>
            )}
            <div className="result-body-scroll">
              <div className="preview-stack">
                <PreviewBlock
                  assetBasePath={previewAssetBasePath}
                  title={previewVersion ? `视频笔记 Markdown · ${previewVersion.id}` : "视频笔记 Markdown"}
                  text={notePreview}
                  empty="完成后显示 note.md 预览"
                  jobId={job?.job_id}
                />
                <PreviewBlock
                  title="字幕 Markdown"
                  titleAction={
                    job?.artifacts.some((artifact) => artifact.path === "transcript.json") ? (
                      <button
                        className="small-button"
                        disabled={isBusy || isCorrectingTranscript}
                        onClick={() => void handleCreateTranscriptCorrection()}
                        type="button"
                      >
                        {isCorrectingTranscript ? <Loader2 className="spin" size={15} /> : <Captions size={15} />}
                        AI 修正字幕
                      </button>
                    ) : null
                  }
                  text={subtitlePreview}
                  empty="字幕生成后显示时间戳预览"
                  jobId={job?.job_id}
                />
              </div>

              <div className="frame-grid" aria-label="关键帧">
                {previewImages.length === 0 ? (
                  <div className="empty-frames">
                    <Image size={20} />
                    <span>关键帧完成后显示在这里</span>
                  </div>
                ) : (
                  previewImages.map((artifact) => (
                    <figure key={artifact.path}>
                      <img alt={artifact.label} src={artifact.asset_url} />
                      <figcaption>{artifact.label}</figcaption>
                    </figure>
                  ))
                )}
              </div>
            </div>
          </section>
        </div>
      </form>

      {isSettingsOpen && (
        <div className="modal-backdrop" onMouseDown={() => setIsSettingsOpen(false)}>
          <section
            aria-label="设置"
            aria-modal="true"
            className="settings-modal"
            onMouseDown={(event) => event.stopPropagation()}
            role="dialog"
          >
            <div className="modal-header">
              <div>
                <p className="eyebrow">Local Settings</p>
                <h2>模型与运行环境设置</h2>
              </div>
              <button className="icon-button" onClick={() => setIsSettingsOpen(false)} title="关闭设置" type="button">
                <X size={18} />
              </button>
            </div>

            <div className="modal-body">
              <section className="settings-strip" aria-label="本地设置">
                <div>
                  <strong>本地配置文件</strong>
                  <span title={health?.runtime?.settings.path}>
                    保存 Base URL、模型和 API Key。Key 会明文写入本机配置文件。
                  </span>
                </div>
                <div className="settings-actions">
                  <button className="small-button strong" disabled={isSavingSettings} onClick={handleSaveSettings} type="button">
                    {isSavingSettings ? <Loader2 className="spin" size={15} /> : <CheckCircle2 size={15} />}
                    保存设置
                  </button>
                  <button className="small-button" disabled={isSavingSettings} onClick={handleClearSettings} type="button">
                    清除设置
                  </button>
                </div>
                {settingsMessage && <p className="settings-message">{settingsMessage}</p>}
              </section>

              <section className="api-section">
                <div className="section-title">
                  <Captions size={16} />
                  <span>字幕转写配置</span>
                </div>
                <p className="field-help">
                  {isLocalTranscription
                    ? "本地 Faster Whisper 使用内置依赖或外部 Python worker；缺模型时可在这里下载。"
                    : "远端转写使用 OpenAI-compatible API，请确认模型支持音频转写或多模态音频。"}
                </p>

                <label className="field">
                  <span className="field-label">转写来源</span>
                  <select
                    value={transcriptionMode}
                    onChange={(event) => {
                      const nextMode = event.target.value as TranscriptionMode;
                      setTranscriptionMode(nextMode);
                      if (nextMode === "local_faster_whisper") {
                        setTranscriptionModel("small");
                      } else if (transcriptionMode === "local_faster_whisper") {
                        setTranscriptionModel(nextMode === "chat_audio" ? "gpt-5.5" : "whisper-1");
                      }
                    }}
                  >
                    <option value="local_faster_whisper">本地 Faster Whisper</option>
                    <option value="audio_transcriptions">Audio Transcriptions 端点</option>
                    <option value="chat_audio">Chat 多模态音频兜底</option>
                  </select>
                </label>

                {isLocalTranscription ? (
                  <>
                    <label className="field">
                      <span className="field-label">本地模型</span>
                      <select value={transcriptionModel} onChange={(event) => setTranscriptionModel(event.target.value)}>
                        <option value="small">small（默认，速度/准确率均衡）</option>
                        <option value="medium">medium（更准，更慢）</option>
                        <option value="large-v3">large-v3（质量优先）</option>
                        <option value="base">base（更快，准确率较低）</option>
                      </select>
                    </label>
                    <div className="two-col">
                      <label className="field">
                        <span className="field-label">运行设备</span>
                        <select
                          value={localWhisperDevice}
                          onChange={(event) => {
                            const nextDevice = event.target.value as LocalWhisperDevice;
                            setLocalWhisperDevice(nextDevice);
                            if (nextDevice === "cuda" && localWhisperComputeType === "int8") {
                              setLocalWhisperComputeType("float16");
                            }
                            if (nextDevice === "cpu" && localWhisperComputeType === "float16") {
                              setLocalWhisperComputeType("int8");
                            }
                          }}
                        >
                          <option value="cpu">CPU（兼容优先）</option>
                          <option value="cuda">CUDA GPU（NVIDIA）</option>
                          <option value="auto">Auto（由 CTranslate2 判断）</option>
                        </select>
                      </label>

                      <label className="field">
                        <span className="field-label">计算精度</span>
                        <select
                          value={localWhisperComputeType}
                          onChange={(event) => setLocalWhisperComputeType(event.target.value as LocalWhisperComputeType)}
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
                    {!health?.runtime?.faster_whisper.worker_ready && (
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
                          onClick={handleInstallLocalDependencies}
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
                          onClick={handleInstallCudaDependencies}
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
                          onClick={handleDownloadLocalModel}
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
                ) : (
                  <>
                    <label className="field">
                      <span className="field-label">Base URL</span>
                      <input value={transcriptionBaseUrl} onChange={(event) => setTranscriptionBaseUrl(event.target.value)} />
                    </label>

                    <label className="field">
                      <span className="field-label">转写模型</span>
                      <input value={transcriptionModel} onChange={(event) => setTranscriptionModel(event.target.value)} />
                    </label>

                    <label className="field">
                      <span className="field-label">
                        <KeyRound size={15} />
                        转写 API Key
                      </span>
                      <input
                        autoComplete="off"
                        placeholder="可保存到本地设置"
                        type="password"
                        value={transcriptionApiKey}
                        onChange={(event) => setTranscriptionApiKey(event.target.value)}
                      />
                    </label>
                  </>
                )}
              </section>

              <section className="api-section">
                <div className="section-title">
                  <FileText size={16} />
                  <span>笔记生成 API</span>
                </div>
                <p className="field-help">用于把字幕整理为结构化笔记。可填 OpenAI、Qwen 或其他 OpenAI-compatible Chat API。</p>

                <div className="preset-row" aria-label="常用 Base URL">
                  <button type="button" onClick={() => setNoteBaseUrl(OPENAI_BASE_URL)}>
                    OpenAI
                  </button>
                  <button type="button" onClick={() => setNoteBaseUrl(QWEN_BASE_URL)}>
                    Qwen
                  </button>
                </div>

                <label className="field">
                  <span className="field-label">Base URL</span>
                  <input value={noteBaseUrl} onChange={(event) => setNoteBaseUrl(event.target.value)} />
                </label>

                <label className="field">
                  <span className="field-label">笔记模型</span>
                  <input value={noteModel} onChange={(event) => setNoteModel(event.target.value)} />
                </label>

                <label className="field">
                  <span className="field-label">
                    <KeyRound size={15} />
                    笔记 API Key
                  </span>
                  <input
                    autoComplete="off"
                    placeholder="可保存到本地设置"
                    type="password"
                    value={noteApiKey}
                    onChange={(event) => setNoteApiKey(event.target.value)}
                  />
                </label>
              </section>

              <section className="api-section">
                <div className="section-title">
                  <Server size={16} />
                  <span>运行环境</span>
                </div>
                <RuntimeStatusCard runtime={health?.runtime ?? null} />
              </section>
            </div>

            <div className="modal-footer">
              <button className="small-button" onClick={() => setIsSettingsOpen(false)} type="button">
                关闭
              </button>
              <button className="small-button strong" disabled={isSavingSettings} onClick={handleSaveSettings} type="button">
                {isSavingSettings ? <Loader2 className="spin" size={15} /> : <CheckCircle2 size={15} />}
                保存设置
              </button>
            </div>
          </section>
        </div>
      )}
      <TranscriptCorrectionModal
        error={correctionError}
        isApplying={isApplyingCorrection}
        onApply={() => void handleApplyTranscriptCorrection()}
        onClose={() => {
          if (!isApplyingCorrection) {
            setCorrectionPreview(null);
            setCorrectionError("");
          }
        }}
        preview={correctionPreview}
      />
    </main>
  );
}

async function fetchJob(jobId: string): Promise<JobState> {
  const response = await fetch(`/api/jobs/${jobId}`);
  if (!response.ok) {
    throw new Error(await readResponseError(response, "任务状态读取失败。"));
  }
  return response.json();
}

async function fetchJobHistory(): Promise<{ jobs: JobSummary[] }> {
  const response = await fetch("/api/jobs");
  if (!response.ok) {
    throw new Error(await readResponseError(response, "历史任务读取失败。"));
  }
  return response.json();
}

async function readResponseError(response: Response, fallback: string): Promise<string> {
  const contentType = response.headers.get("content-type") ?? "";
  try {
    if (contentType.includes("application/json")) {
      const payload = (await response.json()) as { detail?: string };
      return payload.detail || fallback;
    }
    const text = (await response.text()).trim();
    return text || fallback;
  } catch {
    return fallback;
  }
}

function isDesktopDownloadAvailable() {
  return typeof window !== "undefined" && typeof window.pywebview?.api?.save_file === "function";
}

function buildAbsoluteUrl(path: string) {
  return new URL(path, window.location.origin).toString();
}

function deriveDownloadFilename(path: string, fallbackLabel: string) {
  const lastSegment = path.split("/").filter(Boolean).at(-1);
  return lastSegment || fallbackLabel;
}

async function triggerBrowserDownload(url: string, filename: string) {
  const response = await fetch(url);
  if (!response.ok) {
    throw new Error(`下载失败：${response.status}`);
  }
  const blob = await response.blob();
  const objectUrl = window.URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = objectUrl;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  window.URL.revokeObjectURL(objectUrl);
}

async function downloadArtifact(url: string, filename: string) {
  if (isDesktopDownloadAvailable()) {
    return window.pywebview!.api!.save_file!(filename, buildAbsoluteUrl(url));
  }
  await triggerBrowserDownload(url, filename);
  return { ok: true };
}

async function fetchNoteVersions(jobId: string): Promise<NoteVersionIndex> {
  const response = await fetch(`/api/jobs/${jobId}/note-versions`);
  if (!response.ok) {
    throw new Error("笔记版本读取失败。");
  }
  return response.json();
}

function RuntimeStatusCard({ runtime }: { runtime: RuntimeState | null }) {
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
        : runtime.faster_whisper.worker_error || runtime.faster_whisper.install_hint;
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
        : `${runtime.faster_whisper.worker_error || runtime.faster_whisper.install_hint} · ${pythonSource}`;
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
      <RuntimeItem ok={runtime.faster_whisper.available} title="本地转写引擎" detail={fasterWhisperDetail} />
      <RuntimeItem ok={runtime.faster_whisper.python_available && runtime.faster_whisper.worker_ready} title="外部 Python 环境" detail={pythonDetail} />
      <RuntimeItem
        ok={runtime.faster_whisper.cuda_available}
        soft
        title="CUDA 加速"
        detail={cudaDetail}
      />
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

function RuntimeItem({ detail, ok, soft, title }: { detail: string; ok: boolean; soft?: boolean; title: string }) {
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

function HealthBadge({ health }: { health: HealthState | null }) {
  if (!health) {
    return <span className="badge muted">后端未连接</span>;
  }
  if (health.runtime) {
    const runtimeOk =
      health.runtime.ffmpeg.available &&
      (health.runtime.faster_whisper.internal_available || health.runtime.faster_whisper.worker_ready);
    return (
      <span className={runtimeOk ? "badge ok" : "badge warn"} title={health.runtime.settings.path}>
        {runtimeOk ? "运行环境可用" : "依赖待处理"}
      </span>
    );
  }
  return (
    <span className={health.ffmpeg_available ? "badge ok" : "badge warn"} title={health.ffmpeg_path ?? undefined}>
      {health.ffmpeg_available ? "FFmpeg 可用" : "缺少 FFmpeg"}
    </span>
  );
}

function StatusBadge({ job, isSubmitting }: { job: JobState | null; isSubmitting: boolean }) {
  if (isSubmitting) {
    return <span className="badge running">创建任务</span>;
  }
  if (!job) {
    return <span className="badge muted">未开始</span>;
  }
  return <span className={`badge ${job.status}`}>{statusText[job.status]}</span>;
}

function PanelTitle({ icon, title }: { icon: React.ReactNode; title: string }) {
  return (
    <div className="panel-title">
      {icon}
      <h2>{title}</h2>
    </div>
  );
}

function StepList({ job }: { job: JobState | null }) {
  const steps = [
    { label: "音频分离", threshold: 15 },
    { label: "字幕生成", threshold: 35 },
    { label: "笔记生成", threshold: 60 },
    { label: "关键帧抽取", threshold: 78 },
    { label: "Markdown 输出", threshold: 90 }
  ];
  return (
    <ol className="step-list">
      {steps.map((step, index) => {
        const done = (job?.progress ?? 0) >= step.threshold && job?.status !== "failed";
        const active = job?.step === step.label;
        return (
          <li className={done ? "done" : active ? "active" : ""} key={step.label}>
            <strong>{index + 1}</strong>
            <span>{step.label}</span>
          </li>
        );
      })}
    </ol>
  );
}

function DownloadLink({
  job,
  artifactPath,
  label,
  onDownloadError
}: {
  job: JobState | null;
  artifactPath: string;
  label: string;
  onDownloadError: (message: string) => void;
}) {
  const artifact = job?.artifacts.find((item) => item.path === artifactPath);
  if (!artifact) {
    return (
      <button className="small-button" disabled type="button">
        <Download size={15} />
        {label}
      </button>
    );
  }
  return (
    <ArtifactDownloadButton
      filename={deriveDownloadFilename(artifact.path, `${label}.txt`)}
      label={label}
      onError={onDownloadError}
      url={artifact.asset_url}
    />
  );
}

function ArtifactDownloadButton({
  className = "small-button",
  filename,
  label,
  onError,
  url
}: {
  className?: string;
  filename: string;
  label: string;
  onError: (message: string) => void;
  url: string;
}) {
  async function handleClick() {
    onError("");
    try {
      const result = await downloadArtifact(url, filename);
      if (!result.ok && result.reason !== "cancelled") {
        onError("下载失败，请稍后重试。");
      }
    } catch (error) {
      onError(error instanceof Error ? error.message : "下载失败，请稍后重试。");
    }
  }

  return (
    <button className={className} onClick={handleClick} type="button">
      <Download size={15} />
      {label}
    </button>
  );
}

function PreviewBlock({
  assetBasePath,
  title,
  titleAction,
  text,
  empty,
  jobId
}: {
  assetBasePath?: string;
  title: string;
  titleAction?: React.ReactNode;
  text: string;
  empty: string;
  jobId?: string;
}) {
  return (
    <section className="preview-block">
      <div className="preview-title-row">
        <h3>{title}</h3>
        {titleAction}
      </div>
      {text ? <MarkdownPreview assetBasePath={assetBasePath} markdown={text} jobId={jobId} /> : <p>{empty}</p>}
    </section>
  );
}

function TranscriptCorrectionModal({
  error,
  isApplying,
  onApply,
  onClose,
  preview
}: {
  error: string;
  isApplying: boolean;
  onApply: () => void;
  onClose: () => void;
  preview: TranscriptCorrectionPreview | null;
}) {
  if (!preview) {
    return null;
  }
  return (
    <div className="modal-backdrop" onMouseDown={onClose}>
      <section className="settings-modal correction-modal" aria-label="AI 字幕修正对比" onMouseDown={(event) => event.stopPropagation()}>
        <div className="modal-header">
          <div>
            <p className="eyebrow">Transcript correction</p>
            <h2>AI 字幕修正对比</h2>
          </div>
          <button className="icon-button" disabled={isApplying} onClick={onClose} type="button">
            <X size={18} />
          </button>
        </div>

        <div className="modal-body correction-body">
          <p className="correction-summary">
            共 {preview.segments.length} 段，AI 建议修改 {preview.changed_count} 段。采用后会重写字幕文件，并基于修正版生成新的笔记版本。
          </p>
          {error && (
            <p className="inline-error">
              <AlertTriangle size={15} />
              {error}
            </p>
          )}
          <div className="correction-diff-grid">
            <div className="correction-column-title">原始字幕</div>
            <div className="correction-column-title">AI 修正版</div>
            {preview.segments.map((segment) => (
              <div className="correction-row-pair" key={segment.index}>
                <div className={segment.changed ? "correction-row changed" : "correction-row"}>
                  <strong>{formatSecondsRange(segment.start, segment.end)}</strong>
                  <span>{segment.original_text}</span>
                </div>
                <div className={segment.changed ? "correction-row changed" : "correction-row"}>
                  <strong>{formatSecondsRange(segment.start, segment.end)}</strong>
                  <span>{segment.corrected_text}</span>
                </div>
              </div>
            ))}
          </div>
        </div>

        <div className="modal-footer">
          <button className="small-button" disabled={isApplying} onClick={onClose} type="button">
            取消
          </button>
          <button className="small-button strong" disabled={isApplying} onClick={onApply} type="button">
            {isApplying ? <Loader2 className="spin" size={15} /> : <CheckCircle2 size={15} />}
            采用修正版并重新生成笔记
          </button>
        </div>
      </section>
    </div>
  );
}

function MarkdownPreview({ assetBasePath, markdown, jobId }: { assetBasePath?: string; markdown: string; jobId?: string }) {
  return (
    <div className="markdown-preview">
      {parseMarkdown(markdown).map((block, index) => {
        if (block.type === "heading") {
          return <MarkdownHeading key={index} level={block.level} text={block.text} />;
        }
        if (block.type === "list") {
          const items = block.items.map((item, itemIndex) => <li key={itemIndex}>{item}</li>);
          return block.ordered ? <ol key={index}>{items}</ol> : <ul key={index}>{items}</ul>;
        }
        if (block.type === "image") {
          const src = resolvePreviewAssetUrl(block.src, jobId, assetBasePath);
          if (!src) {
            return (
              <p className="markdown-unsupported" key={index}>
                {block.alt || block.src}
              </p>
            );
          }
          return (
            <figure className="markdown-image" key={index}>
              <img alt={block.alt} src={src} />
              {block.alt && <figcaption>{block.alt}</figcaption>}
            </figure>
          );
        }
        return <p key={index}>{block.text}</p>;
      })}
    </div>
  );
}

function MarkdownHeading({ level, text }: { level: number; text: string }) {
  if (level === 1) return <h1>{text}</h1>;
  if (level === 2) return <h2>{text}</h2>;
  if (level === 3) return <h3>{text}</h3>;
  if (level === 4) return <h4>{text}</h4>;
  if (level === 5) return <h5>{text}</h5>;
  return <h6>{text}</h6>;
}

function parseMarkdown(markdown: string): MarkdownBlock[] {
  const blocks: MarkdownBlock[] = [];
  let paragraph: string[] = [];
  let list: Extract<MarkdownBlock, { type: "list" }> | null = null;

  const flushParagraph = () => {
    if (paragraph.length > 0) {
      blocks.push({ type: "paragraph", text: paragraph.join(" ") });
      paragraph = [];
    }
  };
  const flushList = () => {
    if (list) {
      blocks.push(list);
      list = null;
    }
  };

  for (const line of markdown.split(/\r?\n/)) {
    const trimmed = line.trim();
    if (!trimmed) {
      flushParagraph();
      flushList();
      continue;
    }

    const heading = /^(#{1,6})\s+(.+)$/.exec(trimmed);
    const image = /^!\[([^\]]*)\]\(([^)]+)\)$/.exec(trimmed);
    const unordered = /^[-*]\s+(.+)$/.exec(trimmed);
    const ordered = /^\d+[.)]\s+(.+)$/.exec(trimmed);

    if (heading) {
      flushParagraph();
      flushList();
      blocks.push({ type: "heading", level: heading[1].length, text: heading[2].trim() });
    } else if (image) {
      flushParagraph();
      flushList();
      blocks.push({ type: "image", alt: image[1].trim(), src: image[2].trim() });
    } else if (unordered || ordered) {
      flushParagraph();
      const isOrdered = Boolean(ordered);
      if (!list || list.ordered !== isOrdered) {
        flushList();
        list = { type: "list", ordered: isOrdered, items: [] };
      }
      list.items.push((ordered?.[1] ?? unordered?.[1] ?? "").trim());
    } else {
      flushList();
      paragraph.push(trimmed);
    }
  }

  flushParagraph();
  flushList();
  return blocks;
}

function extractMarkdownImages(markdown: string, jobId?: string, assetBasePath?: string): PreviewImage[] {
  if (!jobId) {
    return [];
  }
  return parseMarkdown(markdown)
    .filter((block): block is Extract<MarkdownBlock, { type: "image" }> => block.type === "image")
    .map((block, index) => ({
      label: block.alt || `frame_${index + 1}`,
      path: `${assetBasePath ? `${assetBasePath}/` : ""}${block.src}`.replace(/\\/g, "/"),
      asset_url: resolvePreviewAssetUrl(block.src, jobId, assetBasePath)
    }))
    .filter((image) => image.asset_url);
}

function resolvePreviewAssetUrl(path: string, jobId?: string, assetBasePath?: string) {
  const value = path.trim().replace(/^["']|["']$/g, "");
  if (!jobId || !value || /^(?:[a-z][a-z\d+.-]*:|\/\/|\/)/i.test(value)) {
    return "";
  }
  const normalizedPath = assetBasePath ? `${assetBasePath.replace(/\/$/, "")}/${value}` : value;
  const segments = normalizedPath
    .replace(/\\/g, "/")
    .replace(/^\.?\//, "")
    .split("/")
    .filter((segment) => segment && segment !== "." && segment !== "..");
  if (segments.length === 0) {
    return "";
  }
  return `/api/jobs/${encodeURIComponent(jobId)}/assets/${segments.map(encodeURIComponent).join("/")}`;
}
