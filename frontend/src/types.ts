import type { components } from "./api.generated";

type ApiSchemas = components["schemas"];
type WithRequired<T, K extends keyof T> = Omit<T, K> & Required<Pick<T, K>>;

// FastAPI-owned API DTOs. Feature code keeps readable aliases while fields
// and enum values come from the generated OpenAPI contract.
export type NoteLanguage = ApiSchemas["NoteLanguage"];
export type NoteStyle = ApiSchemas["NoteStyle"];
export type AIProtocol = ApiSchemas["AIProtocol"];
export type AIModelInfo = ApiSchemas["AIModelInfo"];
export type AIModelListRequest = ApiSchemas["AIModelListRequest"];
export type AIModelListResponse = ApiSchemas["AIModelListResponse"];
export type TranscriptionMode = ApiSchemas["TranscriptionMode"];
export type TranscriptionLanguage = ApiSchemas["TranscriptionLanguage"];
export type PerformanceMode = ApiSchemas["PerformanceMode"];
export type LocalWhisperDevice = ApiSchemas["LocalWhisperDevice"];
export type LocalWhisperComputeType = ApiSchemas["LocalWhisperComputeType"];
export type JobStatus = ApiSchemas["JobStatus"];
export type JobStage = ApiSchemas["JobStage"];
export type Artifact = ApiSchemas["Artifact"];
export type FailureContext = ApiSchemas["FailureContext"];
export type TranscriptionWorkProgress = ApiSchemas["TranscriptionWorkProgress"];
export type JobState = WithRequired<ApiSchemas["JobPublicState"], "artifacts">;
export type JobSummary = ApiSchemas["JobSummary"];
export type NoteVersion = WithRequired<ApiSchemas["NoteVersion"], "created_at">;
export type NoteVersionIndex = Omit<ApiSchemas["NoteVersionIndex"], "selected_version_ids" | "versions"> & {
  selected_version_ids: string[];
  versions: NoteVersion[];
};
export type TranscriptCorrectionSegment = ApiSchemas["TranscriptCorrectionSegment"];
export type TranscriptCorrectionPreview = WithRequired<ApiSchemas["TranscriptCorrectionPreview"], "segments">;
export type TranscriptCorrectionRequest = ApiSchemas["TranscriptCorrectionRequest"];
export type TranscriptCorrectionApplyRequest = ApiSchemas["TranscriptCorrectionApplyRequest"];
export type SubtitleConfirmationRequest =
  ApiSchemas["Body_confirm_subtitles_api_jobs__job_id__subtitles_confirm_post"];
export type SubtitleRegenerationRequest =
  ApiSchemas["Body_regenerate_subtitles_api_jobs__job_id__subtitles_regenerate_post"];
export type NoteRegenerationRequest =
  ApiSchemas["Body_regenerate_note_version_endpoint_api_jobs__job_id__note_versions_post"];
export type NoteChunkRegenerationRequest =
  ApiSchemas["Body_regenerate_note_chunk_api_jobs__job_id__note_chunks__chunk_id__regenerate_post"];
export type UserSettings = ApiSchemas["UserSettings"];
export type QualityScores = ApiSchemas["QualityScores"];
export type QualityIssue = WithRequired<ApiSchemas["QualityIssue"], "frame_ids">;
export type ChapterQualityReport = WithRequired<ApiSchemas["ChapterQualityReport"], "issues">;
export type QualityReport = Omit<ApiSchemas["QualityReport"], "chapter_reports" | "issues"> & {
  chapter_reports: ChapterQualityReport[];
  issues: QualityIssue[];
};
export type FrameCandidate = WithRequired<ApiSchemas["FrameCandidate"], "risk_flags">;
export type FrameCandidateChapterContext = ApiSchemas["FrameCandidateChapterContext"];
export type FrameCandidateIndex = Omit<ApiSchemas["FrameCandidateIndex"], "candidates" | "chapter_contexts"> & {
  candidates: FrameCandidate[];
  chapter_contexts: FrameCandidateChapterContext[];
};
export type ReviewSubtitleSegment = ApiSchemas["ReviewSubtitleSegment"];
export type ReviewDraftParagraphStatus = ApiSchemas["ReviewDraftParagraph"]["status"];
export type ReviewDraftParagraph = WithRequired<
  ApiSchemas["ReviewDraftParagraph"],
  | "evidence_segment_ids"
  | "selected_frame_ids"
  | "subtitle_segments"
  | "unsupported_numeric_claims"
  | "unsupported_technical_identifiers"
>;
export type ReviewDraft = Omit<ApiSchemas["ReviewDraft"], "paragraphs"> & {
  paragraphs: ReviewDraftParagraph[];
};
export type ReviewAssets = Omit<
  ApiSchemas["ReviewAssets"],
  "frame_candidates" | "quality_report" | "review_draft"
> & {
  frame_candidates: FrameCandidateIndex;
  quality_report: QualityReport;
  review_draft: ReviewDraft;
};

export type RuntimePathSource = ApiSchemas["LocalModelsRuntimeStatus"]["root_source"];
export type PythonPackageInstallMode = ApiSchemas["UserSettings"]["python_package_install_mode"];
export type RuntimeCapability = ApiSchemas["RuntimeCapability"];
type FasterWhisperRuntimeStatus = WithRequired<
  ApiSchemas["FasterWhisperRuntimeStatus"],
  "cuda_dll_dirs"
>;
type LocalModelsRuntimeStatus = WithRequired<ApiSchemas["LocalModelsRuntimeStatus"], "models">;
export type RuntimeState = Omit<ApiSchemas["RuntimeState"], "faster_whisper" | "local_models"> & {
  faster_whisper: FasterWhisperRuntimeStatus;
  local_models: LocalModelsRuntimeStatus;
};
export type HealthState = Omit<ApiSchemas["HealthState"], "runtime"> & {
  runtime: RuntimeState;
};

type TaskStatus = ApiSchemas["CudaDependencyInstallState"]["status"];
export type PollableTaskState = {
  status: TaskStatus;
};
export type LocalDependencyInstallState = ApiSchemas["LocalTranscriptionDependencyInstallState"];
export type ModelDownloadState = ApiSchemas["ModelDownloadState"];
export type CudaDependencyInstallState = ApiSchemas["CudaDependencyInstallState"];

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

export type NoteChunkMeta = ApiSchemas["NoteChunkMeta"];
export type NoteChunkIndex = Omit<ApiSchemas["NoteChunkIndex"], "chunks"> & {
  chunks: NoteChunkMeta[];
};
