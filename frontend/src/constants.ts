import type { JobStatus, NoteStyle } from "./types";

export const OPENAI_BASE_URL = "https://api.openai.com/v1";
export const QWEN_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1";

export const statusText: Record<JobStatus, string> = {
  pending: "等待",
  running: "处理中",
  awaiting_subtitle_confirmation: "待确认字幕",
  awaiting_note_review: "待复核笔记",
  succeeded: "完成",
  failed: "失败"
};

export const noteStyleOptions: Array<{ value: NoteStyle; label: string }> = [
  { value: "minimal", label: "minimal（极简）" },
  { value: "detailed", label: "detailed（详细）" },
  { value: "tutorial", label: "tutorial（教程）" },
  { value: "academic", label: "academic（学术）" },
  { value: "task_oriented", label: "task_oriented（任务导向）" },
  { value: "meeting_minutes", label: "meeting_minutes（会议纪要）" }
];
