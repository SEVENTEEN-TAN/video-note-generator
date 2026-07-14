import type { JobStatus, NoteStyle } from "./types";

export const OPENAI_BASE_URL = "https://api.openai.com/v1";
export const QWEN_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1";

export const statusText: Record<JobStatus, string> = {
  pending: "等待",
  running: "处理中",
  cancelling: "正在取消",
  awaiting_subtitle_confirmation: "待确认字幕",
  awaiting_note_review: "待复核笔记",
  succeeded: "完成",
  failed: "失败",
  cancelled: "已取消"
};

export const noteStyleOptions: Array<{ value: NoteStyle; label: string }> = [
  { value: "minimal", label: "极简摘要" },
  { value: "detailed", label: "详细笔记" },
  { value: "tutorial", label: "操作教程" },
  { value: "academic", label: "学术整理" },
  { value: "task_oriented", label: "任务导向" },
  { value: "meeting_minutes", label: "会议纪要" }
];
