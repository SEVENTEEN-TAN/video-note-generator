import { noteStyleOptions } from "./constants";
import type { NoteVersion, PythonPackageInstallMode, RuntimePathSource } from "./types";

export function formatElapsedSeconds(seconds?: number): string {
  if (!seconds || seconds < 1) {
    return "少于 1 秒";
  }

  const totalSeconds = Math.floor(seconds);
  const minutes = Math.floor(totalSeconds / 60);
  const restSeconds = totalSeconds % 60;

  if (minutes === 0) {
    return `${restSeconds} 秒`;
  }

  return `${minutes} 分 ${restSeconds} 秒`;
}

export function formatSecondsRange(start: number, end: number): string {
  const format = (value: number) => {
    const totalSeconds = Math.max(0, Math.floor(value));
    const hours = Math.floor(totalSeconds / 3600);
    const minutes = Math.floor((totalSeconds % 3600) / 60);
    const seconds = totalSeconds % 60;
    return [hours, minutes, seconds].map((part) => String(part).padStart(2, "0")).join(":");
  };
  return `${format(start)} - ${format(end)}`;
}

export function formatUpdateTime(value?: string | null): string {
  if (!value) {
    return "暂无";
  }

  return new Date(value).toLocaleTimeString();
}

export function formatHistoryTime(value?: string | null): string {
  if (!value) {
    return "未知时间";
  }
  return new Date(value).toLocaleString();
}

export function formatVersionOption(version: NoteVersion): string {
  return version.id;
}

export function formatVersionDetails(version: NoteVersion): string {
  const createdAt = formatHistoryTime(version.created_at);
  const style = noteStyleOptions.find((option) => option.value === version.note_style)?.label ?? version.note_style;
  return `${style} · ${createdAt} · ${version.note_model}`;
}

export function formatRuntimeSource(source?: RuntimePathSource): string {
  if (source === "environment") return "环境变量";
  if (source === "settings") return "本地设置";
  if (source === "default") return "默认检测";
  return "未找到";
}

export function formatInstallMode(mode?: PythonPackageInstallMode): string {
  if (mode === "user") return "用户目录 (--user)";
  return "默认 pip 安装";
}
