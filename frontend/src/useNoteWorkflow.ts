import { useCallback, useEffect, useRef, useState } from "react";
import type { ChangeEvent, Dispatch, SetStateAction } from "react";

import {
  fetchJob,
  finalizeJob,
  regenerateNoteChunk,
  regenerateNoteVersion,
  updateNoteVersionSelection
} from "./api";
import type {
  JobState,
  NoteChunkIndex,
  NoteRegenerationRequest,
  NoteVersionIndex
} from "./types";

type UseNoteWorkflowOptions = {
  job: JobState | null;
  noteChunks: NoteChunkIndex | null;
  noteConfig: NoteRegenerationRequest;
  noteVersions: NoteVersionIndex | null;
  onRefreshJobHistory: () => Promise<void>;
  previewVersionId: string;
  setJob: Dispatch<SetStateAction<JobState | null>>;
  setNoteVersions: Dispatch<SetStateAction<NoteVersionIndex | null>>;
  setPreviewVersionId: Dispatch<SetStateAction<string>>;
};

type NoteWorkflow = {
  finalizeError: string;
  finalizeJob: () => Promise<void>;
  isFinalizingJob: boolean;
  isRegenerating: boolean;
  isSwitchingVersion: boolean;
  onNoteVersionChange: (event: ChangeEvent<HTMLSelectElement>) => Promise<void>;
  regenerateNote: () => Promise<void>;
  regenerateNoteChunk: (chunkId: string) => Promise<void>;
  regeneratingChunkId: string;
  resetNoteWorkflow: () => void;
  versionError: string;
};

export function useNoteWorkflow({
  job,
  noteChunks,
  noteConfig,
  noteVersions,
  onRefreshJobHistory,
  previewVersionId,
  setJob,
  setNoteVersions,
  setPreviewVersionId
}: UseNoteWorkflowOptions): NoteWorkflow {
  const [versionError, setVersionError] = useState("");
  const [isRegenerating, setIsRegenerating] = useState(false);
  const [regeneratingChunkId, setRegeneratingChunkId] = useState("");
  const [isFinalizingJob, setIsFinalizingJob] = useState(false);
  const [isSwitchingVersion, setIsSwitchingVersion] = useState(false);
  const [finalizeError, setFinalizeError] = useState("");
  const activeJobIdRef = useRef(job?.job_id ?? "");
  const operationEpochRef = useRef(0);
  const versionSwitchControllerRef = useRef<AbortController | null>(null);
  const versionSwitchRequestRef = useRef(0);
  activeJobIdRef.current = job?.job_id ?? "";

  const clearState = useCallback(() => {
    setVersionError("");
    setIsRegenerating(false);
    setRegeneratingChunkId("");
    setIsFinalizingJob(false);
    setIsSwitchingVersion(false);
    setFinalizeError("");
  }, []);

  const resetNoteWorkflow = useCallback(() => {
    operationEpochRef.current += 1;
    versionSwitchRequestRef.current += 1;
    versionSwitchControllerRef.current?.abort();
    versionSwitchControllerRef.current = null;
    clearState();
  }, [clearState]);

  useEffect(() => {
    resetNoteWorkflow();
  }, [job?.job_id, resetNoteWorkflow]);

  useEffect(
    () => () => {
      versionSwitchControllerRef.current?.abort();
    },
    []
  );

  useEffect(() => {
    if (
      job?.status === "awaiting_note_review" ||
      job?.status === "succeeded" ||
      job?.status === "failed" ||
      job?.status === "cancelled"
    ) {
      setIsRegenerating(false);
      setRegeneratingChunkId("");
    }
    if (job?.status === "succeeded" || job?.status === "failed" || job?.status === "cancelled") {
      setIsFinalizingJob(false);
    }
  }, [job?.status]);

  function isCurrentRequest(jobId: string, epoch: number): boolean {
    return activeJobIdRef.current === jobId && operationEpochRef.current === epoch;
  }

  function markJobQueued(jobId: string, step: string, progress: number, preserveProgress: boolean) {
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

  function validateNoteConfig(message: string): boolean {
    setVersionError("");
    if (!noteConfig.note_api_key.trim()) {
      setVersionError(`请填写笔记 API Key，再${message}。`);
      return false;
    }
    if (!noteConfig.note_base_url.trim() || !noteConfig.note_model.trim()) {
      setVersionError("笔记 Base URL 和模型不能为空。");
      return false;
    }
    return true;
  }

  async function handleRegenerateNote() {
    if (!job || !validateNoteConfig("重新生成笔记")) {
      return;
    }
    const requestJobId = job.job_id;
    const requestEpoch = operationEpochRef.current;
    setIsRegenerating(true);
    try {
      const queued = await regenerateNoteVersion(requestJobId, noteConfig);
      if (queued.job_id !== requestJobId) {
        throw new Error("笔记重生成任务与当前任务不匹配。");
      }
      if (isCurrentRequest(requestJobId, requestEpoch)) {
        markJobQueued(requestJobId, "等待重新生成笔记", 62, true);
      }
    } catch (error) {
      if (isCurrentRequest(requestJobId, requestEpoch)) {
        setVersionError(error instanceof Error ? error.message : "重新生成笔记失败。");
        setIsRegenerating(false);
      }
    }
  }

  async function handleRegenerateNoteChunk(chunkId: string) {
    if (!job || !noteChunks || !validateNoteConfig("重新生成笔记块")) {
      return;
    }
    const requestJobId = job.job_id;
    const requestEpoch = operationEpochRef.current;
    setRegeneratingChunkId(chunkId);
    try {
      const queued = await regenerateNoteChunk(requestJobId, chunkId, noteConfig);
      if (queued.job_id !== requestJobId) {
        throw new Error("笔记块重生成任务与当前任务不匹配。");
      }
      if (isCurrentRequest(requestJobId, requestEpoch)) {
        markJobQueued(requestJobId, "等待重新生成笔记块", 70, false);
      }
    } catch (error) {
      if (isCurrentRequest(requestJobId, requestEpoch)) {
        setVersionError(error instanceof Error ? error.message : "重新生成笔记块失败。");
        setRegeneratingChunkId("");
      }
    }
  }

  async function handleFinalizeJob() {
    if (!job?.job_id) {
      return;
    }
    const requestJobId = job.job_id;
    const requestEpoch = operationEpochRef.current;
    setIsFinalizingJob(true);
    setFinalizeError("");
    try {
      const nextJob = await finalizeJob(requestJobId, job, previewVersionId || undefined);
      if (isCurrentRequest(requestJobId, requestEpoch)) {
        setJob((current) => (current?.job_id === requestJobId ? nextJob : current));
      }
      await onRefreshJobHistory();
    } catch (error) {
      if (isCurrentRequest(requestJobId, requestEpoch)) {
        setFinalizeError(error instanceof Error ? error.message : "确认定稿失败。");
      }
      try {
        const nextJob = await fetchJob(requestJobId);
        if (isCurrentRequest(requestJobId, requestEpoch)) {
          setJob((current) => (current?.job_id === requestJobId ? nextJob : current));
        }
      } catch {
        // Keep the last usable task state when the conflict refresh also fails.
      }
    } finally {
      if (isCurrentRequest(requestJobId, requestEpoch)) {
        setIsFinalizingJob(false);
      }
    }
  }

  async function handleNoteVersionChange(event: ChangeEvent<HTMLSelectElement>) {
    if (!job || !noteVersions || isSwitchingVersion) {
      return;
    }
    const requestedJobId = job.job_id;
    const requestEpoch = operationEpochRef.current;
    const nextVersionId = event.target.value;
    const previousVersionId = previewVersionId;
    const requestId = versionSwitchRequestRef.current + 1;
    versionSwitchRequestRef.current = requestId;
    versionSwitchControllerRef.current?.abort();
    const controller = new AbortController();
    versionSwitchControllerRef.current = controller;
    setPreviewVersionId(nextVersionId);
    setVersionError("");
    setIsSwitchingVersion(true);
    let selectionCommitted = false;

    const isCurrentVersionRequest = () =>
      isCurrentRequest(requestedJobId, requestEpoch) && requestId === versionSwitchRequestRef.current;

    try {
      const payload = await updateNoteVersionSelection(
        requestedJobId,
        {
          active_version_id: nextVersionId,
          selected_version_ids: noteVersions.selected_version_ids.length
            ? noteVersions.selected_version_ids
            : noteVersions.versions.map((version) => version.id)
        },
        job,
        controller.signal
      );
      if (!isCurrentVersionRequest()) {
        return;
      }
      selectionCommitted = true;
      setNoteVersions(payload);
      setPreviewVersionId(payload.active_version_id ?? nextVersionId);
      try {
        const nextJob = await fetchJob(requestedJobId, controller.signal);
        if (isCurrentVersionRequest()) {
          setJob((current) => (current?.job_id === requestedJobId ? nextJob : current));
        }
      } catch (error) {
        if (isCurrentVersionRequest() && !isAbortError(error)) {
          setVersionError("版本已切换，但任务产物状态刷新失败；重新载入任务即可同步。");
        }
      }
      await onRefreshJobHistory();
    } catch (error) {
      if (isCurrentVersionRequest() && !isAbortError(error)) {
        if (!selectionCommitted) {
          setPreviewVersionId(previousVersionId);
        }
        setVersionError(error instanceof Error ? error.message : "笔记版本切换失败。");
        try {
          const nextJob = await fetchJob(requestedJobId, controller.signal);
          if (isCurrentVersionRequest()) {
            setJob((current) => (current?.job_id === requestedJobId ? nextJob : current));
          }
        } catch {
          // Preserve the last usable state when both the mutation and refresh fail.
        }
      }
    } finally {
      if (isCurrentVersionRequest()) {
        versionSwitchControllerRef.current = null;
        setIsSwitchingVersion(false);
      }
    }
  }

  return {
    finalizeError,
    finalizeJob: handleFinalizeJob,
    isFinalizingJob,
    isRegenerating,
    isSwitchingVersion,
    onNoteVersionChange: handleNoteVersionChange,
    regenerateNote: handleRegenerateNote,
    regenerateNoteChunk: handleRegenerateNoteChunk,
    regeneratingChunkId,
    resetNoteWorkflow,
    versionError
  };
}

function isAbortError(error: unknown): boolean {
  return error instanceof Error && error.name === "AbortError";
}
