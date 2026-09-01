import {
  AlertTriangle,
  CheckCircle2,
  Loader2,
  Settings,
  X
} from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";

import type {
  FrameCandidate,
  FrameCandidateIndex,
  JobState,
  PreviewImage,
} from "./types";
import { statusText } from "./constants";
import {
  formatElapsedSeconds,
} from "./format";
import { extractMarkdownImages } from "./markdown";
import { FrameReviewModal } from "./FrameReviewModal";
import { JobHistoryPanel } from "./JobHistoryPanel";
import { ResultWorkbench } from "./ResultWorkbench";
import { HealthBadge } from "./RuntimeStatus";
import { SettingsModal } from "./SettingsModal";
import { TranscriptCorrectionModal } from "./TranscriptCorrectionModal";
import { TaskConfigPanel } from "./TaskConfigPanel";
import { useHealthState } from "./useHealthState";
import { useJobCreation } from "./useJobCreation";
import { useJobResources } from "./useJobResources";
import { useJobLifecycle } from "./useJobLifecycle";
import { useNoteWorkflow } from "./useNoteWorkflow";
import { useReviewWorkflow } from "./useReviewWorkflow";
import { useRuntimeTasks } from "./useRuntimeTasks";
import { useSettings } from "./useSettings";
import { useSubtitleWorkflow } from "./useSubtitleWorkflow";
import type { WorkbenchTab } from "./WorkbenchNavigation";

export function App() {
  const { health, refreshHealth } = useHealthState();
  const {
    clearSettings: handleClearSettings,
    isSavingSettings,
    saveSettings: handleSaveSettings,
    settings,
    settingsMessage,
    updateSetting
  } = useSettings(refreshHealth);
  const {
    external_python_path: externalPythonPath,
    extras,
    faster_whisper_model_dir: fasterWhisperModelDir,
    frame_limit: frameLimit,
    local_whisper_compute_type: localWhisperComputeType,
    local_whisper_device: localWhisperDevice,
    note_api_key: noteApiKey,
    note_base_url: noteBaseUrl,
    note_language: noteLanguage,
    note_model: noteModel,
    note_style: noteStyle,
    performance_mode: performanceMode,
    python_package_install_mode: pythonPackageInstallMode,
    transcription_api_key: transcriptionApiKey,
    transcription_base_url: transcriptionBaseUrl,
    transcription_language: transcriptionLanguage,
    transcription_mode: transcriptionMode,
    transcription_model: transcriptionModel
  } = settings;
  const workspaceFormRef = useRef<HTMLFormElement>(null);
  const resetTaskContextRef = useRef<() => void>(() => undefined);
  const clearSelectedInputsRef = useRef<() => void>(() => undefined);
  const {
    cancelActiveJob: handleCancelJob,
    deleteHistoryJob: handleDeleteHistoryJob,
    historyError,
    isDeletingJobId,
    isHistoryLoading,
    job,
    jobHistory,
    lifecycleError,
    loadHistoryJob: handleLoadHistoryJob,
    refreshJobHistory,
    resumeActiveTranscription: handleResumeTranscription,
    setJob,
    setLifecycleError
  } = useJobLifecycle({
    onClearSelectedInputs: () => clearSelectedInputsRef.current(),
    onResetTaskContext: () => resetTaskContextRef.current()
  });
  const {
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
  } = useJobResources(job);
  const [isSettingsOpen, setIsSettingsOpen] = useState(false);
  const [activeWorkbench, setActiveWorkbench] = useState<WorkbenchTab>("note");
  const [downloadMessage, setDownloadMessage] = useState("");
  const {
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
    isTranscriptCorrectionActive,
    regenerateSubtitles: handleRegenerateSubtitles,
    resetSubtitleWorkflow,
    subtitleGateError
  } = useSubtitleWorkflow({
    job,
    noteConfig: {
      extras,
      frame_limit: frameLimit,
      note_api_key: noteApiKey,
      note_base_url: noteBaseUrl,
      note_language: noteLanguage,
      note_model: noteModel,
      note_style: noteStyle
    },
    onRefreshJobHistory: refreshJobHistory,
    setJob,
    transcriptionConfig: {
      local_whisper_compute_type: localWhisperComputeType,
      local_whisper_device: localWhisperDevice,
      performance_mode: performanceMode,
      transcription_api_key: transcriptionApiKey,
      transcription_base_url: transcriptionBaseUrl,
      transcription_language: transcriptionLanguage,
      transcription_mode: transcriptionMode,
      transcription_model: transcriptionModel
    }
  });
  const {
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
  } = useNoteWorkflow({
    job,
    noteChunks,
    noteConfig: {
      extras,
      frame_limit: frameLimit,
      note_api_key: noteApiKey,
      note_base_url: noteBaseUrl,
      note_language: noteLanguage,
      note_model: noteModel,
      note_style: noteStyle
    },
    noteVersions,
    onRefreshJobHistory: refreshJobHistory,
    previewVersionId,
    setJob,
    setNoteVersions,
    setPreviewVersionId
  });
  const {
    closeFrameReview,
    isFrameReviewOpen,
    openFrameReview,
    openManualReview: handleManualReview,
    resetReviewWorkflow,
    reviewDraftSavingId,
    saveReviewParagraph: handleSaveReviewParagraph
  } = useReviewWorkflow({
    frameCandidateIndex,
    job,
    loadManualReview,
    previewVersionId,
    refreshQualityReport,
    reviewDraft,
    setFrameCandidateError,
    setJob,
    setReviewDraft
  });
  const {
    cudaInstall,
    cudaInstallError,
    downloadLocalModel: handleDownloadLocalModel,
    installCudaDependencies: handleInstallCudaDependencies,
    installLocalDependencies: handleInstallLocalDependencies,
    localDependencyInstall,
    localDependencyInstallError,
    modelDownload,
    modelDownloadError
  } = useRuntimeTasks({
    cudaPythonPath: health?.runtime?.faster_whisper.external_python_path ?? "",
    localPythonPath: health?.runtime?.faster_whisper.external_python_path ?? "",
    modelName: transcriptionModel,
    modelRoot: health?.runtime?.local_models.root ?? "",
    onRefreshHealth: refreshHealth
  });
  const {
    clearSelectedInputs,
    clearSubtitle: handleClearSubtitle,
    handleSubtitleChange,
    handleVideoChange,
    hasUploadedSubtitle,
    isSubmitting,
    submitError,
    submitJob: handleSubmit,
    subtitle,
    subtitleInputRef,
    video,
    videoInputRef
  } = useJobCreation({
    hasTaskContext: Boolean(job || notePreview || subtitlePreview || noteVersions),
    health,
    onClearLifecycleError: () => setLifecycleError(""),
    onDownloadLocalModel: handleDownloadLocalModel,
    onRefreshJobHistory: refreshJobHistory,
    onResetTaskContext: () => resetTaskContextRef.current(),
    setJob,
    settings
  });
  clearSelectedInputsRef.current = clearSelectedInputs;

  const isBusy =
    job?.status === "pending" ||
    job?.status === "running" ||
    job?.status === "cancelling" ||
    isSubmitting ||
    isRegenerating ||
    isConfirmingSubtitles ||
    isRegeneratingSubtitles ||
    isTranscriptCorrectionActive ||
    isFinalizingJob;
  const images = useMemo(() => job?.artifacts.filter((artifact) => artifact.kind === "image") ?? [], [job]);
  const hasNoteArtifact = Boolean(job?.artifacts.some((artifact) => artifact.path === "note.md"));
  const previewVersion = useMemo(
    () => noteVersions?.versions.find((version) => version.id === previewVersionId) ?? null,
    [noteVersions, previewVersionId]
  );
  const previewAssetBasePath = previewVersion ? `note_versions/${previewVersion.id}` : undefined;
  const previewImages = useMemo<PreviewImage[]>(() => {
    if (job && previewVersion) {
      return extractMarkdownImages(notePreview, job.job_id, previewAssetBasePath);
    }
    return images.map((artifact) => ({
      label: artifact.label,
      path: artifact.path,
      asset_url: artifact.asset_url
    }));
  }, [images, job, notePreview, previewAssetBasePath, previewVersion]);
  const frameCandidateGroups = useMemo(() => {
    const groups = new Map<number, FrameCandidate[]>();
    for (const context of frameCandidateIndex?.chapter_contexts ?? []) {
      groups.set(context.chapter_index, groups.get(context.chapter_index) ?? []);
    }
    for (const candidate of frameCandidateIndex?.candidates ?? []) {
      const group = groups.get(candidate.chapter_index) ?? [];
      group.push(candidate);
      groups.set(candidate.chapter_index, group);
    }
    return Array.from(groups.entries()).sort(([left], [right]) => left - right);
  }, [frameCandidateIndex]);
  const frameCandidateContextByChapter = useMemo(() => {
    const contexts = new Map<number, FrameCandidateIndex["chapter_contexts"][number]>();
    for (const context of frameCandidateIndex?.chapter_contexts ?? []) {
      contexts.set(context.chapter_index, context);
    }
    return contexts;
  }, [frameCandidateIndex]);
  const selectedFrameCandidateCount =
    frameCandidateIndex?.candidates.filter((candidate) => candidate.selected && !candidate.rejected).length ?? 0;
  const currentJobSummary = useMemo(
    () => jobHistory.find((item) => item.job_id === job?.job_id) ?? null,
    [job?.job_id, jobHistory]
  );
  function resetTaskContext() {
    setJob(null);
    resetJobResources();
    resetNoteWorkflow();
    setDownloadMessage("");
    resetSubtitleWorkflow();
    setFrameCandidateError("");
    resetReviewWorkflow();
  }
  resetTaskContextRef.current = resetTaskContext;

  useEffect(() => {
    if (job?.stage === "awaiting_subtitle_review" || job?.status === "awaiting_subtitle_confirmation") {
      setActiveWorkbench("subtitle");
    } else if (job?.stage === "awaiting_note_review" || job?.status === "awaiting_note_review") {
      setActiveWorkbench("note");
    } else if (
      job?.stage === "generating_frames" ||
      job?.stage === "preparing_review" ||
      (!job?.stage && job?.step.includes("关键帧"))
    ) {
      setActiveWorkbench("frame");
    } else if (job?.stage === "completed" || job?.status === "succeeded") {
      setActiveWorkbench("note");
    }
  }, [job?.stage, job?.status, job?.step]);

  useEffect(() => {
    function handleShortcut(event: KeyboardEvent) {
      if (event.key === "Escape") {
        setIsSettingsOpen(false);
        closeFrameReview();
        return;
      }
      if (!(event.ctrlKey || event.metaKey)) {
        return;
      }
      if (event.key === ",") {
        event.preventDefault();
        setIsSettingsOpen(true);
      } else if (event.key.toLowerCase() === "o") {
        event.preventDefault();
        videoInputRef.current?.click();
      } else if (event.key.toLowerCase() === "s" && job?.artifacts.some((artifact) => artifact.path === "download.zip")) {
        event.preventDefault();
        (document.querySelector('[data-download-zip="true"]') as HTMLButtonElement | null)?.click();
      } else if (event.key === "Enter" && health && !isBusy) {
        event.preventDefault();
        workspaceFormRef.current?.requestSubmit();
      }
    }
    window.addEventListener("keydown", handleShortcut);
    return () => window.removeEventListener("keydown", handleShortcut);
  }, [health, isBusy, job]);

  return (
    <main className="app-shell">
      <header className="topbar">
        <div className="topbar-brand">
          <p className="eyebrow">本地优先 · AI 视频整理</p>
          <h1>视频笔记生成器</h1>
        </div>
        <div className="topbar-stepper">
          <StepList job={job} />
          <div className="step-progress-bar" aria-label="处理进度">
            <StepProgress job={job} />
          </div>
        </div>
        <div className="topbar-actions">
          <HealthBadge
            hasUploadedSubtitle={hasUploadedSubtitle}
            health={health}
            localWhisperDevice={localWhisperDevice}
            transcriptionMode={transcriptionMode}
          />
          <button className="settings-button" onClick={() => setIsSettingsOpen(true)} title="打开设置" type="button">
            <Settings size={17} />
            <span>设置</span>
          </button>
        </div>
      </header>

      <form className="workspace-grid" onSubmit={handleSubmit} ref={workspaceFormRef}>
        {job?.error && (
          <div className="error-box">
            <AlertTriangle size={18} />
            <span>{job.error}</span>
          </div>
        )}

        <TaskConfigPanel
          extras={extras}
          frameLimit={frameLimit}
          isBusy={isBusy}
          job={job}
          noteLanguage={noteLanguage}
          noteStyle={noteStyle}
          onCancelJob={() => void handleCancelJob()}
          onClearSubtitle={handleClearSubtitle}
          onExtrasChange={(value) => updateSetting("extras", value)}
          onFrameLimitChange={(value) => updateSetting("frame_limit", value)}
          onNoteLanguageChange={(value) => updateSetting("note_language", value)}
          onNoteStyleChange={(value) => updateSetting("note_style", value)}
          onResumeTranscription={() => void handleResumeTranscription()}
          onSubtitleChange={handleSubtitleChange}
          onVideoChange={handleVideoChange}
          serviceConnected={Boolean(health)}
          subtitle={subtitle}
          subtitleInputRef={subtitleInputRef}
          submitError={submitError || lifecycleError}
          video={video}
          videoInputRef={videoInputRef}
        />

        <div className="workspace-bottom">
          <JobHistoryPanel
            activeJob={job}
            busy={isBusy}
            deletingJobId={isDeletingJobId}
            error={historyError}
            health={health}
            history={jobHistory}
            loading={isHistoryLoading}
            onDelete={(jobId) => void handleDeleteHistoryJob(jobId)}
            onLoad={(jobId) => void handleLoadHistoryJob(jobId)}
            onRefresh={() => void refreshJobHistory()}
          />

          <ResultWorkbench
            context={{ activeWorkbench, currentJobSummary, isBusy, job, onWorkbenchChange: setActiveWorkbench }}
            downloads={{ message: downloadMessage, onError: setDownloadMessage }}
            frames={{
              candidateError: frameCandidateError,
              candidateIndex: frameCandidateIndex,
              isReviewOpen: isFrameReviewOpen,
              onOpenReview: openFrameReview,
              previewImages,
              selectedCandidateCount: selectedFrameCandidateCount
            }}
            note={{
              chunks: noteChunks,
              finalizeError,
              hasArtifact: hasNoteArtifact,
              isFinalizing: isFinalizingJob,
              isRegenerating,
              isSwitchingVersion,
              onFinalize: () => void handleFinalizeJob(),
              onManualReview: () => void handleManualReview(),
              onRegenerate: () => void handleRegenerateNote(),
              onRegenerateChunk: (chunkId) => void handleRegenerateNoteChunk(chunkId),
              onVersionChange: handleNoteVersionChange,
              preview: notePreview,
              previewAssetBasePath,
              previewVersion,
              previewVersionId,
              qualityReport,
              qualityReportError,
              regeneratingChunkId,
              versionError,
              versions: noteVersions
            }}
            subtitle={{
              correctionError,
              correctionPreview,
              gateError: subtitleGateError,
              isConfirming: isConfirmingSubtitles,
              isCorrecting: isCorrectingTranscript,
              isRegenerating: isRegeneratingSubtitles,
              onConfirm: () => void handleConfirmSubtitles(),
              onCreateCorrection: () => void handleCreateTranscriptCorrection(),
              onRegenerate: () => void handleRegenerateSubtitles(),
              preview: subtitlePreview
            }}
          />
        </div>
      </form>

      <SettingsModal
        health={health}
        modal={{
          isOpen: isSettingsOpen,
          isSaving: isSavingSettings,
          message: settingsMessage,
          onClear: () => void handleClearSettings(),
          onClose: () => setIsSettingsOpen(false),
          onSave: () => void handleSaveSettings()
        }}
        note={{
          apiKey: noteApiKey,
          baseUrl: noteBaseUrl,
          model: noteModel,
          onApiKeyChange: (value) => updateSetting("note_api_key", value),
          onBaseUrlChange: (value) => updateSetting("note_base_url", value),
          onModelChange: (value) => updateSetting("note_model", value)
        }}
        transcription={{
          cudaInstall,
          cudaInstallError,
          externalPythonPath,
          fasterWhisperModelDir,
          localDependencyInstall,
          localDependencyInstallError,
          localWhisperComputeType,
          localWhisperDevice,
          modelDownload,
          modelDownloadError,
          onDownloadLocalModel: () => void handleDownloadLocalModel(),
          onExternalPythonPathChange: (value) => updateSetting("external_python_path", value),
          onFasterWhisperModelDirChange: (value) => updateSetting("faster_whisper_model_dir", value),
          onInstallCudaDependencies: () => void handleInstallCudaDependencies(),
          onInstallLocalDependencies: () => void handleInstallLocalDependencies(),
          onLocalWhisperComputeTypeChange: (value) => updateSetting("local_whisper_compute_type", value),
          onLocalWhisperDeviceChange: (value) => updateSetting("local_whisper_device", value),
          onPerformanceModeChange: (value) => updateSetting("performance_mode", value),
          onPythonPackageInstallModeChange: (value) => updateSetting("python_package_install_mode", value),
          onRefreshHealth: () => void refreshHealth(),
          onTranscriptionApiKeyChange: (value) => updateSetting("transcription_api_key", value),
          onTranscriptionBaseUrlChange: (value) => updateSetting("transcription_base_url", value),
          onTranscriptionLanguageChange: (value) => updateSetting("transcription_language", value),
          onTranscriptionModeChange: (value) => updateSetting("transcription_mode", value),
          onTranscriptionModelChange: (value) => updateSetting("transcription_model", value),
          performanceMode,
          pythonPackageInstallMode,
          transcriptionApiKey,
          transcriptionBaseUrl,
          transcriptionLanguage,
          transcriptionMode,
          transcriptionModel
        }}
      />
      <TranscriptCorrectionModal
        error={correctionError}
        isApplying={isApplyingCorrection}
        onApply={() => void handleApplyTranscriptCorrection()}
        onClose={closeTranscriptCorrection}
        preview={correctionPreview}
      />
      {isFrameReviewOpen && job && frameCandidateIndex && reviewDraft && (
        <FrameReviewModal
          contextByChapter={frameCandidateContextByChapter}
          groups={frameCandidateGroups}
          isBusy={isBusy}
          jobId={job.job_id}
          noteChunks={noteChunks}
          onSaveParagraph={(paragraphId, body, selectedFrameIds, status) =>
            void handleSaveReviewParagraph(paragraphId, body, selectedFrameIds, status)
          }
          onRegenerateNote={() => void handleRegenerateNote()}
          onRegenerateChunk={(chunkId) => void handleRegenerateNoteChunk(chunkId)}
          onClose={closeFrameReview}
          regeneratingChunkId={regeneratingChunkId}
          reviewDraft={reviewDraft}
          savingParagraphId={reviewDraftSavingId}
          selectedCount={selectedFrameCandidateCount}
        />
      )}
    </main>
  );
}


function StepList({ job }: { job: JobState | null }) {
  const steps = [
    { label: "分析视频", threshold: 10, activeSteps: ["分析视频", "音频分离"] },
    { label: "准备字幕", threshold: 35, activeSteps: ["字幕生成", "解析字幕"] },
    { label: "笔记生成", threshold: 60, activeSteps: ["笔记生成", "重新生成笔记", "重新生成笔记块"] },
    { label: "关键帧抽取", threshold: 78, activeSteps: ["关键帧抽取"] },
    { label: "Markdown 输出", threshold: 90, activeSteps: ["生成复核资料", "完成"] }
  ];
  return (
    <ol className="step-list">
      {steps.map((step, index) => {
        const done = (job?.progress ?? 0) >= step.threshold && job?.status !== "failed";
        const active = Boolean(job?.step && step.activeSteps.includes(job.step));
        return (
          <li className={done ? "done" : active ? "active" : ""} key={step.label}>
            <strong>{index + 1}</strong>
            <span>{step.label}</span>
          </li>
        );
      })}
    </ol>
  );
}

function StepProgress({ job }: { job: JobState | null }) {
  const progress = Math.min(100, Math.max(0, Math.round(job?.progress ?? 0)));
  const isActive = job?.status === "pending" || job?.status === "running" || job?.status === "cancelling";
  const icon = isActive ? (
    <Loader2 className="spin" size={14} />
  ) : job?.status === "succeeded" ? (
    <CheckCircle2 size={14} />
  ) : job?.status === "failed" ? (
    <AlertTriangle size={14} />
  ) : job?.status === "cancelled" ? (
    <X size={14} />
  ) : null;
  const label = job?.step || (job ? statusText[job.status] : "未开始");
  const work = job?.work_progress;
  return (
    <>
      <span className="step-progress-label">
        {icon}
        {label}
      </span>
      <span className="step-progress-track">
        <span className="step-progress-fill" style={{ width: `${progress}%` }} />
      </span>
      <span className="step-progress-detail">
        <span>{progress}%</span>
        {job?.stage_elapsed_seconds !== undefined && job.stage_elapsed_seconds > 0 && (
          <span>{formatElapsedSeconds(job.stage_elapsed_seconds)}</span>
        )}
      </span>
      {work && work.total_seconds > 0 && (
        <span className="transcription-work-progress">
          <span>{formatElapsedSeconds(work.completed_seconds)} / {formatElapsedSeconds(work.total_seconds)}</span>
          <span>{work.completed_chunks}/{work.total_chunks} 块</span>
          <span>{work.device.toUpperCase()} · {work.compute_type}</span>
          {work.cache_hits > 0 && <span>复用 {work.cache_hits} 块</span>}
          {work.eta_seconds !== null && work.eta_seconds !== undefined && <span>预计剩余 {formatElapsedSeconds(work.eta_seconds)}</span>}
        </span>
      )}
    </>
  );
}
