import { AlertTriangle, Captions, Loader2, Play, RefreshCw, Upload, X } from "lucide-react";
import type { ChangeEventHandler, RefObject } from "react";

import { noteStyleOptions } from "./constants";
import type { JobState, NoteLanguage, NoteStyle } from "./types";

type TaskConfigPanelProps = {
  extras: string;
  frameLimit: number;
  isBusy: boolean;
  job: JobState | null;
  noteLanguage: NoteLanguage;
  noteStyle: NoteStyle;
  onCancelJob: () => void;
  onClearSubtitle: () => void;
  onExtrasChange: (value: string) => void;
  onFrameLimitChange: (value: number) => void;
  onNoteLanguageChange: (value: NoteLanguage) => void;
  onNoteStyleChange: (value: NoteStyle) => void;
  onResumeTranscription: () => void;
  onSubtitleChange: ChangeEventHandler<HTMLInputElement>;
  onVideoChange: ChangeEventHandler<HTMLInputElement>;
  serviceConnected: boolean;
  subtitle: File | null;
  subtitleInputRef: RefObject<HTMLInputElement>;
  submitError: string;
  video: File | null;
  videoInputRef: RefObject<HTMLInputElement>;
};

export function TaskConfigPanel({
  extras,
  frameLimit,
  isBusy,
  job,
  noteLanguage,
  noteStyle,
  onCancelJob,
  onClearSubtitle,
  onExtrasChange,
  onFrameLimitChange,
  onNoteLanguageChange,
  onNoteStyleChange,
  onResumeTranscription,
  onSubtitleChange,
  onVideoChange,
  serviceConnected,
  subtitle,
  subtitleInputRef,
  submitError,
  video,
  videoInputRef
}: TaskConfigPanelProps) {
  return (
    <section className="panel config-panel task-config-panel" aria-label="任务配置">
      <div className="panel-title">
        <Upload size={18} />
        <h2>视频与笔记要求</h2>
      </div>

      <div className="config-main">
        <div className="video-config-block">
          <div className="upload-field">
            <label className="drop-zone">
              <input
                accept=".mp4,.mov,.mkv,.webm,.avi,video/*"
                ref={videoInputRef}
                type="file"
                onChange={onVideoChange}
              />
              <Upload size={18} />
              <span>{video ? `视频文件：${video.name}` : "视频文件：选择文件"}</span>
            </label>
          </div>
          <div className="upload-field subtitle-upload-field">
            <div className="subtitle-upload-row">
              <label className="drop-zone subtitle-drop-zone">
                <input accept=".srt" ref={subtitleInputRef} type="file" onChange={onSubtitleChange} />
                <Captions size={18} />
                <span>{subtitle ? `已有字幕（可选）：${subtitle.name}` : "已有字幕（可选）：选择 SRT 字幕"}</span>
              </label>
              {subtitle && (
                <button
                  className="icon-button subtitle-clear-button"
                  onClick={onClearSubtitle}
                  title="移除字幕"
                  type="button"
                >
                  <X size={16} />
                </button>
              )}
            </div>
          </div>
        </div>

        <div className="quick-settings">
          <label className="field">
            <span className="field-label">笔记语言</span>
            <select value={noteLanguage} onChange={(event) => onNoteLanguageChange(event.target.value as NoteLanguage)}>
              <option value="zh">中文</option>
              <option value="en">英文</option>
              <option value="follow">跟随原文</option>
            </select>
          </label>

          <label className="field">
            <span className="field-label">笔记风格</span>
            <select value={noteStyle} onChange={(event) => onNoteStyleChange(event.target.value as NoteStyle)}>
              {noteStyleOptions.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </label>

          <label className="field">
            <span className="field-label">关键帧上限</span>
            <input
              max={24}
              min={1}
              type="number"
              value={frameLimit}
              onChange={(event) => onFrameLimitChange(Number(event.target.value))}
            />
          </label>
        </div>

        <label className="field extras-field">
          <span className="field-label">额外笔记要求</span>
          <input
            maxLength={2000}
            onChange={(event) => onExtrasChange(event.target.value)}
            placeholder="例如：突出操作步骤、保留关键术语、最后补一组行动项"
            type="text"
            value={extras}
          />
        </label>

        <div className="config-submit-block">
          {submitError && (
            <p className="inline-error">
              <AlertTriangle size={15} />
              {submitError}
            </p>
          )}

          <div className="primary-action-stack">
            <button
              className="primary-button"
              disabled={isBusy || !serviceConnected}
              title={!serviceConnected ? "服务未连接，暂时无法创建任务" : undefined}
              type="submit"
            >
              {isBusy ? <Loader2 className="spin" size={18} /> : <Play size={18} />}
              {!serviceConnected ? "服务未连接" : "开始生成"}
            </button>
            {(job?.status === "pending" || job?.status === "running") && (
              <button className="small-button danger cancel-job-button" onClick={onCancelJob} type="button">
                <X size={15} />取消任务
              </button>
            )}
            {job?.status === "cancelling" && (
              <button className="small-button cancel-job-button" disabled type="button">
                <Loader2 className="spin" size={15} />正在取消
              </button>
            )}
            {(job?.status === "cancelled" || job?.status === "failed") && job.work_progress?.resumable && (
              <button className="small-button cancel-job-button" onClick={onResumeTranscription} type="button">
                <RefreshCw size={15} />继续转写
              </button>
            )}
          </div>
        </div>
      </div>
    </section>
  );
}
