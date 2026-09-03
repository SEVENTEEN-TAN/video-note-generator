import { useCallback, useEffect, useRef, useState } from "react";
import type { Dispatch, SetStateAction } from "react";

import {
  applyTranscriptCorrection,
  confirmSubtitles,
  createTranscriptCorrection,
  fetchJob,
  regenerateSubtitles
} from "./api";
import type {
  JobState,
  SubtitleConfirmationRequest,
  SubtitleRegenerationRequest,
  TranscriptCorrectionPreview
} from "./types";

type UseSubtitleWorkflowOptions = {
  job: JobState | null;
  noteConfig: SubtitleConfirmationRequest;
  onRefreshJobHistory: () => Promise<void>;
  setJob: Dispatch<SetStateAction<JobState | null>>;
  transcriptionConfig: SubtitleRegenerationRequest;
};

type SubtitleWorkflow = {
  applyTranscriptCorrection: () => Promise<void>;
  closeTranscriptCorrection: () => void;
  confirmSubtitles: () => Promise<void>;
  correctionError: string;
  correctionPreview: TranscriptCorrectionPreview | null;
  createTranscriptCorrection: () => Promise<void>;
  isApplyingCorrection: boolean;
  isConfirmingSubtitles: boolean;
  isCorrectingTranscript: boolean;
  isRegeneratingSubtitles: boolean;
  isTranscriptCorrectionActive: boolean;
  regenerateSubtitles: () => Promise<void>;
  resetSubtitleWorkflow: () => void;
  subtitleGateError: string;
};

export function useSubtitleWorkflow({
  job,
  noteConfig,
  onRefreshJobHistory,
  setJob,
  transcriptionConfig
}: UseSubtitleWorkflowOptions): SubtitleWorkflow {
  const [correctionPreview, setCorrectionPreview] = useState<TranscriptCorrectionPreview | null>(null);
  const [correctionError, setCorrectionError] = useState("");
  const [isCorrectingTranscript, setIsCorrectingTranscript] = useState(false);
  const [isApplyingCorrection, setIsApplyingCorrection] = useState(false);
  const [isConfirmingSubtitles, setIsConfirmingSubtitles] = useState(false);
  const [isRegeneratingSubtitles, setIsRegeneratingSubtitles] = useState(false);
  const [subtitleGateError, setSubtitleGateError] = useState("");
  const activeJobIdRef = useRef(job?.job_id ?? "");
  const operationEpochRef = useRef(0);
  activeJobIdRef.current = job?.job_id ?? "";

  const clearState = useCallback(() => {
    setCorrectionPreview(null);
    setCorrectionError("");
    setIsCorrectingTranscript(false);
    setIsApplyingCorrection(false);
    setIsConfirmingSubtitles(false);
    setIsRegeneratingSubtitles(false);
    setSubtitleGateError("");
  }, []);

  const resetSubtitleWorkflow = useCallback(() => {
    operationEpochRef.current += 1;
    clearState();
  }, [clearState]);

  useEffect(() => {
    resetSubtitleWorkflow();
  }, [job?.job_id, resetSubtitleWorkflow]);

  function isCurrentRequest(jobId: string, epoch: number): boolean {
    return activeJobIdRef.current === jobId && operationEpochRef.current === epoch;
  }

  function markJobQueued(jobId: string, step: string, progress: number, preserveProgress = true) {
    setJob((current) =>
      current?.job_id === jobId
        ? {
            ...current,
            error: null,
            progress: preserveProgress ? Math.max(current.progress, progress) : progress,
            stage: "queued",
            status: "pending",
            step
          }
        : current
    );
  }

  async function handleCreateTranscriptCorrection() {
    if (!job) {
      return;
    }
    const requestJobId = job.job_id;
    const requestEpoch = operationEpochRef.current;
    setCorrectionError("");
    if (!noteConfig.note_api_key.trim()) {
      setCorrectionError("请填写笔记 API Key，再修正字幕。");
      return;
    }
    if (!noteConfig.note_base_url.trim() || !noteConfig.note_model.trim()) {
      setCorrectionError("笔记 Base URL 和模型不能为空。");
      return;
    }
    setIsCorrectingTranscript(true);
    try {
      const preview = await createTranscriptCorrection(requestJobId, {
        instructions: noteConfig.extras,
        note_api_key: noteConfig.note_api_key,
        note_api_protocol: noteConfig.note_api_protocol,
        note_thinking_enabled: noteConfig.note_thinking_enabled,
        note_context_window_tokens: noteConfig.note_context_window_tokens,
        note_max_output_tokens: noteConfig.note_max_output_tokens,
        note_base_url: noteConfig.note_base_url,
        note_model: noteConfig.note_model
      });
      if (preview.job_id !== requestJobId) {
        throw new Error("字幕修正结果与当前任务不匹配。");
      }
      if (isCurrentRequest(requestJobId, requestEpoch)) {
        setCorrectionPreview(preview);
      }
    } catch (error) {
      if (isCurrentRequest(requestJobId, requestEpoch)) {
        setCorrectionError(error instanceof Error ? error.message : "字幕修正失败。");
      }
    } finally {
      if (isCurrentRequest(requestJobId, requestEpoch)) {
        setIsCorrectingTranscript(false);
      }
    }
  }

  async function handleApplyTranscriptCorrection() {
    if (!job || !correctionPreview) {
      return;
    }
    const requestJobId = correctionPreview.job_id;
    const requestEpoch = operationEpochRef.current;
    if (job.job_id !== requestJobId) {
      setCorrectionError("当前任务与字幕修正结果不匹配，请重新发起修正。");
      return;
    }
    setCorrectionError("");
    setIsApplyingCorrection(true);
    try {
      const queued = await applyTranscriptCorrection(requestJobId, noteConfig);
      if (queued.job_id !== requestJobId) {
        throw new Error("字幕修正任务与当前任务不匹配。");
      }
      const nextJob = await fetchJob(requestJobId);
      if (!isCurrentRequest(requestJobId, requestEpoch)) {
        return;
      }
      setCorrectionPreview(null);
      setJob((current) =>
        current?.job_id === requestJobId
          ? {
              ...nextJob,
              error: null,
              progress: Math.max(nextJob.progress, 62),
              stage: "queued",
              status: "pending",
              step: "等待重新生成笔记"
            }
          : current
      );
      await onRefreshJobHistory();
    } catch (error) {
      if (isCurrentRequest(requestJobId, requestEpoch)) {
        setCorrectionError(error instanceof Error ? error.message : "采用字幕修正失败。");
      }
    } finally {
      if (isCurrentRequest(requestJobId, requestEpoch)) {
        setIsApplyingCorrection(false);
      }
    }
  }

  async function handleConfirmSubtitles() {
    if (!job) {
      return;
    }
    const requestJobId = job.job_id;
    const requestEpoch = operationEpochRef.current;
    setSubtitleGateError("");
    if (!noteConfig.note_api_key.trim()) {
      setSubtitleGateError("请填写笔记生成 API Key，再继续生成笔记。");
      return;
    }
    if (!noteConfig.note_model.trim()) {
      setSubtitleGateError("笔记生成模型不能为空。");
      return;
    }
    setIsConfirmingSubtitles(true);
    try {
      const queued = await confirmSubtitles(requestJobId, noteConfig);
      if (queued.job_id !== requestJobId) {
        throw new Error("字幕确认任务与当前任务不匹配。");
      }
      if (isCurrentRequest(requestJobId, requestEpoch)) {
        markJobQueued(requestJobId, "等待生成笔记", 60);
      }
    } catch (error) {
      if (isCurrentRequest(requestJobId, requestEpoch)) {
        setSubtitleGateError(error instanceof Error ? error.message : "字幕确认失败，请重试。");
      }
    } finally {
      if (isCurrentRequest(requestJobId, requestEpoch)) {
        setIsConfirmingSubtitles(false);
      }
    }
  }

  async function handleRegenerateSubtitles() {
    if (!job) {
      return;
    }
    const requestJobId = job.job_id;
    const requestEpoch = operationEpochRef.current;
    const isLocal = transcriptionConfig.transcription_mode === "local_faster_whisper";
    setSubtitleGateError("");
    if (!isLocal && !transcriptionConfig.transcription_api_key.trim()) {
      setSubtitleGateError("请填写字幕转写 API Key，再重新生成字幕。");
      return;
    }
    if (!transcriptionConfig.transcription_model.trim()) {
      setSubtitleGateError("字幕转写模型不能为空。");
      return;
    }
    setIsRegeneratingSubtitles(true);
    try {
      const queued = await regenerateSubtitles(requestJobId, {
        ...transcriptionConfig,
        local_whisper_compute_type: isLocal ? transcriptionConfig.local_whisper_compute_type : "",
        local_whisper_device: isLocal ? transcriptionConfig.local_whisper_device : "",
        transcription_api_key: isLocal ? "" : transcriptionConfig.transcription_api_key,
        transcription_base_url: isLocal ? "" : transcriptionConfig.transcription_base_url
      });
      if (queued.job_id !== requestJobId) {
        throw new Error("字幕重生成任务与当前任务不匹配。");
      }
      if (isCurrentRequest(requestJobId, requestEpoch)) {
        markJobQueued(requestJobId, "等待重新生成字幕", 20, false);
      }
    } catch (error) {
      if (isCurrentRequest(requestJobId, requestEpoch)) {
        setSubtitleGateError(error instanceof Error ? error.message : "重新生成字幕失败，请重试。");
      }
    } finally {
      if (isCurrentRequest(requestJobId, requestEpoch)) {
        setIsRegeneratingSubtitles(false);
      }
    }
  }

  const closeTranscriptCorrection = useCallback(() => {
    if (!isApplyingCorrection) {
      setCorrectionPreview(null);
      setCorrectionError("");
    }
  }, [isApplyingCorrection]);

  return {
    applyTranscriptCorrection: handleApplyTranscriptCorrection,
    closeTranscriptCorrection,
    confirmSubtitles: handleConfirmSubtitles,
    correctionError,
    correctionPreview,
    createTranscriptCorrection: handleCreateTranscriptCorrection,
    isApplyingCorrection,
    isConfirmingSubtitles,
    isCorrectingTranscript,
    isRegeneratingSubtitles,
    isTranscriptCorrectionActive:
      isCorrectingTranscript || isApplyingCorrection || Boolean(correctionPreview),
    regenerateSubtitles: handleRegenerateSubtitles,
    resetSubtitleWorkflow,
    subtitleGateError
  };
}
