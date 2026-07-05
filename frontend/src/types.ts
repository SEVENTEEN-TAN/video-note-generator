export type NoteLanguage = "zh" | "en" | "follow";
export type NoteStyle = "minimal" | "detailed" | "tutorial" | "academic" | "task_oriented" | "meeting_minutes";
export type TranscriptionMode = "audio_transcriptions" | "chat_audio" | "local_faster_whisper";
export type LocalWhisperDevice = "auto" | "cpu" | "cuda";
export type LocalWhisperComputeType = "default" | "int8" | "int8_float16" | "float16" | "float32";
export type RuntimePathSource = "environment" | "settings" | "default" | "missing";
export type PythonPackageInstallMode = "default" | "user";
export type JobStatus = "pending" | "running" | "succeeded" | "failed";

export type Artifact = {
  label: string;
  path: string;
  kind: "audio" | "subtitle" | "markdown" | "image" | "json" | "zip" | "log";
  asset_url: string;
};

export type JobState = {
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

export type JobSummary = {
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

export type NoteVersion = {
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

export type NoteVersionIndex = {
  active_version_id?: string | null;
  selected_version_ids: string[];
  versions: NoteVersion[];
};

export type TranscriptCorrectionSegment = {
  index: number;
  start: number;
  end: number;
  original_text: string;
  corrected_text: string;
  changed: boolean;
};

export type TranscriptCorrectionPreview = {
  job_id: string;
  changed_count: number;
  segments: TranscriptCorrectionSegment[];
};

export type RuntimeState = {
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

export type HealthState = {
  ok: boolean;
  runtime_ok?: boolean;
  ffmpeg_available: boolean;
  ffmpeg_path?: string | null;
  runtime?: RuntimeState;
};

export type UserSettings = {
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

export type LocalDependencyInstallState = {
  status: "idle" | "pending" | "running" | "succeeded" | "failed";
  progress: number;
  error: string;
  python_path: string;
};

export type PollableTaskState = {
  status: "idle" | "pending" | "running" | "succeeded" | "failed";
};

export type ModelDownloadState = {
  model_name: string;
  status: "idle" | "pending" | "running" | "succeeded" | "failed";
  progress: number;
  error: string;
  model_root: string;
};

export type CudaDependencyInstallState = {
  status: "idle" | "pending" | "running" | "succeeded" | "failed";
  progress: number;
  error: string;
  python_path: string;
};

export type MarkdownBlock =
  | { type: "heading"; level: number; text: string }
  | { type: "list"; ordered: boolean; items: string[] }
  | { type: "paragraph"; text: string }
  | { type: "image"; alt: string; src: string };

export type PreviewImage = {
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
