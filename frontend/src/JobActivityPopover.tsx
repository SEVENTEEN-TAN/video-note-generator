import { Activity, Loader2 } from "lucide-react";
import { useEffect, useState } from "react";

import { fetchJobActivity } from "./api";
import type { JobActivitySnapshot, JobState } from "./types";

export function JobActivityPopover({ job }: { job: JobState | null }) {
  const [isOpen, setIsOpen] = useState(false);
  const [activity, setActivity] = useState<JobActivitySnapshot | null>(null);
  const [error, setError] = useState("");
  const [isLoading, setIsLoading] = useState(false);

  useEffect(() => {
    setActivity(null);
    setError("");
  }, [job?.job_id]);

  useEffect(() => {
    if (!isOpen || !job?.job_id) {
      return;
    }
    const jobId = job.job_id;
    const isActive = job.status === "pending" || job.status === "running" || job.status === "cancelling";
    let stopped = false;
    let timer: number | undefined;
    let controller: AbortController | null = null;

    const load = async () => {
      controller = new AbortController();
      setIsLoading(true);
      try {
        const nextActivity = await fetchJobActivity(jobId, controller.signal);
        if (!stopped) {
          setActivity(nextActivity);
          setError("");
        }
      } catch (loadError) {
        if (!stopped && !isAbortError(loadError)) {
          setError(loadError instanceof Error ? loadError.message : "任务执行日志读取失败。");
        }
      } finally {
        if (!stopped) {
          setIsLoading(false);
          if (isActive) {
            timer = window.setTimeout(() => void load(), 1600);
          }
        }
      }
    };

    void load();
    return () => {
      stopped = true;
      controller?.abort();
      if (timer !== undefined) {
        window.clearTimeout(timer);
      }
    };
  }, [isOpen, job?.job_id, job?.status]);

  if (!job) {
    return null;
  }

  const latestEvent = activity?.events.at(-1);
  const waitingForAI = latestEvent?.stage === "note_model_call" && latestEvent.message === "requesting";
  return (
    <span
      className={`job-activity-control${isOpen ? " open" : ""}`}
      onBlur={(event) => {
        if (!event.currentTarget.contains(event.relatedTarget)) {
          setIsOpen(false);
        }
      }}
      onFocus={() => setIsOpen(true)}
      onMouseEnter={() => setIsOpen(true)}
      onMouseLeave={() => setIsOpen(false)}
    >
      <button
        aria-expanded={isOpen}
        aria-label="查看实时执行日志"
        className="job-activity-trigger"
        onClick={() => setIsOpen(true)}
        title="悬浮查看实时执行日志"
        type="button"
      >
        <Activity size={13} />
      </button>
      <span className="job-activity-popover" role="tooltip">
        <span className="job-activity-head">
          <span>
            <strong>实时执行日志</strong>
            <small>{waitingForAI ? "正在等待 AI 返回" : "悬浮时自动刷新"}</small>
          </span>
          {isLoading && <Loader2 className="spin" size={14} />}
        </span>

        {activity ? (
          <>
            <span className="job-activity-current">
              <small>当前进度</small>
              <strong>{formatContext(activity.current_context, job.step)}</strong>
            </span>
            <span className="job-activity-stats">
              <ActivityStat label="AI 请求" value={activity.request_count} />
              <ActivityStat label="已返回" value={activity.response_count} />
              <ActivityStat label="格式重试" value={activity.format_failure_count} />
              <ActivityStat label="拆分" value={activity.binary_split_count} />
            </span>
            {activity.events.length > 0 ? (
              <span className="job-activity-events">
                {activity.events.map((event, index) => (
                  <span className={`job-activity-event ${event.level.toLowerCase()}`} key={`${event.timestamp}-${index}`}>
                    <time>{formatLogTime(event.timestamp)}</time>
                    <span>{event.summary}</span>
                  </span>
                ))}
              </span>
            ) : (
              <span className="job-activity-empty">当前阶段还没有可展示的详细日志。</span>
            )}
          </>
        ) : error ? (
          <span className="job-activity-error">{error}</span>
        ) : (
          <span className="job-activity-empty">正在读取执行日志…</span>
        )}
      </span>
    </span>
  );
}

function ActivityStat({ label, value }: { label: string; value: number }) {
  return (
    <span>
      <small>{label}</small>
      <strong>{value}</strong>
    </span>
  );
}

function formatContext(context: string, fallback: string) {
  if (context === "note-reduce") {
    return "整合最终笔记";
  }
  const match = context.match(/^note-chunk-(\d+)-of-(\d+)(.*)$/);
  if (match) {
    const splitDepth = (match[3].match(/-(?:left|right)/g) ?? []).length;
    return `笔记块 ${match[1]}/${match[2]}${splitDepth > 0 ? ` · 拆分层级 ${splitDepth}` : ""}`;
  }
  return context || fallback || "等待任务开始";
}

function formatLogTime(value: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return "--:--:--";
  }
  return date.toLocaleTimeString("zh-CN", { hour12: false });
}

function isAbortError(error: unknown): boolean {
  return error instanceof Error && error.name === "AbortError";
}
