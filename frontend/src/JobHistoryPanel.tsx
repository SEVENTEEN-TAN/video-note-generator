import { AlertTriangle, FolderOpen, History, Loader2, RefreshCw, Trash2 } from "lucide-react";
import { useMemo, useState } from "react";

import { statusText } from "./constants";
import { formatHistoryTime } from "./format";
import type { HealthState, JobState, JobStatus, JobSummary } from "./types";

type Props = {
  activeJob: JobState | null;
  busy: boolean;
  deletingJobId: string;
  error: string;
  health: HealthState | null;
  history: JobSummary[];
  loading: boolean;
  onDelete: (jobId: string) => void;
  onLoad: (jobId: string) => void;
  onRefresh: () => void;
};

export function JobHistoryPanel({
  activeJob,
  busy,
  deletingJobId,
  error,
  health,
  history,
  loading,
  onDelete,
  onLoad,
  onRefresh
}: Props) {
  const [query, setQuery] = useState("");
  const [status, setStatus] = useState<"all" | JobStatus>("all");
  const filteredHistory = useMemo(() => {
    const normalized = query.trim().toLowerCase();
    return history.filter(
      (item) =>
        (status === "all" || item.status === status) &&
        (!normalized ||
          item.title.toLowerCase().includes(normalized) ||
          item.original_filename.toLowerCase().includes(normalized))
    );
  }, [history, query, status]);

  return (
    <section className="panel history-panel history-column" aria-label="历史任务">
      <div className="history-header">
        <div className="section-title">
          <History size={16} />
          <span>历史任务</span>
        </div>
        <button className="small-button" disabled={loading} onClick={onRefresh} type="button">
          {loading ? <Loader2 className="spin" size={15} /> : <RefreshCw size={15} />}
          刷新
        </button>
      </div>

      <div className="history-controls">
        <input
          aria-label="搜索历史任务"
          onChange={(event) => setQuery(event.target.value)}
          placeholder="搜索任务"
          type="search"
          value={query}
        />
        <select
          aria-label="筛选任务状态"
          onChange={(event) => setStatus(event.target.value as "all" | JobStatus)}
          value={status}
        >
          <option value="all">全部状态</option>
          <option value="pending">等待处理</option>
          <option value="running">处理中</option>
          <option value="cancelling">正在取消</option>
          <option value="awaiting_subtitle_confirmation">待确认字幕</option>
          <option value="awaiting_note_review">待复核笔记</option>
          <option value="succeeded">已完成</option>
          <option value="failed">失败</option>
          <option value="cancelled">已取消</option>
        </select>
      </div>

      {error && health && (
        <p className="inline-error">
          <AlertTriangle size={15} />
          {error}
        </p>
      )}

      {filteredHistory.length === 0 ? (
        <div className="empty-history">
          <strong>{health ? "暂无历史任务" : "等待服务连接"}</strong>
          <span>{health ? "任务创建后会保存在这里。" : "连接后可读取本地任务记录。"}</span>
        </div>
      ) : (
        <div className="history-list">
          {filteredHistory.map((item) => (
            <article
              className={`history-item ${activeJob?.job_id === item.job_id ? "active" : ""}`}
              key={item.job_id}
              onClick={(event) => {
                if (!(event.target as HTMLElement).closest("button")) {
                  onLoad(item.job_id);
                }
              }}
              onKeyDown={(event) => {
                if ((event.target as HTMLElement).closest("button")) {
                  return;
                }
                if (event.key === "Enter" || event.key === " ") {
                  event.preventDefault();
                  onLoad(item.job_id);
                }
              }}
              role="button"
              tabIndex={0}
            >
              <div className="history-item-main">
                <div>
                  <strong>{item.title || item.original_filename}</strong>
                  <span>{item.original_filename}</span>
                </div>
                <span className={`badge ${item.status}`}>{statusText[item.status]}</span>
              </div>
              {item.status === "failed" && item.error && (
                <p className="history-item-error">
                  <AlertTriangle size={14} />
                  <span>{item.error}</span>
                </p>
              )}
              <div className="history-meta">
                <span>{formatHistoryTime(item.updated_at ?? item.created_at)}</span>
                <span>{item.note_version_count} 个版本</span>
                <span>{item.artifact_count} 个产物</span>
              </div>
              <div className="history-actions">
                <button className="small-button" disabled={busy} onClick={() => onLoad(item.job_id)} type="button">
                  <FolderOpen size={15} />载入
                </button>
                <button
                  className="small-button danger"
                  disabled={busy || deletingJobId === item.job_id}
                  onClick={() => onDelete(item.job_id)}
                  type="button"
                >
                  {deletingJobId === item.job_id ? <Loader2 className="spin" size={15} /> : <Trash2 size={15} />}
                  删除
                </button>
              </div>
            </article>
          ))}
        </div>
      )}
    </section>
  );
}
