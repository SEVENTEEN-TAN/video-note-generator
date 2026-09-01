import { AlertTriangle } from "lucide-react";

import type { QualityReport } from "./types";

export function QualityStatusControl({ report }: { report: QualityReport }) {
  const visibleIssues = report.issues.slice(0, 4);
  return (
    <div className="quality-status-control">
      <button className={`quality-status ${report.status}`} type="button">
        {formatQualityStatus(report.status)}
      </button>
      <div className="quality-popover" role="tooltip">
        <div className="quality-popover-head">
          <strong>质量复核</strong>
          <span>覆盖、结构、配图、稳定性、证据</span>
        </div>
        <div className="quality-score-grid">
          <QualityScore label="覆盖" value={report.scores.coverage} />
          <QualityScore label="结构" value={report.scores.structure} />
          <QualityScore label="配图" value={report.scores.frames} />
          <QualityScore label="稳定性" value={report.scores.stability} />
          <QualityScore label="证据" value={report.scores.evidence} />
        </div>
        {visibleIssues.length > 0 ? (
          <div className="quality-issues">
            {visibleIssues.map((issue, index) => (
              <div
                className={`quality-issue ${issue.severity}`}
                key={`${issue.type}-${issue.chapter_index ?? "global"}-${index}`}
              >
                <AlertTriangle size={14} />
                <span>
                  {issue.chapter_index !== null && issue.chapter_index !== undefined
                    ? `第 ${issue.chapter_index + 1} 章 · `
                    : ""}
                  {formatQualityIssueType(issue.type)}：{issue.message}
                </span>
              </div>
            ))}
            {report.issues.length > visibleIssues.length && (
              <span className="quality-more">还有 {report.issues.length - visibleIssues.length} 个风险项</span>
            )}
          </div>
        ) : (
          <p className="quality-empty">没有发现可测量的覆盖、配图或证据风险。</p>
        )}
      </div>
    </div>
  );
}

function QualityScore({ label, value }: { label: string; value: number }) {
  return (
    <div>
      <span>{label}</span>
      <strong>{Math.round(value * 100)}%</strong>
    </div>
  );
}

function formatQualityStatus(status: QualityReport["status"]) {
  if (status === "ready") {
    return "可交付";
  }
  if (status === "needs_attention") {
    return "需要处理";
  }
  return "建议复核";
}

function formatQualityIssueType(type: string) {
  const labels: Record<string, string> = {
    low_chapter_coverage: "章节覆盖偏薄",
    missing_chapter_frame: "章节缺少配图",
    missing_timestamp_reference: "缺少引用时间",
    duplicate_frame_reference: "重复配图",
    selected_frame_visual_risk: "候选帧画质风险",
    stale_evidence_transcript: "证据对应的字幕已变化",
    invalid_chapter_evidence_reference: "章节证据引用失效",
    invalid_key_moment_evidence_reference: "关键帧证据引用失效",
    unsupported_numeric_evidence: "数字缺少字幕证据",
    unsupported_technical_identifier: "技术标识缺少字幕证据",
    generation_instability: "生成不稳定"
  };
  return labels[type] ?? type;
}
