import type { JobState, JobSummary, NoteVersionIndex, QualityReport } from "./types";

export async function fetchJob(jobId: string): Promise<JobState> {
  const response = await fetch(`/api/jobs/${jobId}`);
  if (!response.ok) {
    throw new Error(await readResponseError(response, "任务状态读取失败。"));
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

export async function fetchNoteVersions(jobId: string): Promise<NoteVersionIndex> {
  const response = await fetch(`/api/jobs/${jobId}/note-versions`);
  if (!response.ok) {
    throw new Error("笔记版本读取失败。");
  }
  return response.json();
}

export async function fetchQualityReport(jobId: string): Promise<QualityReport> {
  const response = await fetch(`/api/jobs/${jobId}/quality-report`);
  if (!response.ok) {
    throw new Error(await readResponseError(response, "质量报告读取失败。"));
  }
  return response.json();
}
