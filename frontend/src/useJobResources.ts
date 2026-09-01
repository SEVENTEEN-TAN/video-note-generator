import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { Dispatch, SetStateAction } from "react";

import {
  fetchFrameCandidates,
  fetchNoteChunks,
  fetchNotePreview,
  fetchNoteVersions,
  fetchQualityReport,
  fetchSubtitlePreview,
  prepareReviewAssets
} from "./api";
import type {
  FrameCandidateIndex,
  JobState,
  NoteChunkIndex,
  NoteVersionIndex,
  QualityReport,
  ReviewDraft
} from "./types";

type JobResources = {
  frameCandidateError: string;
  frameCandidateIndex: FrameCandidateIndex | null;
  loadManualReview: (versionId?: string) => Promise<boolean>;
  noteChunks: NoteChunkIndex | null;
  notePreview: string;
  noteVersions: NoteVersionIndex | null;
  previewVersionId: string;
  qualityReport: QualityReport | null;
  qualityReportError: string;
  refreshQualityReport: () => Promise<void>;
  resetJobResources: () => void;
  reviewDraft: ReviewDraft | null;
  setFrameCandidateError: Dispatch<SetStateAction<string>>;
  setNoteVersions: Dispatch<SetStateAction<NoteVersionIndex | null>>;
  setPreviewVersionId: Dispatch<SetStateAction<string>>;
  setReviewDraft: Dispatch<SetStateAction<ReviewDraft | null>>;
  subtitlePreview: string;
};

export function useJobResources(job: JobState | null): JobResources {
  const [notePreview, setNotePreview] = useState("");
  const [subtitlePreview, setSubtitlePreview] = useState("");
  const [noteVersions, setNoteVersions] = useState<NoteVersionIndex | null>(null);
  const [previewVersionId, setPreviewVersionId] = useState("");
  const [noteChunks, setNoteChunks] = useState<NoteChunkIndex | null>(null);
  const [qualityReport, setQualityReport] = useState<QualityReport | null>(null);
  const [qualityReportError, setQualityReportError] = useState("");
  const [frameCandidateIndex, setFrameCandidateIndex] = useState<FrameCandidateIndex | null>(null);
  const [frameCandidateError, setFrameCandidateError] = useState("");
  const [reviewDraft, setReviewDraft] = useState<ReviewDraft | null>(null);

  const jobId = job?.job_id ?? "";
  const artifactRevision = job?.artifact_revision ?? "";
  const hasNote = Boolean(job?.artifacts.some((artifact) => artifact.path === "note.md"));
  const hasSubtitles = Boolean(job?.artifacts.some((artifact) => artifact.path === "subtitles.md"));
  const canLoadChunks = job?.status === "succeeded" || job?.status === "awaiting_note_review";
  const canLoadReviewResources = job?.status === "succeeded" || job?.status === "awaiting_note_review";
  const activeJobIdRef = useRef(jobId);
  const manualReviewControllerRef = useRef<AbortController | null>(null);
  activeJobIdRef.current = jobId;

  const resetJobResources = useCallback(() => {
    setNotePreview("");
    setSubtitlePreview("");
    setNoteVersions(null);
    setPreviewVersionId("");
    setNoteChunks(null);
    setQualityReport(null);
    setQualityReportError("");
    setFrameCandidateIndex(null);
    setFrameCandidateError("");
    setReviewDraft(null);
  }, []);

  useEffect(() => {
    manualReviewControllerRef.current?.abort();
    manualReviewControllerRef.current = null;
    resetJobResources();
    return () => {
      manualReviewControllerRef.current?.abort();
      manualReviewControllerRef.current = null;
    };
  }, [jobId, resetJobResources]);

  useEffect(() => {
    if (!jobId || !hasNote) {
      setNoteVersions(null);
      setPreviewVersionId("");
      return;
    }
    const requestedJobId = jobId;
    const controller = new AbortController();
    fetchNoteVersions(jobId, controller.signal)
      .then((index) => {
        if (activeJobIdRef.current !== requestedJobId) {
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
      .catch((error: unknown) => {
        if (!isAbortError(error)) {
          setNoteVersions(null);
        }
      });
    return () => controller.abort();
  }, [artifactRevision, hasNote, jobId]);

  useEffect(() => {
    if (!jobId || !hasSubtitles) {
      setSubtitlePreview("");
      return;
    }
    const requestedJobId = jobId;
    const controller = new AbortController();
    fetchSubtitlePreview(jobId, controller.signal)
      .then((preview) => {
        if (activeJobIdRef.current === requestedJobId) {
          setSubtitlePreview(preview);
        }
      })
      .catch((error: unknown) => {
        if (!isAbortError(error)) {
          setSubtitlePreview("");
        }
      });
    return () => controller.abort();
  }, [artifactRevision, hasSubtitles, jobId]);

  useEffect(() => {
    if (!jobId || !hasNote) {
      setNotePreview("");
      return;
    }
    const requestedJobId = jobId;
    const controller = new AbortController();
    fetchNotePreview(jobId, previewVersionId || undefined, controller.signal)
      .then((preview) => {
        if (activeJobIdRef.current === requestedJobId) {
          setNotePreview(preview);
        }
      })
      .catch((error: unknown) => {
        if (!isAbortError(error)) {
          setNotePreview("");
        }
      });
    return () => controller.abort();
  }, [artifactRevision, hasNote, jobId, previewVersionId]);

  const refreshQualityReport = useCallback(async () => {
    if (!jobId || !hasNote || !canLoadReviewResources) {
      setQualityReport(null);
      setQualityReportError("");
      return;
    }
    const requestedJobId = jobId;
    try {
      const assets = await prepareReviewAssets(requestedJobId, previewVersionId || undefined);
      if (activeJobIdRef.current !== requestedJobId) {
        return;
      }
      setFrameCandidateIndex(assets.frame_candidates);
      setQualityReport(assets.quality_report);
      setReviewDraft(assets.review_draft);
      setFrameCandidateError("");
      setQualityReportError("");
    } catch (error) {
      if (activeJobIdRef.current !== requestedJobId || isAbortError(error)) {
        return;
      }
      setQualityReport(null);
      setQualityReportError(error instanceof Error ? error.message : "质量报告读取失败。");
    }
  }, [canLoadReviewResources, hasNote, jobId, previewVersionId]);

  useEffect(() => {
    if (!jobId || !hasNote || !canLoadReviewResources) {
      setQualityReport(null);
      setQualityReportError("");
      return;
    }
    const requestedJobId = jobId;
    const controller = new AbortController();
    fetchQualityReport(jobId, controller.signal)
      .then((report) => {
        if (activeJobIdRef.current !== requestedJobId) {
          return;
        }
        setQualityReport(report);
        setQualityReportError("");
      })
      .catch((error: unknown) => {
        if (!isAbortError(error)) {
          setQualityReport(null);
          setQualityReportError(error instanceof Error ? error.message : "质量报告读取失败。");
        }
      });
    return () => controller.abort();
  }, [artifactRevision, canLoadReviewResources, hasNote, jobId]);

  useEffect(() => {
    if (!jobId || !hasNote || !canLoadReviewResources) {
      setFrameCandidateIndex(null);
      setFrameCandidateError("");
      return;
    }
    const requestedJobId = jobId;
    const controller = new AbortController();
    fetchFrameCandidates(jobId, controller.signal)
      .then((index) => {
        if (activeJobIdRef.current !== requestedJobId) {
          return;
        }
        setFrameCandidateIndex(index);
        setFrameCandidateError("");
      })
      .catch((error: unknown) => {
        if (!isAbortError(error)) {
          setFrameCandidateIndex(null);
          setFrameCandidateError(error instanceof Error ? error.message : "配图候选读取失败。");
        }
      });
    return () => controller.abort();
  }, [artifactRevision, canLoadReviewResources, hasNote, jobId]);

  useEffect(() => {
    if (!jobId || !canLoadChunks) {
      setNoteChunks(null);
      return;
    }
    const requestedJobId = jobId;
    const controller = new AbortController();
    fetchNoteChunks(jobId, controller.signal)
      .then((chunks) => {
        if (activeJobIdRef.current === requestedJobId) {
          setNoteChunks(chunks);
        }
      })
      .catch((error: unknown) => {
        if (!isAbortError(error)) {
          setNoteChunks(null);
        }
      });
    return () => controller.abort();
  }, [artifactRevision, canLoadChunks, jobId]);

  const loadManualReview = useCallback(
    async (versionId?: string) => {
      if (!jobId) {
        return false;
      }
      const requestedJobId = jobId;
      manualReviewControllerRef.current?.abort();
      const controller = new AbortController();
      manualReviewControllerRef.current = controller;
      try {
        const assets = await prepareReviewAssets(requestedJobId, versionId, controller.signal);
        if (activeJobIdRef.current !== requestedJobId) {
          return false;
        }
        setFrameCandidateIndex(assets.frame_candidates);
        setQualityReport(assets.quality_report);
        setReviewDraft(assets.review_draft);
        setQualityReportError("");
        setFrameCandidateError("");
        return true;
      } catch (error) {
        if (activeJobIdRef.current !== requestedJobId || isAbortError(error)) {
          return false;
        }
        setFrameCandidateError(error instanceof Error ? error.message : "人工审核数据读取失败。");
        return false;
      } finally {
        if (manualReviewControllerRef.current === controller) {
          manualReviewControllerRef.current = null;
        }
      }
    },
    [jobId]
  );

  return useMemo(
    () => ({
      frameCandidateError,
      frameCandidateIndex,
      loadManualReview,
      noteChunks,
      notePreview,
      noteVersions,
      previewVersionId,
      qualityReport,
      qualityReportError,
      refreshQualityReport,
      resetJobResources,
      reviewDraft,
      setFrameCandidateError,
      setNoteVersions,
      setPreviewVersionId,
      setReviewDraft,
      subtitlePreview
    }),
    [
      frameCandidateError,
      frameCandidateIndex,
      loadManualReview,
      noteChunks,
      notePreview,
      noteVersions,
      previewVersionId,
      qualityReport,
      qualityReportError,
      refreshQualityReport,
      resetJobResources,
      reviewDraft,
      subtitlePreview
    ]
  );
}

function isAbortError(error: unknown): boolean {
  return error instanceof Error && error.name === "AbortError";
}
