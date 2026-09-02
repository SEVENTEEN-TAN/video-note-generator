import type {
  AIModelListRequest,
  AIModelListResponse,
  CudaDependencyInstallState,
  FrameCandidateIndex,
  HealthState,
  JobState,
  JobSummary,
  LocalDependencyInstallState,
  ModelDownloadState,
  NoteChunkIndex,
  NoteChunkRegenerationRequest,
  NoteRegenerationRequest,
  NoteVersionIndex,
  QualityReport,
  ReviewAssets,
  ReviewDraft,
  ReviewDraftParagraphStatus,
  SubtitleConfirmationRequest,
  SubtitleRegenerationRequest,
  TranscriptCorrectionApplyRequest,
  TranscriptCorrectionPreview,
  TranscriptCorrectionRequest,
  UserSettings
} from "./types";

export type JobRevisionGuard = Pick<JobState, "artifact_revision" | "state_revision">;

export async function fetchAIModels(payload: AIModelListRequest, signal?: AbortSignal): Promise<AIModelListResponse> {
  return requestJson("/api/ai/models", "服务器模型列表获取失败。", {
    body: JSON.stringify(payload),
    headers: { "Content-Type": "application/json" },
    method: "POST",
    signal
  });
}

function mutationQuery(
  revision: JobRevisionGuard,
  versionId?: string
) {
  const query = new URLSearchParams({
    expected_artifact_revision: revision.artifact_revision,
    expected_state_revision: String(revision.state_revision)
  });
  if (versionId) {
    query.set("version_id", versionId);
  }
  return `?${query.toString()}`;
}

export async function fetchJob(jobId: string, signal?: AbortSignal): Promise<JobState> {
  const response = await fetch(`/api/jobs/${jobId}`, { signal });
  if (!response.ok) {
    throw new Error(await readResponseError(response, "任务状态读取失败。"));
  }
  return response.json();
}

export async function createJob(formData: FormData): Promise<{ job_id: string }> {
  return requestJson("/api/jobs", "任务创建失败。", { body: formData, method: "POST" });
}

export async function fetchHealthState(signal?: AbortSignal): Promise<HealthState> {
  return requestJson("/api/health", "运行环境状态读取失败。", { signal });
}

export async function startModelDownload(modelName: string): Promise<ModelDownloadState> {
  return requestJson("/api/models/faster-whisper/download", "模型下载启动失败。", {
    body: JSON.stringify({ model_name: modelName }),
    headers: { "Content-Type": "application/json" },
    method: "POST"
  });
}

export async function fetchModelDownload(modelName: string): Promise<ModelDownloadState> {
  return requestJson(
    `/api/models/faster-whisper/download/${encodeURIComponent(modelName)}`,
    "模型下载状态读取失败。"
  );
}

export async function startLocalDependencyInstall(): Promise<LocalDependencyInstallState> {
  return requestJson("/api/runtime/local-dependencies/install", "本地转写依赖安装启动失败。", {
    method: "POST"
  });
}

export async function fetchLocalDependencyInstall(): Promise<LocalDependencyInstallState> {
  return requestJson("/api/runtime/local-dependencies/install", "本地转写依赖安装状态读取失败。");
}

export async function startCudaDependencyInstall(): Promise<CudaDependencyInstallState> {
  return requestJson("/api/runtime/cuda-dependencies/install", "CUDA 依赖安装启动失败。", {
    method: "POST"
  });
}

export async function fetchCudaDependencyInstall(): Promise<CudaDependencyInstallState> {
  return requestJson("/api/runtime/cuda-dependencies/install", "CUDA 依赖安装状态读取失败。");
}

export async function fetchUserSettings(): Promise<UserSettings> {
  return requestJson("/api/settings", "设置读取失败。");
}

export async function saveUserSettings(settings: UserSettings): Promise<UserSettings> {
  return requestJson("/api/settings", "设置保存失败。", {
    body: JSON.stringify(settings),
    headers: { "Content-Type": "application/json" },
    method: "PATCH"
  });
}

export async function clearUserSettings(): Promise<UserSettings> {
  return requestJson("/api/settings", "设置清除失败。", { method: "DELETE" });
}

export async function updateNoteVersionSelection(
  jobId: string,
  payload: {
    active_version_id?: string | null;
    selected_version_ids: string[];
  },
  revision: JobRevisionGuard,
  signal?: AbortSignal
): Promise<NoteVersionIndex> {
  const response = await fetch(`/api/jobs/${jobId}/note-versions${mutationQuery(revision)}`, {
    body: JSON.stringify(payload),
    headers: { "Content-Type": "application/json" },
    method: "PATCH",
    signal
  });
  if (!response.ok) {
    throw new Error(await readResponseError(response, "笔记版本切换失败。"));
  }
  return response.json();
}

export async function fetchJobHistory(): Promise<{ jobs: JobSummary[] }> {
  const response = await fetch("/api/jobs");
  if (!response.ok) {
    throw new Error(await readResponseError(response, "历史任务读取失败。"));
  }
  return response.json();
}

export async function cancelJob(jobId: string): Promise<JobState> {
  return requestJson(`/api/jobs/${jobId}/cancel`, "取消任务失败。", { method: "POST" });
}

export async function resumeJobTranscription(jobId: string): Promise<void> {
  await requestJson(`/api/jobs/${jobId}/transcription/resume`, "继续转写失败。", { method: "POST" });
}

export async function deleteJob(jobId: string): Promise<void> {
  await requestJson(`/api/jobs/${encodeURIComponent(jobId)}`, "历史任务删除失败。", { method: "DELETE" });
}

type QueuedJobResponse = {
  job_id: string;
  status: string;
};

export async function confirmSubtitles(
  jobId: string,
  payload: SubtitleConfirmationRequest
): Promise<QueuedJobResponse> {
  return postForm(`/api/jobs/${jobId}/subtitles/confirm`, payload, "字幕确认失败，请重试。");
}

export async function regenerateSubtitles(
  jobId: string,
  payload: SubtitleRegenerationRequest
): Promise<QueuedJobResponse> {
  return postForm(`/api/jobs/${jobId}/subtitles/regenerate`, payload, "重新生成字幕失败，请重试。");
}

export async function createTranscriptCorrection(
  jobId: string,
  payload: TranscriptCorrectionRequest
): Promise<TranscriptCorrectionPreview> {
  const response = await fetch(`/api/jobs/${jobId}/transcript-corrections`, {
    body: JSON.stringify(payload),
    headers: { "Content-Type": "application/json" },
    method: "POST"
  });
  if (!response.ok) {
    throw new Error(await readResponseError(response, "字幕修正失败。"));
  }
  return response.json();
}

export async function applyTranscriptCorrection(
  jobId: string,
  payload: TranscriptCorrectionApplyRequest
): Promise<QueuedJobResponse> {
  const response = await fetch(`/api/jobs/${jobId}/transcript-corrections/apply`, {
    body: JSON.stringify(payload),
    headers: { "Content-Type": "application/json" },
    method: "POST"
  });
  if (!response.ok) {
    throw new Error(await readResponseError(response, "采用字幕修正失败。"));
  }
  return response.json();
}

export async function regenerateNoteVersion(
  jobId: string,
  payload: NoteRegenerationRequest
): Promise<QueuedJobResponse> {
  return postForm(`/api/jobs/${jobId}/note-versions`, payload, "重新生成笔记失败。");
}

export async function regenerateNoteChunk(
  jobId: string,
  chunkId: string,
  payload: NoteChunkRegenerationRequest
): Promise<QueuedJobResponse> {
  return postForm(
    `/api/jobs/${jobId}/note-chunks/${encodeURIComponent(chunkId)}/regenerate`,
    payload,
    "重新生成笔记块失败。"
  );
}

async function postForm<T extends Record<string, string | number>>(
  url: string,
  payload: T,
  fallback: string
): Promise<QueuedJobResponse> {
  const formData = new FormData();
  for (const [key, value] of Object.entries(payload)) {
    formData.append(key, String(value));
  }
  const response = await fetch(url, { body: formData, method: "POST" });
  if (!response.ok) {
    throw new Error(await readResponseError(response, fallback));
  }
  return response.json();
}

export async function readResponseError(response: Response, fallback: string): Promise<string> {
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

async function requestJson<T>(url: string, fallback: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, init);
  if (!response.ok) {
    throw new Error(await readResponseError(response, fallback));
  }
  return response.json();
}

export function isDesktopDownloadAvailable() {
  return typeof window !== "undefined" && typeof window.pywebview?.api?.save_file === "function";
}

export function buildAbsoluteUrl(path: string) {
  return new URL(path, window.location.origin).toString();
}

export function deriveDownloadFilename(path: string, fallbackLabel: string) {
  const lastSegment = path.split("/").filter(Boolean).at(-1);
  return lastSegment || fallbackLabel;
}

export async function triggerBrowserDownload(url: string, filename: string) {
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

export async function downloadArtifact(url: string, filename: string) {
  if (isDesktopDownloadAvailable()) {
    return window.pywebview!.api!.save_file!(filename, buildAbsoluteUrl(url));
  }
  await triggerBrowserDownload(url, filename);
  return { ok: true };
}

export async function fetchNoteVersions(jobId: string, signal?: AbortSignal): Promise<NoteVersionIndex> {
  const response = await fetch(`/api/jobs/${jobId}/note-versions`, { signal });
  if (!response.ok) {
    throw new Error("笔记版本读取失败。");
  }
  return response.json();
}

export async function fetchQualityReport(jobId: string, signal?: AbortSignal): Promise<QualityReport> {
  const response = await fetch(`/api/jobs/${jobId}/quality-report`, { signal });
  if (!response.ok) {
    throw new Error(await readResponseError(response, "质量报告读取失败。"));
  }
  return response.json();
}

export async function fetchFrameCandidates(jobId: string, signal?: AbortSignal): Promise<FrameCandidateIndex> {
  const response = await fetch(`/api/jobs/${jobId}/frame-candidates`, { signal });
  if (!response.ok) {
    throw new Error(await readResponseError(response, "配图候选读取失败。"));
  }
  return response.json();
}

export async function selectFrameCandidate(
  jobId: string,
  candidateId: string,
  revision: JobRevisionGuard
): Promise<FrameCandidateIndex> {
  const response = await fetch(
    `/api/jobs/${jobId}/frame-candidates/${candidateId}/select${mutationQuery(revision)}`,
    { method: "POST" }
  );
  if (!response.ok) {
    throw new Error(await readResponseError(response, "配图候选选择失败。"));
  }
  return response.json();
}

export async function rejectFrameCandidate(
  jobId: string,
  candidateId: string,
  revision: JobRevisionGuard
): Promise<FrameCandidateIndex> {
  const response = await fetch(
    `/api/jobs/${jobId}/frame-candidates/${candidateId}/reject${mutationQuery(revision)}`,
    { method: "POST" }
  );
  if (!response.ok) {
    throw new Error(await readResponseError(response, "配图候选拒绝失败。"));
  }
  return response.json();
}

export async function fetchReviewDraft(
  jobId: string,
  versionId?: string,
  signal?: AbortSignal
): Promise<ReviewDraft> {
  const query = versionId ? `?version_id=${encodeURIComponent(versionId)}` : "";
  const response = await fetch(`/api/jobs/${jobId}/review-draft${query}`, { signal });
  if (!response.ok) {
    throw new Error(await readResponseError(response, "人工审核稿读取失败。"));
  }
  return response.json();
}

export async function prepareReviewAssets(
  jobId: string,
  versionId?: string,
  signal?: AbortSignal
): Promise<ReviewAssets> {
  const query = versionId ? `?version_id=${encodeURIComponent(versionId)}` : "";
  const response = await fetch(`/api/jobs/${jobId}/review-assets/prepare${query}`, {
    method: "POST",
    signal
  });
  if (!response.ok) {
    throw new Error(await readResponseError(response, "人工审核资料准备失败。"));
  }
  return response.json();
}

export async function updateReviewDraftParagraph(
  jobId: string,
  paragraphId: string,
  payload: {
    body: string;
    selected_frame_ids: string[];
    status: ReviewDraftParagraphStatus;
  },
  revision: JobRevisionGuard,
  versionId?: string
): Promise<ReviewDraft> {
  const query = mutationQuery(revision, versionId);
  const response = await fetch(`/api/jobs/${jobId}/review-draft/paragraphs/${paragraphId}${query}`, {
    body: JSON.stringify(payload),
    headers: { "Content-Type": "application/json" },
    method: "PATCH"
  });
  if (!response.ok) {
    throw new Error(await readResponseError(response, "人工审核稿保存失败。"));
  }
  return response.json();
}

export async function finalizeJob(
  jobId: string,
  revision: JobRevisionGuard,
  versionId?: string
): Promise<JobState> {
  const query = mutationQuery(revision, versionId);
  const response = await fetch(`/api/jobs/${jobId}/finalize${query}`, { method: "POST" });
  if (!response.ok) {
    throw new Error(await readResponseError(response, "确认定稿失败。"));
  }
  return response.json();
}

export async function fetchNotePreview(
  jobId: string,
  versionId?: string,
  signal?: AbortSignal
): Promise<string> {
  const path = versionId
    ? `/api/jobs/${jobId}/preview/note/${encodeURIComponent(versionId)}`
    : `/api/jobs/${jobId}/preview/note`;
  const response = await fetch(path, { signal });
  if (!response.ok) {
    throw new Error(await readResponseError(response, "笔记预览读取失败。"));
  }
  return response.text();
}

export async function fetchSubtitlePreview(jobId: string, signal?: AbortSignal): Promise<string> {
  const response = await fetch(`/api/jobs/${jobId}/preview/subtitles`, { signal });
  if (!response.ok) {
    throw new Error(await readResponseError(response, "字幕预览读取失败。"));
  }
  return response.text();
}

export async function fetchNoteChunks(jobId: string, signal?: AbortSignal): Promise<NoteChunkIndex | null> {
  const response = await fetch(`/api/jobs/${jobId}/note-chunks`, { signal });
  if (!response.ok) {
    return null;
  }
  return response.json();
}
