import { useEffect, useRef, useState } from "react";

import {
  fetchCudaDependencyInstall,
  fetchLocalDependencyInstall,
  fetchModelDownload,
  startCudaDependencyInstall,
  startLocalDependencyInstall,
  startModelDownload
} from "./api";
import type {
  CudaDependencyInstallState,
  LocalDependencyInstallState,
  ModelDownloadState,
  PollableTaskState
} from "./types";

type UseRuntimeTasksOptions = {
  cudaPythonPath: string;
  localPythonPath: string;
  modelName: string;
  modelRoot: string;
  onRefreshHealth: () => Promise<void>;
};

type RuntimeTasks = {
  cudaInstall: CudaDependencyInstallState | null;
  cudaInstallError: string;
  downloadLocalModel: () => Promise<void>;
  installCudaDependencies: () => Promise<void>;
  installLocalDependencies: () => Promise<void>;
  localDependencyInstall: LocalDependencyInstallState | null;
  localDependencyInstallError: string;
  modelDownload: ModelDownloadState | null;
  modelDownloadError: string;
};

export function useRuntimeTasks({
  cudaPythonPath,
  localPythonPath,
  modelName,
  modelRoot,
  onRefreshHealth
}: UseRuntimeTasksOptions): RuntimeTasks {
  const modelTask = usePolledRuntimeTask<ModelDownloadState>({
    intervalMs: 1400,
    onSucceeded: onRefreshHealth,
    poll: (task) => fetchModelDownload(task.model_name),
    pollErrorMessage: "模型下载状态读取失败。"
  });
  const localDependencyTask = usePolledRuntimeTask<LocalDependencyInstallState>({
    intervalMs: 1600,
    onSucceeded: onRefreshHealth,
    poll: fetchLocalDependencyInstall,
    pollErrorMessage: "本地转写依赖安装状态读取失败。"
  });
  const cudaTask = usePolledRuntimeTask<CudaDependencyInstallState>({
    intervalMs: 1800,
    onSucceeded: onRefreshHealth,
    poll: fetchCudaDependencyInstall,
    pollErrorMessage: "CUDA 依赖安装状态读取失败。"
  });

  async function downloadLocalModel() {
    await modelTask.start(
      () => startModelDownload(modelName),
      {
        error: "",
        model_name: modelName,
        model_root: modelRoot,
        progress: 0,
        status: "pending"
      },
      "模型下载启动失败。"
    );
  }

  async function installLocalDependencies() {
    await localDependencyTask.start(
      startLocalDependencyInstall,
      {
        error: "",
        progress: 0,
        python_path: localPythonPath,
        status: "pending"
      },
      "本地转写依赖安装启动失败。"
    );
  }

  async function installCudaDependencies() {
    const shouldInstall = window.confirm(
      "CUDA 加速依赖包含 NVIDIA cuBLAS/cuDNN，下载体积约 1GB+。是否现在安装到当前外部 Python 环境？"
    );
    if (!shouldInstall) {
      return;
    }
    await cudaTask.start(
      startCudaDependencyInstall,
      {
        error: "",
        progress: 0,
        python_path: cudaPythonPath,
        status: "pending"
      },
      "CUDA 依赖安装启动失败。"
    );
  }

  return {
    cudaInstall: cudaTask.task,
    cudaInstallError: cudaTask.error,
    downloadLocalModel,
    installCudaDependencies,
    installLocalDependencies,
    localDependencyInstall: localDependencyTask.task,
    localDependencyInstallError: localDependencyTask.error,
    modelDownload: modelTask.task,
    modelDownloadError: modelTask.error
  };
}

type PolledTask<T extends PollableTaskState & { error: string }> = {
  error: string;
  start: (request: () => Promise<T>, optimisticState: T, errorMessage: string) => Promise<void>;
  task: T | null;
};

function usePolledRuntimeTask<T extends PollableTaskState & { error: string }>({
  intervalMs,
  onSucceeded,
  poll,
  pollErrorMessage
}: {
  intervalMs: number;
  onSucceeded: () => Promise<void>;
  poll: (task: T) => Promise<T>;
  pollErrorMessage: string;
}): PolledTask<T> {
  const [task, setTask] = useState<T | null>(null);
  const [error, setError] = useState("");
  const mountedRef = useRef(true);
  const requestEpochRef = useRef(0);
  const pollRef = useRef(poll);
  const onSucceededRef = useRef(onSucceeded);
  pollRef.current = poll;
  onSucceededRef.current = onSucceeded;

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      requestEpochRef.current += 1;
    };
  }, []);

  const taskStatus = task?.status;
  const taskKey = task && "model_name" in task ? String(task.model_name) : "runtime";

  useEffect(() => {
    if (!task || (task.status !== "pending" && task.status !== "running")) {
      return;
    }
    let stopped = false;
    let timer: number | undefined;
    const activeTask = task;

    const schedule = () => {
      if (!stopped) {
        timer = window.setTimeout(() => void pollTask(), intervalMs);
      }
    };
    const pollTask = async () => {
      try {
        const nextTask = await pollRef.current(activeTask);
        if (stopped || !mountedRef.current) {
          return;
        }
        setTask(nextTask);
        setError("");
        if (nextTask.status === "succeeded") {
          await onSucceededRef.current();
        } else if (nextTask.status === "pending" || nextTask.status === "running") {
          schedule();
        }
      } catch (pollError) {
        if (stopped || !mountedRef.current) {
          return;
        }
        setError(pollError instanceof Error ? pollError.message : pollErrorMessage);
        schedule();
      }
    };

    schedule();
    return () => {
      stopped = true;
      if (timer !== undefined) {
        window.clearTimeout(timer);
      }
    };
  }, [intervalMs, pollErrorMessage, taskKey, taskStatus]);

  async function start(request: () => Promise<T>, optimisticState: T, errorMessage: string) {
    const requestEpoch = requestEpochRef.current + 1;
    requestEpochRef.current = requestEpoch;
    setError("");
    setTask(optimisticState);
    try {
      const nextTask = await request();
      if (!mountedRef.current || requestEpoch !== requestEpochRef.current) {
        return;
      }
      setTask(nextTask);
      if (nextTask.status === "succeeded") {
        await onSucceededRef.current();
      }
    } catch (startError) {
      if (!mountedRef.current || requestEpoch !== requestEpochRef.current) {
        return;
      }
      const message = startError instanceof Error ? startError.message : errorMessage;
      setError(message);
      setTask((current) =>
        current
          ? {
              ...current,
              error: message,
              status: "failed"
            }
          : null
      );
    }
  }

  return { error, start, task };
}
