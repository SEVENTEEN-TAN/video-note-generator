import { useEffect, useRef, useState } from "react";
import type { ChangeEvent, FormEvent, RefObject } from "react";

import { createJob, fetchJob } from "./api";
import type { HealthState, JobState, UserSettings } from "./types";

type UseJobCreationOptions = {
  hasTaskContext: boolean;
  health: HealthState | null;
  onClearLifecycleError: () => void;
  onDownloadLocalModel: () => Promise<void>;
  onRefreshJobHistory: () => Promise<void>;
  onResetTaskContext: () => void;
  setJob: (job: JobState | null) => void;
  settings: UserSettings;
};

type JobCreation = {
  clearSelectedInputs: () => void;
  clearSubtitle: () => void;
  handleSubtitleChange: (event: ChangeEvent<HTMLInputElement>) => void;
  handleVideoChange: (event: ChangeEvent<HTMLInputElement>) => void;
  hasUploadedSubtitle: boolean;
  isSubmitting: boolean;
  submitError: string;
  submitJob: (event: FormEvent) => Promise<void>;
  subtitle: File | null;
  subtitleInputRef: RefObject<HTMLInputElement>;
  video: File | null;
  videoInputRef: RefObject<HTMLInputElement>;
};

export function useJobCreation({
  hasTaskContext,
  health,
  onClearLifecycleError,
  onDownloadLocalModel,
  onRefreshJobHistory,
  onResetTaskContext,
  setJob,
  settings
}: UseJobCreationOptions): JobCreation {
  const [video, setVideo] = useState<File | null>(null);
  const [subtitle, setSubtitle] = useState<File | null>(null);
  const [submitError, setSubmitError] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const videoInputRef = useRef<HTMLInputElement>(null);
  const subtitleInputRef = useRef<HTMLInputElement>(null);
  const mountedRef = useRef(true);
  const submissionEpochRef = useRef(0);
  const optionsRef = useRef({
    hasTaskContext,
    health,
    onClearLifecycleError,
    onDownloadLocalModel,
    onRefreshJobHistory,
    onResetTaskContext,
    setJob,
    settings
  });
  optionsRef.current = {
    hasTaskContext,
    health,
    onClearLifecycleError,
    onDownloadLocalModel,
    onRefreshJobHistory,
    onResetTaskContext,
    setJob,
    settings
  };

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      submissionEpochRef.current += 1;
    };
  }, []);

  function invalidatePendingSubmission() {
    submissionEpochRef.current += 1;
    setIsSubmitting(false);
  }

  function clearSelectedInputs() {
    invalidatePendingSubmission();
    setVideo(null);
    setSubtitle(null);
    if (videoInputRef.current) {
      videoInputRef.current.value = "";
    }
    if (subtitleInputRef.current) {
      subtitleInputRef.current.value = "";
    }
  }

  function clearSubtitle() {
    setSubtitle(null);
    if (subtitleInputRef.current) {
      subtitleInputRef.current.value = "";
    }
  }

  function handleVideoChange(event: ChangeEvent<HTMLInputElement>) {
    const selectedVideo = event.target.files?.[0] ?? null;
    if (!selectedVideo) {
      return;
    }
    const options = optionsRef.current;
    if (
      options.hasTaskContext &&
      !window.confirm("当前页面已有任务内容。选择新视频会清空当前页面并准备创建新任务，历史任务仍可在左侧重新载入。是否继续？")
    ) {
      event.currentTarget.value = "";
      return;
    }
    invalidatePendingSubmission();
    setSubmitError("");
    options.onClearLifecycleError();
    options.onResetTaskContext();
    setVideo(selectedVideo);
    event.currentTarget.value = "";
  }

  function handleSubtitleChange(event: ChangeEvent<HTMLInputElement>) {
    const selectedSubtitle = event.target.files?.[0] ?? null;
    if (!selectedSubtitle) {
      return;
    }
    if (!selectedSubtitle.name.toLowerCase().endsWith(".srt")) {
      setSubmitError("当前仅支持上传 .srt 字幕文件。");
      event.currentTarget.value = "";
      return;
    }
    const options = optionsRef.current;
    if (
      options.hasTaskContext &&
      !window.confirm("当前页面已有任务内容。选择新字幕会清空当前页面并准备创建新任务，历史任务仍可在左侧重新载入。是否继续？")
    ) {
      event.currentTarget.value = "";
      return;
    }
    invalidatePendingSubmission();
    setSubmitError("");
    options.onClearLifecycleError();
    options.onResetTaskContext();
    setSubtitle(selectedSubtitle);
    event.currentTarget.value = "";
  }

  async function submitJob(event: FormEvent) {
    event.preventDefault();
    const options = optionsRef.current;
    const { health: currentHealth, settings: currentSettings } = options;
    setSubmitError("");
    options.onClearLifecycleError();
    if (!video) {
      setSubmitError("请先选择视频文件。");
      return;
    }

    const hasUploadedSubtitle = Boolean(subtitle);
    const isLocalTranscription = currentSettings.transcription_mode === "local_faster_whisper";
    const runtimeLocalStatus = currentHealth?.runtime?.faster_whisper;
    const selectedLocalModelAvailable =
      !isLocalTranscription ||
      !currentHealth?.runtime ||
      currentHealth.runtime.local_models.models.includes(currentSettings.transcription_model);
    const localTranscriptionReady =
      !isLocalTranscription || !runtimeLocalStatus || runtimeLocalStatus.ready_for_cpu;

    if (!hasUploadedSubtitle) {
      if (!isLocalTranscription && !currentSettings.transcription_api_key.trim()) {
        setSubmitError("请填写字幕转写 API Key。");
        return;
      }
      if (!currentSettings.transcription_model.trim()) {
        setSubmitError("字幕转写模型不能为空。");
        return;
      }
      if (!selectedLocalModelAvailable) {
        const shouldDownload = window.confirm(
          `当前模型目录未发现 ${currentSettings.transcription_model}。是否现在下载到 ${currentHealth?.runtime?.local_models.root ?? "本地模型目录"}？`
        );
        if (shouldDownload) {
          void options.onDownloadLocalModel();
        } else {
          setSubmitError(`请先下载 ${currentSettings.transcription_model}，或切换远端字幕转写。`);
        }
        return;
      }
      if (!localTranscriptionReady) {
        setSubmitError(
          runtimeLocalStatus?.worker_probe_error ||
            runtimeLocalStatus?.worker_error ||
            runtimeLocalStatus?.install_hint ||
            "本地转写环境未就绪，请检查运行环境。"
        );
        return;
      }
    }

    options.onResetTaskContext();
    const formData = new FormData();
    formData.append("video", video);
    if (subtitle) {
      formData.append("subtitle", subtitle);
    }
    formData.append("transcription_mode", currentSettings.transcription_mode);
    formData.append("transcription_language", currentSettings.transcription_language);
    formData.append("transcription_api_key", isLocalTranscription ? "" : currentSettings.transcription_api_key);
    formData.append("transcription_base_url", isLocalTranscription ? "" : currentSettings.transcription_base_url);
    formData.append("transcription_model", currentSettings.transcription_model);
    formData.append("local_whisper_device", isLocalTranscription ? currentSettings.local_whisper_device : "");
    formData.append(
      "local_whisper_compute_type",
      isLocalTranscription ? currentSettings.local_whisper_compute_type : ""
    );
    formData.append("performance_mode", currentSettings.performance_mode);
    formData.append("note_api_protocol", currentSettings.note_api_protocol);
    formData.append("note_base_url", currentSettings.note_base_url);
    formData.append("note_model", currentSettings.note_model);
    formData.append("note_language", currentSettings.note_language);
    formData.append("note_style", currentSettings.note_style);
    formData.append("extras", currentSettings.extras);
    formData.append("frame_limit", String(currentSettings.frame_limit));

    const submissionEpoch = submissionEpochRef.current + 1;
    submissionEpochRef.current = submissionEpoch;
    setIsSubmitting(true);
    try {
      const created = await createJob(formData);
      const nextJob = await fetchJob(created.job_id);
      if (!mountedRef.current || submissionEpoch !== submissionEpochRef.current) {
        return;
      }
      options.setJob(nextJob);
      await options.onRefreshJobHistory();
    } catch (error) {
      if (mountedRef.current && submissionEpoch === submissionEpochRef.current) {
        setSubmitError(error instanceof Error ? error.message : "任务创建失败。");
      }
    } finally {
      if (mountedRef.current && submissionEpoch === submissionEpochRef.current) {
        setIsSubmitting(false);
      }
    }
  }

  return {
    clearSelectedInputs,
    clearSubtitle,
    handleSubtitleChange,
    handleVideoChange,
    hasUploadedSubtitle: Boolean(subtitle),
    isSubmitting,
    submitError,
    submitJob,
    subtitle,
    subtitleInputRef,
    video,
    videoInputRef
  };
}
