import { useCallback, useEffect, useRef, useState } from "react";
import type { Dispatch, SetStateAction } from "react";

import { fetchJob, updateReviewDraftParagraph } from "./api";
import type {
  FrameCandidateIndex,
  JobState,
  ReviewDraft,
  ReviewDraftParagraphStatus
} from "./types";

type UseReviewWorkflowOptions = {
  frameCandidateIndex: FrameCandidateIndex | null;
  job: JobState | null;
  loadManualReview: (versionId?: string) => Promise<boolean>;
  previewVersionId: string;
  refreshQualityReport: () => Promise<void>;
  reviewDraft: ReviewDraft | null;
  setFrameCandidateError: Dispatch<SetStateAction<string>>;
  setJob: Dispatch<SetStateAction<JobState | null>>;
  setReviewDraft: Dispatch<SetStateAction<ReviewDraft | null>>;
};

type ReviewWorkflow = {
  closeFrameReview: () => void;
  isFrameReviewOpen: boolean;
  openFrameReview: () => void;
  openManualReview: () => Promise<void>;
  resetReviewWorkflow: () => void;
  reviewDraftSavingId: string;
  saveReviewParagraph: (
    paragraphId: string,
    body: string,
    selectedFrameIds: string[],
    status: ReviewDraftParagraphStatus
  ) => Promise<void>;
};

export function useReviewWorkflow({
  frameCandidateIndex,
  job,
  loadManualReview,
  previewVersionId,
  refreshQualityReport,
  reviewDraft,
  setFrameCandidateError,
  setJob,
  setReviewDraft
}: UseReviewWorkflowOptions): ReviewWorkflow {
  const [reviewDraftSavingId, setReviewDraftSavingId] = useState("");
  const [isFrameReviewOpen, setIsFrameReviewOpen] = useState(false);
  const activeJobIdRef = useRef(job?.job_id ?? "");
  const operationEpochRef = useRef(0);
  activeJobIdRef.current = job?.job_id ?? "";

  const resetReviewWorkflow = useCallback(() => {
    operationEpochRef.current += 1;
    setReviewDraftSavingId("");
    setIsFrameReviewOpen(false);
  }, []);

  useEffect(() => {
    resetReviewWorkflow();
  }, [job?.job_id, resetReviewWorkflow]);

  function isCurrentRequest(jobId: string, epoch: number): boolean {
    return activeJobIdRef.current === jobId && operationEpochRef.current === epoch;
  }

  async function handleManualReview() {
    if (!job?.job_id) {
      return;
    }
    const requestJobId = job.job_id;
    const requestEpoch = operationEpochRef.current;
    const loaded = await loadManualReview(previewVersionId || undefined);
    if (!isCurrentRequest(requestJobId, requestEpoch)) {
      return;
    }
    if (!loaded && !(frameCandidateIndex && reviewDraft)) {
      return;
    }
    try {
      const nextJob = await fetchJob(requestJobId);
      if (!isCurrentRequest(requestJobId, requestEpoch) || nextJob.job_id !== requestJobId) {
        return;
      }
      setJob((current) => (current?.job_id === requestJobId ? nextJob : current));
      setIsFrameReviewOpen(true);
    } catch (error) {
      if (isCurrentRequest(requestJobId, requestEpoch)) {
        setFrameCandidateError(
          error instanceof Error ? error.message : "人工审核资料已准备，但任务版本刷新失败。"
        );
      }
    }
  }

  async function handleSaveReviewParagraph(
    paragraphId: string,
    body: string,
    selectedFrameIds: string[],
    status: ReviewDraftParagraphStatus
  ) {
    if (!job?.job_id) {
      return;
    }
    const requestJobId = job.job_id;
    const requestEpoch = operationEpochRef.current;
    setReviewDraftSavingId(paragraphId);
    try {
      const updatedDraft = await updateReviewDraftParagraph(
        requestJobId,
        paragraphId,
        {
          body,
          selected_frame_ids: selectedFrameIds,
          status
        },
        job,
        previewVersionId || undefined
      );
      if (!isCurrentRequest(requestJobId, requestEpoch)) {
        return;
      }
      setReviewDraft(updatedDraft);
      setFrameCandidateError("");
      await refreshQualityReport();
      const nextJob = await fetchJob(requestJobId);
      if (isCurrentRequest(requestJobId, requestEpoch)) {
        setJob((current) => (current?.job_id === requestJobId ? nextJob : current));
      }
    } catch (error) {
      if (isCurrentRequest(requestJobId, requestEpoch)) {
        setFrameCandidateError(error instanceof Error ? error.message : "人工审核稿保存失败。");
      }
      try {
        const nextJob = await fetchJob(requestJobId);
        if (isCurrentRequest(requestJobId, requestEpoch)) {
          setJob((current) => (current?.job_id === requestJobId ? nextJob : current));
        }
      } catch {
        // Keep the editable local paragraph intact when the conflict refresh also fails.
      }
    } finally {
      if (isCurrentRequest(requestJobId, requestEpoch)) {
        setReviewDraftSavingId("");
      }
    }
  }

  const openFrameReview = useCallback(() => setIsFrameReviewOpen(true), []);
  const closeFrameReview = useCallback(() => setIsFrameReviewOpen(false), []);

  return {
    closeFrameReview,
    isFrameReviewOpen,
    openFrameReview,
    openManualReview: handleManualReview,
    resetReviewWorkflow,
    reviewDraftSavingId,
    saveReviewParagraph: handleSaveReviewParagraph
  };
}
