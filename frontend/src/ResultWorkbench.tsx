import {
  AlertTriangle,
  Captions,
  CheckCircle2,
  ChevronDown,
  Download,
  FileSearch,
  FileText,
  Image,
  Loader2,
  RefreshCw
} from "lucide-react";
import type { ChangeEvent, ReactNode } from "react";
import { useState } from "react";

import { downloadArtifact, deriveDownloadFilename } from "./api";
import { formatSecondsRange, formatVersionDetails, formatVersionOption } from "./format";
import { parseMarkdown, resolvePreviewAssetUrl } from "./markdown";
import { QualityStatusControl } from "./QualityStatusControl";
import type {
  FrameCandidateIndex,
  JobState,
  JobSummary,
  NoteChunkIndex,
  NoteVersion,
  NoteVersionIndex,
  PreviewImage,
  QualityReport,
  TranscriptCorrectionPreview
} from "./types";
import { WorkbenchNavigation } from "./WorkbenchNavigation";
import type { WorkbenchTab } from "./WorkbenchNavigation";

type ResultWorkbenchProps = {
  context: {
    activeWorkbench: WorkbenchTab;
    currentJobSummary: JobSummary | null;
    isBusy: boolean;
    job: JobState | null;
    onWorkbenchChange: (tab: WorkbenchTab) => void;
  };
  downloads: {
    message: string;
    onError: (message: string) => void;
  };
  frames: {
    candidateError: string;
    candidateIndex: FrameCandidateIndex | null;
    isReviewOpen: boolean;
    onOpenReview: () => void;
    previewImages: PreviewImage[];
    selectedCandidateCount: number;
  };
  note: {
    chunks: NoteChunkIndex | null;
    finalizeError: string;
    hasArtifact: boolean;
    isFinalizing: boolean;
    isRegenerating: boolean;
    isSwitchingVersion: boolean;
    onFinalize: () => void;
    onManualReview: () => void;
    onRegenerate: () => void;
    onRegenerateChunk: (chunkId: string) => void;
    onVersionChange: (event: ChangeEvent<HTMLSelectElement>) => void;
    preview: string;
    previewAssetBasePath?: string;
    previewVersion: NoteVersion | null;
    previewVersionId: string;
    qualityReport: QualityReport | null;
    qualityReportError: string;
    regeneratingChunkId: string;
    versionError: string;
    versions: NoteVersionIndex | null;
  };
  subtitle: {
    correctionError: string;
    correctionPreview: TranscriptCorrectionPreview | null;
    gateError: string;
    isConfirming: boolean;
    isCorrecting: boolean;
    isRegenerating: boolean;
    onConfirm: () => void;
    onCreateCorrection: () => void;
    onRegenerate: () => void;
    preview: string;
  };
};

export function ResultWorkbench({
  context,
  downloads,
  frames,
  note,
  subtitle
}: ResultWorkbenchProps) {
  const { activeWorkbench, currentJobSummary, isBusy, job, onWorkbenchChange } = context;
  const { message: downloadMessage, onError: onDownloadError } = downloads;
  const {
    candidateError: frameCandidateError,
    candidateIndex: frameCandidateIndex,
    isReviewOpen: isFrameReviewOpen,
    onOpenReview: onOpenFrameReview,
    previewImages,
    selectedCandidateCount: selectedFrameCandidateCount
  } = frames;
  const {
    chunks: noteChunks,
    finalizeError,
    hasArtifact: hasNoteArtifact,
    isFinalizing: isFinalizingJob,
    isRegenerating,
    isSwitchingVersion,
    onFinalize: onFinalizeJob,
    onManualReview,
    onRegenerate: onRegenerateNote,
    onRegenerateChunk: onRegenerateNoteChunk,
    onVersionChange: onNoteVersionChange,
    preview: notePreview,
    previewAssetBasePath,
    previewVersion,
    previewVersionId,
    qualityReport,
    qualityReportError,
    regeneratingChunkId,
    versionError,
    versions: noteVersions
  } = note;
  const {
    correctionError,
    correctionPreview,
    gateError: subtitleGateError,
    isConfirming: isConfirmingSubtitles,
    isCorrecting: isCorrectingTranscript,
    isRegenerating: isRegeneratingSubtitles,
    onConfirm: onConfirmSubtitles,
    onCreateCorrection: onCreateTranscriptCorrection,
    onRegenerate: onRegenerateSubtitles,
    preview: subtitlePreview
  } = subtitle;
  const noteTitleAction = hasNoteArtifact ? (
    <div className="note-title-actions note-title-toolbar">
      {noteVersions && noteVersions.versions.length > 0 && (
        <label className="version-inline compact">
          <span>版本</span>
          <select
            disabled={isBusy || isFrameReviewOpen || isSwitchingVersion}
            value={previewVersionId}
            onChange={onNoteVersionChange}
          >
            {noteVersions.versions.map((version) => (
              <option key={version.id} value={version.id}>
                {formatVersionOption(version)}
              </option>
            ))}
          </select>
          {previewVersion?.active && <span className="mini-badge ok">当前</span>}
        </label>
      )}
      <button className="small-button" disabled={!job || isBusy} onClick={onRegenerateNote} type="button">
        {isRegenerating ? <Loader2 className="spin" size={15} /> : <RefreshCw size={15} />}
        重新生成
      </button>
      {qualityReport && <QualityStatusControl report={qualityReport} />}
      <button className="small-button manual-review-button" disabled={isBusy} onClick={onManualReview} type="button">
        <FileSearch size={15} />
        手动审核
      </button>
    </div>
  ) : null;

  return (
    <section className={`panel result-panel workbench-${activeWorkbench} ${job ? "has-result" : "is-empty"}`} aria-label="结果预览">
      <div className="panel-title result-panel-title">
        <div className="panel-title-main">
          <FileText size={18} />
          <h2>结果预览</h2>
        </div>
        {previewVersion && <span className="result-version-summary">{formatVersionDetails(previewVersion)}</span>}
      </div>
      <div className="download-row">
        <div className="download-actions">
          <DownloadLink job={job} artifactPath="note.md" label="Markdown" onDownloadError={onDownloadError} />
          <DownloadLink job={job} artifactPath="subtitles.srt" label="SRT" onDownloadError={onDownloadError} />
          <DownloadLink job={job} artifactPath="audio.mp3" label="MP3" onDownloadError={onDownloadError} />
          <DownloadLink job={job} artifactPath="debug.log" label="调试日志" onDownloadError={onDownloadError} />
          {job && !["pending", "running", "cancelling"].includes(job.status) && (
            <ArtifactDownloadButton
              filename={`video-note-${job.job_id}-diagnostics.zip`}
              label="诊断包"
              onError={onDownloadError}
              url={`/api/jobs/${job.job_id}/diagnostics.zip`}
            />
          )}
          {job?.artifacts.some((artifact) => artifact.path === "download.zip") && job && (
            <ArtifactDownloadButton
              className="small-button strong"
              dataDownloadZip="true"
              filename={job.download_filename ?? `video-note-${job.job_id}.zip`}
              label="ZIP"
              onError={onDownloadError}
              url={`/api/jobs/${job.job_id}/download.zip`}
            />
          )}
        </div>
      </div>
      {job && (
        <WorkbenchNavigation active={activeWorkbench} job={job} summary={currentJobSummary} onChange={onWorkbenchChange} />
      )}
      {!job && (
        <div className="result-empty-state">
          <div className="result-empty-icon">
            <FileText size={26} />
          </div>
          <strong>选择视频，开始生成笔记</strong>
          <span>笔记、字幕、音频和关键帧将在这里集中审核与下载。</span>
        </div>
      )}
      <div className="result-body-scroll">
        {noteChunks && noteChunks.chunks.length > 1 && (
          <details className="chunk-manager" aria-label="笔记分段管理">
            <summary>
              <Captions size={15} />
              <span>笔记分段（{noteChunks.chunks.length} 块）</span>
            </summary>
            <div className="chunk-list">
              {noteChunks.chunks.map((chunk) => (
                <div className={`chunk-item ${chunk.status}`} key={chunk.id}>
                  <div className="chunk-item-info">
                    <strong>{chunk.label}</strong>
                    <span className="chunk-time">{formatSecondsRange(chunk.start_time, chunk.end_time)}</span>
                    {chunk.title && <span className="chunk-title">{chunk.title}</span>}
                    {chunk.status === "skipped" && <span className="mini-badge warn">已跳过</span>}
                  </div>
                  <button
                    className="small-button"
                    disabled={isBusy || regeneratingChunkId === chunk.id}
                    onClick={() => onRegenerateNoteChunk(chunk.id)}
                    type="button"
                  >
                    {regeneratingChunkId === chunk.id ? (
                      <Loader2 className="spin" size={14} />
                    ) : (
                      <RefreshCw size={14} />
                    )}
                    重生成
                  </button>
                </div>
              ))}
            </div>
          </details>
        )}
        {qualityReportError && <InlineMessage kind="warning" message={qualityReportError} />}
        {frameCandidateError && <InlineMessage kind="warning" message={frameCandidateError} />}
        {subtitleGateError && <InlineMessage kind="error" message={subtitleGateError} />}
        {job?.status === "awaiting_note_review" && (
          <section className="note-review-gate" aria-label="确认定稿">
            <div>
              <strong>等待人工复核</strong>
              <span>确认覆盖、关键要点和配图后，生成最终定稿。ZIP 只是下载打包结果。</span>
            </div>
            <div className="review-gate-actions">
              {frameCandidateIndex && frameCandidateIndex.candidates.length > 0 && (
                <button className="small-button" disabled={!job || isBusy} onClick={onOpenFrameReview} type="button">
                  <Image size={15} />
                  审核配图 · {selectedFrameCandidateCount} 已选
                </button>
              )}
              <button className="small-button strong" disabled={isBusy} onClick={onFinalizeJob} type="button">
                {isFinalizingJob ? <Loader2 className="spin" size={15} /> : <CheckCircle2 size={15} />}
                确认定稿
              </button>
            </div>
          </section>
        )}
        {finalizeError && <InlineMessage kind="error" message={finalizeError} />}
        {downloadMessage && <InlineMessage kind="warning" message={downloadMessage} />}
        {versionError && <InlineMessage kind="error" message={versionError} />}
        {correctionError && !correctionPreview && <InlineMessage kind="error" message={correctionError} />}
        <div className="preview-stack">
          <PreviewBlock
            assetBasePath={previewAssetBasePath}
            title={previewVersion ? `视频笔记 Markdown · ${previewVersion.id}` : "视频笔记 Markdown"}
            titleAction={noteTitleAction}
            text={notePreview}
            empty="完成后显示 note.md 预览"
            jobId={job?.job_id}
          />
          <PreviewBlock
            title="字幕 Markdown"
            titleAction={
              job?.status === "awaiting_subtitle_confirmation" ? (
                <div className="subtitle-title-actions">
                  <button
                    className="small-button"
                    disabled={isRegeneratingSubtitles}
                    onClick={onRegenerateSubtitles}
                    type="button"
                  >
                    {isRegeneratingSubtitles ? <Loader2 className="spin" size={15} /> : <RefreshCw size={15} />}
                    重新生成字幕
                  </button>
                  <button
                    className="small-button strong"
                    disabled={isConfirmingSubtitles}
                    onClick={onConfirmSubtitles}
                    type="button"
                  >
                    {isConfirmingSubtitles ? <Loader2 className="spin" size={15} /> : <CheckCircle2 size={15} />}
                    确认字幕并生成笔记
                  </button>
                </div>
              ) : job?.artifacts.some((artifact) => artifact.path === "transcript.json") ? (
                <button
                  className="small-button"
                  disabled={isBusy || isCorrectingTranscript}
                  onClick={onCreateTranscriptCorrection}
                  type="button"
                >
                  {isCorrectingTranscript ? <Loader2 className="spin" size={15} /> : <Captions size={15} />}
                  AI 修正字幕
                </button>
              ) : null
            }
            text={subtitlePreview}
            empty="字幕生成后显示时间戳预览"
            jobId={job?.job_id}
          />
        </div>

        <CollapsibleBlock className="frame-preview-block" title="关键帧">
          <div className={previewImages.length === 0 ? "frame-grid empty-frame-grid" : "frame-grid"} aria-label="关键帧">
            {previewImages.length === 0 ? (
              <div className="empty-frames">
                <Image size={20} />
                <span>关键帧完成后显示在这里</span>
              </div>
            ) : (
              previewImages.map((artifact) => (
                <figure key={artifact.path}>
                  <img alt={artifact.label} src={artifact.asset_url} />
                  <figcaption>{artifact.label}</figcaption>
                </figure>
              ))
            )}
          </div>
        </CollapsibleBlock>
      </div>
    </section>
  );
}

function InlineMessage({ kind, message }: { kind: "error" | "warning"; message: string }) {
  return (
    <p className={kind === "error" ? "inline-error" : "inline-warning"}>
      <AlertTriangle size={15} />
      {message}
    </p>
  );
}

function DownloadLink({
  job,
  artifactPath,
  label,
  onDownloadError
}: {
  job: JobState | null;
  artifactPath: string;
  label: string;
  onDownloadError: (message: string) => void;
}) {
  const artifact = job?.artifacts.find((item) => item.path === artifactPath);
  if (!artifact) {
    return (
      <button className="small-button" disabled type="button">
        <Download size={15} />
        {label}
      </button>
    );
  }
  return (
    <ArtifactDownloadButton
      filename={deriveDownloadFilename(artifact.path, `${label}.txt`)}
      label={label}
      onError={onDownloadError}
      url={artifact.asset_url}
    />
  );
}

function ArtifactDownloadButton({
  className = "small-button",
  dataDownloadZip,
  filename,
  label,
  onError,
  url
}: {
  className?: string;
  dataDownloadZip?: string;
  filename: string;
  label: string;
  onError: (message: string) => void;
  url: string;
}) {
  async function handleClick() {
    onError("");
    try {
      const result = await downloadArtifact(url, filename);
      if (!result.ok && result.reason !== "cancelled") {
        onError("下载失败，请稍后重试。");
      }
    } catch (error) {
      onError(error instanceof Error ? error.message : "下载失败，请稍后重试。");
    }
  }

  return (
    <button className={className} data-download-zip={dataDownloadZip} onClick={handleClick} type="button">
      <Download size={15} />
      {label}
    </button>
  );
}

function CollapsibleBlock({
  children,
  className = "",
  defaultCollapsed = false,
  title,
  titleAction
}: {
  children: ReactNode;
  className?: string;
  defaultCollapsed?: boolean;
  title: string;
  titleAction?: ReactNode;
}) {
  const [isCollapsed, setIsCollapsed] = useState(defaultCollapsed);
  const sectionClassName = className ? `collapsible-block ${className}` : "collapsible-block";
  return (
    <section className={sectionClassName}>
      <div className="preview-title-row">
        <h3>
          <button
            aria-expanded={!isCollapsed}
            className="collapse-toggle"
            onClick={() => setIsCollapsed((current) => !current)}
            type="button"
          >
            <ChevronDown className={isCollapsed ? "collapsed" : ""} size={16} />
            <span>{title}</span>
          </button>
        </h3>
        {titleAction}
      </div>
      {!isCollapsed && <div className="collapsible-content">{children}</div>}
    </section>
  );
}

function PreviewBlock({
  assetBasePath,
  defaultCollapsed,
  title,
  titleAction,
  text,
  empty,
  jobId
}: {
  assetBasePath?: string;
  defaultCollapsed?: boolean;
  title: string;
  titleAction?: ReactNode;
  text: string;
  empty: string;
  jobId?: string;
}) {
  return (
    <CollapsibleBlock className="preview-block" defaultCollapsed={defaultCollapsed} title={title} titleAction={titleAction}>
      {text ? (
        <MarkdownPreview assetBasePath={assetBasePath} markdown={text} jobId={jobId} />
      ) : (
        <p className="preview-empty">{empty}</p>
      )}
    </CollapsibleBlock>
  );
}

function MarkdownPreview({ assetBasePath, markdown, jobId }: { assetBasePath?: string; markdown: string; jobId?: string }) {
  return (
    <div className="markdown-preview">
      {parseMarkdown(markdown).map((block, index) => {
        if (block.type === "heading") {
          return <MarkdownHeading key={index} level={block.level} text={block.text} />;
        }
        if (block.type === "list") {
          const items = block.items.map((item, itemIndex) => <li key={itemIndex}>{item}</li>);
          return block.ordered ? <ol key={index}>{items}</ol> : <ul key={index}>{items}</ul>;
        }
        if (block.type === "image") {
          const src = resolvePreviewAssetUrl(block.src, jobId, assetBasePath);
          if (!src) {
            return (
              <p className="markdown-unsupported" key={index}>
                {block.alt || block.src}
              </p>
            );
          }
          return (
            <figure className="markdown-image" key={index}>
              <img alt={block.alt} src={src} />
              {block.alt && <figcaption>{block.alt}</figcaption>}
            </figure>
          );
        }
        return <p key={index}>{block.text}</p>;
      })}
    </div>
  );
}

function MarkdownHeading({ level, text }: { level: number; text: string }) {
  if (level === 1) return <h1>{text}</h1>;
  if (level === 2) return <h2>{text}</h2>;
  if (level === 3) return <h3>{text}</h3>;
  if (level === 4) return <h4>{text}</h4>;
  if (level === 5) return <h5>{text}</h5>;
  return <h6>{text}</h6>;
}
