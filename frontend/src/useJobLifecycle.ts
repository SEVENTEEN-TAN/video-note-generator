import { useCallback, useEffect, useRef, useState } from "react";
import type { Dispatch, SetStateAction } from "react";

import { cancelJob, deleteJob, fetchJob, fetchJobHistory, resumeJobTranscription } from "./api";
import type { JobState, JobSummary } from "./types";

type UseJobLifecycleOptions = {
  onClearSelectedInputs: () => void;
  onResetTaskContext: () => void;
};

type JobLifecycle = {
  cancelActiveJob: () => Promise<void>;
  deleteHistoryJob: (jobId: string) => Promise<void>;
  historyError: string;
  isDeletingJobId: string;
  isHistoryLoading: boolean;
  job: JobState | null;
  jobHistory: JobSummary[];
  lifecycleError: string;
  loadHistoryJob: (jobId: string) => Promise<void>;
  refreshJobHistory: () => Promise<void>;
  resumeActiveTranscription: () => Promise<void>;
  setJob: Dispatch<SetStateAction<JobState | null>>;
  setLifecycleError: Dispatch<SetStateAction<string>>;
};

export function useJobLifecycle({
  onClearSelectedInputs,
  onResetTaskContext
}: UseJobLifecycleOptions): JobLifecycle {
  const [job, setJob] = useState<JobState | null>(null);
  const [jobHistory, setJobHistory] = useState<JobSummary[]>([]);
  const [historyError, setHistoryError] = useState("");
  const [isHistoryLoading, setIsHistoryLoading] = useState(false);
  const [isDeletingJobId, setIsDeletingJobId] = useState("");
  const [lifecycleError, setLifecycleError] = useState("");
  const mountedRef = useRef(true);
  const historyRequestRef = useRef(0);
  const loadControllerRef = useRef<AbortController | null>(null);
  const onClearSelectedInputsRef = useRef(onClearSelectedInputs);
  const onResetTaskContextRef = useRef(onResetTaskContext);
  onClearSelectedInputsRef.current = onClearSelectedInputs;
  onResetTaskContextRef.current = onResetTaskContext;

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      historyRequestRef.current += 1;
      loadControllerRef.current?.abort();
    };
  }, []);

  const refreshJobHistory = useCallback(async () => {
    const requestId = historyRequestRef.current + 1;
    historyRequestRef.current = requestId;
    setIsHistoryLoading(true);
    setHistoryError("");
    try {
      const payload = await fetchJobHistory();
      if (mountedRef.current && requestId === historyRequestRef.current) {
        setJobHistory(payload.jobs);
      }
    } catch (error) {
      if (mountedRef.current && requestId === historyRequestRef.current) {
        setHistoryError(error instanceof Error ? error.message : "历史任务读取失败。");
      }
    } finally {
      if (mountedRef.current && requestId === historyRequestRef.current) {
        setIsHistoryLoading(false);
      }
    }
  }, []);

  useEffect(() => {
    void refreshJobHistory();
  }, [refreshJobHistory]);

  useEffect(() => {
    const jobId = job?.job_id;
    const jobStatus = job?.status;
    if (!jobId || (jobStatus !== "pending" && jobStatus !== "running" && jobStatus !== "cancelling")) {
      return;
    }
    let stopped = false;
    let timer: number | undefined;
    let controller: AbortController | null = null;

    const scheduleNext = () => {
      if (!stopped) {
        timer = window.setTimeout(() => void poll(), 1600);
      }
    };
    const poll = async () => {
      controller = new AbortController();
      try {
        const nextJob = await fetchJob(jobId, controller.signal);
        if (!stopped && mountedRef.current) {
          setJob((current) => (current?.job_id === jobId ? nextJob : current));
        }
      } catch (error) {
        if (!stopped && !isAbortError(error)) {
          // Preserve the last usable state across transient polling failures.
        }
      } finally {
        controller = null;
        scheduleNext();
      }
    };

    scheduleNext();
    return () => {
      stopped = true;
      controller?.abort();
      if (timer !== undefined) {
        window.clearTimeout(timer);
      }
    };
  }, [job?.job_id, job?.status]);

  useEffect(() => {
    if (job?.status === "succeeded" || job?.status === "failed" || job?.status === "cancelled") {
      void refreshJobHistory();
    }
  }, [job?.job_id, job?.status, refreshJobHistory]);

  async function loadHistoryJob(jobId: string) {
    setHistoryError("");
    setLifecycleError("");
    onResetTaskContextRef.current();
    onClearSelectedInputsRef.current();
    loadControllerRef.current?.abort();
    const controller = new AbortController();
    loadControllerRef.current = controller;
    try {
      const nextJob = await fetchJob(jobId, controller.signal);
      if (mountedRef.current && loadControllerRef.current === controller) {
        setJob(nextJob);
      }
    } catch (error) {
      if (mountedRef.current && loadControllerRef.current === controller && !isAbortError(error)) {
        setHistoryError(error instanceof Error ? error.message : "历史任务载入失败。");
      }
    } finally {
      if (loadControllerRef.current === controller) {
        loadControllerRef.current = null;
      }
    }
  }

  async function cancelActiveJob() {
    if (!job || (job.status !== "pending" && job.status !== "running")) {
      return;
    }
    const requestJobId = job.job_id;
    setLifecycleError("");
    try {
      const nextJob = await cancelJob(requestJobId);
      if (mountedRef.current) {
        setJob((current) => (current?.job_id === requestJobId ? nextJob : current));
      }
      await refreshJobHistory();
    } catch (error) {
      if (mountedRef.current) {
        setLifecycleError(error instanceof Error ? error.message : "取消任务失败。");
      }
    }
  }

  async function resumeActiveTranscription() {
    if (!job || !job.work_progress?.resumable || (job.status !== "cancelled" && job.status !== "failed")) {
      return;
    }
    const requestJobId = job.job_id;
    setLifecycleError("");
    try {
      await resumeJobTranscription(requestJobId);
      const nextJob = await fetchJob(requestJobId);
      if (mountedRef.current) {
        setJob((current) => (current?.job_id === requestJobId ? nextJob : current));
      }
      await refreshJobHistory();
    } catch (error) {
      if (mountedRef.current) {
        setLifecycleError(error instanceof Error ? error.message : "继续转写失败。");
      }
    }
  }

  async function deleteHistoryJob(jobId: string) {
    if (!window.confirm("删除后会移除该任务及其所有笔记版本，是否继续？")) {
      return;
    }
    setIsDeletingJobId(jobId);
    setHistoryError("");
    try {
      await deleteJob(jobId);
      if (job?.job_id === jobId) {
        onResetTaskContextRef.current();
        onClearSelectedInputsRef.current();
      }
      await refreshJobHistory();
    } catch (error) {
      if (mountedRef.current) {
        setHistoryError(error instanceof Error ? error.message : "历史任务删除失败。");
      }
    } finally {
      if (mountedRef.current) {
        setIsDeletingJobId("");
      }
    }
  }

  return {
    cancelActiveJob,
    deleteHistoryJob,
    historyError,
    isDeletingJobId,
    isHistoryLoading,
    job,
    jobHistory,
    lifecycleError,
    loadHistoryJob,
    refreshJobHistory,
    resumeActiveTranscription,
    setJob,
    setLifecycleError
  };
}

function isAbortError(error: unknown): boolean {
  return error instanceof Error && error.name === "AbortError";
}
