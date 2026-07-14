export type NoteLanguage = "zh" | "en" | "follow";
export type NoteStyle = "minimal" | "detailed" | "tutorial" | "academic" | "task_oriented" | "meeting_minutes";
export type TranscriptionMode = "audio_transcriptions" | "chat_audio" | "local_faster_whisper";
export type TranscriptionLanguage = "auto" | "zh" | "en";
export type PerformanceMode = "fast" | "balanced" | "accurate";
export type LocalWhisperDevice = "auto" | "cpu" | "cuda";
export type LocalWhisperComputeType = "default" | "int8" | "int8_float16" | "float16" | "float32";
export type RuntimePathSource = "environment" | "settings" | "default" | "missing";
export type PythonPackageInstallMode = "default" | "user";
export type JobStatus = "pending" | "running" | "cancelling" | "awaiting_subtitle_confirmation" | "awaiting_note_review" | "succeeded" | "failed" | "cancelled";
export type JobStage = "queued" | "analyzing_video" | "extracting_audio" | "transcribing" | "awaiting_subtitle_review" | "generating_note" | "generating_frames" | "preparing_review" | "awaiting_note_review" | "finalizing" | "completed" | "failed" | "cancelling" | "cancelled";

export type Artifact = {
  label: string;
  path: string;
  kind: "audio" | "subtitle" | "markdown" | "image" | "json" | "zip" | "log";
  asset_url: string;
};

export type FailureContext = {
  ts?: string;
  stage?: string;
  message?: string;
  context?: string;
  attempt?: number;
  note_base_url?: string;
  note_model?: string;
  response_file?: string;
  finish_reason?: string;
  message_chars?: number;
  max_tokens?: number;
  response_length?: number;
  status_code?: number;
  error_code?: string;
  flagged_categories?: string[];
  summary?: string;
};

export type TranscriptionWorkProgress = {
  completed_seconds: number;
  total_seconds: number;
  completed_chunks: number;
  total_chunks: number;
  current_chunk?: number | null;
  realtime_factor?: number | null;
  eta_seconds?: number | null;
  resumable: boolean;
  cache_hits: number;
  device: string;
  compute_type: string;
};

export type JobState = {
  job_id: string;
  status: JobStatus;
  step: string;
  stage?: JobStage;
  progress: number;
  work_progress?: TranscriptionWorkProgress | null;
  error?: string | null;
  failure_context?: FailureContext | null;
  artifacts: Artifact[];
  step_started_at?: string | null;
  updated_at?: string | null;
  stage_elapsed_seconds?: number;
  download_filename?: string | null;
};

export type JobSummary = {
  job_id: string;
  title: string;
  original_filename: string;
  created_at?: string | null;
  updated_at?: string | null;
  status: JobStatus;
  error?: string | null;
  failure_context?: FailureContext | null;
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
  transcription_language: TranscriptionLanguage;
  transcription_api_key: string;
  transcription_base_url: string;
  transcription_model: string;
  local_whisper_device: LocalWhisperDevice;
  local_whisper_compute_type: LocalWhisperComputeType;
  performance_mode: PerformanceMode;
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

export type QualityScores = {
  coverage: number;
  structure: number;
  frames: number;
  stability: number;
};

export type QualityIssue = {
  severity: "info" | "warning" | "error";
  type: string;
  message: string;
  chapter_index?: number | null;
  frame_ids: string[];
};

export type ChapterQualityReport = {
  chapter_index: number;
  title: string;
  start_time: number;
  end_time: number;
  transcript_chars: number;
  note_chars: number;
  selected_frame_count: number;
  issues: string[];
};

export type QualityReport = {
  status: "ready" | "review_recommended" | "needs_attention";
  scores: QualityScores;
  issues: QualityIssue[];
  chapter_reports: ChapterQualityReport[];
};

export type FrameCandidate = {
  id: string;
  chapter_index: number;
  time: number;
  path: string;
  reason: string;
  note_excerpt: string;
  subtitle_excerpt: string;
  source: "note_key_moment" | "chapter_fallback";
  hash: string;
  duplicate_of?: string | null;
  similarity: number;
  risk_flags: string[];
  selected: boolean;
  rejected: boolean;
};

export type FrameCandidateChapterContext = {
  chapter_index: number;
  title: string;
  start_time: number;
  end_time: number;
  note_excerpt: string;
  subtitle_excerpt: string;
};

export type FrameCandidateIndex = {
  candidates: FrameCandidate[];
  chapter_contexts: FrameCandidateChapterContext[];
};

export type ReviewSubtitleSegment = {
  start: number;
  end: number;
  text: string;
};

export type ReviewDraftParagraphStatus = "needs_review" | "edited" | "approved";

export type ReviewDraftParagraph = {
  id: string;
  chapter_index: number;
  title: string;
  start_time: number;
  end_time: number;
  body: string;
  subtitle_segments: ReviewSubtitleSegment[];
  selected_frame_ids: string[];
  status: ReviewDraftParagraphStatus;
};

export type ReviewDraft = {
  title: string;
  paragraphs: ReviewDraftParagraph[];
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

export type NoteChunkMeta = {
  id: string;
  index: number;
  total: number;
  label: string;
  start_time: number;
  end_time: number;
  segment_start: number;
  segment_end: number;
  status: string;
  title: string;
};

export type NoteChunkIndex = {
  chunks: NoteChunkMeta[];
  total_segments: number;
};
