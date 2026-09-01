import { CheckCircle2, Loader2, RefreshCw, X, ZoomIn } from "lucide-react";
import { useEffect, useState } from "react";

import { formatSecondsRange } from "./format";
import type {
  FrameCandidate,
  FrameCandidateIndex,
  NoteChunkIndex,
  NoteChunkMeta,
  ReviewDraft,
  ReviewDraftParagraph,
  ReviewDraftParagraphStatus
} from "./types";

type FrameReviewModalProps = {
  contextByChapter: Map<number, FrameCandidateIndex["chapter_contexts"][number]>;
  groups: [number, FrameCandidate[]][];
  isBusy: boolean;
  jobId: string;
  noteChunks: NoteChunkIndex | null;
  onClose: () => void;
  onRegenerateNote: () => void;
  onRegenerateChunk: (chunkId: string) => void;
  onSaveParagraph: (
    paragraphId: string,
    body: string,
    selectedFrameIds: string[],
    status: ReviewDraftParagraphStatus
  ) => void;
  regeneratingChunkId: string;
  reviewDraft: ReviewDraft;
  savingParagraphId: string;
  selectedCount: number;
};

export function FrameReviewModal({
  contextByChapter,
  groups,
  isBusy,
  jobId,
  noteChunks,
  onClose,
  onRegenerateNote,
  onRegenerateChunk,
  onSaveParagraph,
  regeneratingChunkId,
  reviewDraft,
  savingParagraphId,
  selectedCount
}: FrameReviewModalProps) {
  const chunks = noteChunks?.chunks ?? [];
  const candidatesByChapter = new Map(groups);
  const draftSelectedCount = reviewDraft.paragraphs.reduce(
    (total, paragraph) => total + paragraph.selected_frame_ids.length,
    0
  );
  const [previewCandidate, setPreviewCandidate] = useState<FrameCandidate | null>(null);

  return (
    <div className="modal-backdrop" onMouseDown={onClose}>
      <section
        aria-label="手动审核"
        aria-modal="true"
        className="frame-review-modal"
        onMouseDown={(event) => event.stopPropagation()}
        role="dialog"
      >
        <div className="modal-header">
          <div>
            <p className="eyebrow">Manual Review</p>
            <h2>手动审核</h2>
          </div>
          <div className="frame-review-header-actions">
            <span className="mini-badge ok">{draftSelectedCount || selectedCount} 已选</span>
            <button className="icon-button" onClick={onClose} title="关闭配图审核" type="button">
              <X size={18} />
            </button>
          </div>
        </div>

        <div className="modal-body frame-review-body">
          <p className="frame-review-summary">
            按段落核对最终文案、字幕依据和配图。这里保存的人工审核稿会作为确认定稿的来源。
          </p>
          <div className="frame-candidate-groups">
            {reviewDraft.paragraphs.map((paragraph) => {
              const candidates = candidatesByChapter.get(paragraph.chapter_index) ?? [];
              const context = contextByChapter.get(paragraph.chapter_index);
              const chunk =
                chunks.find((item) =>
                  rangesOverlap(paragraph.start_time, paragraph.end_time, item.start_time, item.end_time)
                ) ?? findChunkForChapterContext(context, chunks);
              const isRegeneratingThisChunk = Boolean(chunk ? regeneratingChunkId === chunk.id : isBusy);
              return (
                <ReviewParagraphEditor
                  candidates={candidates}
                  isBusy={isBusy}
                  isRegenerating={isRegeneratingThisChunk}
                  isSaving={savingParagraphId === paragraph.id}
                  jobId={jobId}
                  key={paragraph.id}
                  onPreviewCandidate={setPreviewCandidate}
                  onRegenerate={() => {
                    chunk ? onRegenerateChunk(chunk.id) : onRegenerateNote();
                  }}
                  onSave={onSaveParagraph}
                  paragraph={paragraph}
                />
              );
            })}
          </div>
        </div>

        <div className="modal-footer">
          <button className="small-button strong" onClick={onClose} type="button">
            完成
          </button>
        </div>
      </section>
      {previewCandidate && (
        <div className="frame-image-preview-backdrop" onMouseDown={(event) => event.stopPropagation()}>
          <section aria-label="候选配图预览" className="frame-image-preview" role="dialog">
            <div className="frame-image-preview-head">
              <div>
                <strong>{formatCandidateTime(previewCandidate.time)}</strong>
                <span>{previewCandidate.reason}</span>
              </div>
              <button className="icon-button" onClick={() => setPreviewCandidate(null)} title="关闭预览" type="button">
                <X size={18} />
              </button>
            </div>
            <div className="frame-image-preview-body">
              <img alt={previewCandidate.reason} src={`/api/jobs/${jobId}/assets/${previewCandidate.path}`} />
              <div className="frame-image-preview-reference">
                <div>
                  <strong>笔记依据</strong>
                  <p>{previewCandidate.note_excerpt || previewCandidate.reason || "暂无笔记依据。"}</p>
                </div>
                <div>
                  <strong>附近字幕</strong>
                  <p>{previewCandidate.subtitle_excerpt || "暂无该时间点附近字幕。"}</p>
                </div>
              </div>
            </div>
          </section>
        </div>
      )}
    </div>
  );
}

function ReviewParagraphEditor({
  candidates,
  isBusy,
  isRegenerating,
  isSaving,
  jobId,
  onPreviewCandidate,
  onRegenerate,
  onSave,
  paragraph
}: {
  candidates: FrameCandidate[];
  isBusy: boolean;
  isRegenerating: boolean;
  isSaving: boolean;
  jobId: string;
  onPreviewCandidate: (candidate: FrameCandidate) => void;
  onRegenerate: () => void;
  onSave: (
    paragraphId: string,
    body: string,
    selectedFrameIds: string[],
    status: ReviewDraftParagraphStatus
  ) => void;
  paragraph: ReviewDraftParagraph;
}) {
  const [body, setBody] = useState(paragraph.body);
  const [selectedFrameIds, setSelectedFrameIds] = useState(paragraph.selected_frame_ids);

  useEffect(() => {
    setBody(paragraph.body);
    setSelectedFrameIds(paragraph.selected_frame_ids);
  }, [paragraph.body, paragraph.id, paragraph.selected_frame_ids]);

  const selectedSet = new Set(selectedFrameIds);
  const hasChanges =
    body.trim() !== paragraph.body.trim() ||
    selectedFrameIds.join("|") !== paragraph.selected_frame_ids.join("|");

  function toggleFrame(candidateId: string) {
    setSelectedFrameIds((current) =>
      current.includes(candidateId) ? current.filter((id) => id !== candidateId) : [...current, candidateId]
    );
  }

  return (
    <section className="frame-candidate-group review-paragraph-group">
      <div className="frame-candidate-group-head">
        <div className="frame-candidate-title-line">
          <strong>{paragraph.title || `第 ${paragraph.chapter_index + 1} 段`}</strong>
          <span>{formatSecondsRange(paragraph.start_time, paragraph.end_time)}</span>
          <span className={`mini-badge ${paragraph.status === "approved" ? "ok" : ""}`}>
            {formatReviewParagraphStatus(paragraph.status)}
          </span>
        </div>
        <div className="frame-candidate-group-actions">
          <button className="small-button" disabled={isBusy || isRegenerating} onClick={onRegenerate} type="button">
            {isRegenerating ? <Loader2 className="spin" size={14} /> : <RefreshCw size={14} />}
            重新生成本段文字
          </button>
          <button
            className="small-button strong"
            disabled={isBusy || isSaving || (!hasChanges && paragraph.status === "approved")}
            onClick={() => onSave(paragraph.id, body, selectedFrameIds, hasChanges ? "edited" : "approved")}
            type="button"
          >
            {isSaving ? <Loader2 className="spin" size={14} /> : <CheckCircle2 size={14} />}
            保存本段
          </button>
          <span>{candidates.length} 个候选</span>
        </div>
      </div>

      <div className="review-paragraph-layout" aria-label="段落审稿">
        <label className="frame-candidate-reference-panel review-paragraph-editor">
          <strong>文案编辑</strong>
          <textarea value={body} onChange={(event) => setBody(event.target.value)} />
        </label>
        <div className="frame-candidate-reference-panel review-subtitle-evidence">
          <strong>字幕依据</strong>
          {!paragraph.evidence_reference_valid && (
            <p className="inline-error">该段字幕证据引用已失效，请重新生成笔记或复核稿。</p>
          )}
          {paragraph.unsupported_numeric_claims.length > 0 && (
            <p className="inline-error">
              字幕中未找到这些数字：{paragraph.unsupported_numeric_claims.join("、")}
            </p>
          )}
          {paragraph.unsupported_technical_identifiers.length > 0 && (
            <p className="field-hint">
              字幕中未找到这些技术标识：{paragraph.unsupported_technical_identifiers.join("、")}
            </p>
          )}
          <textarea
            aria-label="字幕依据内容"
            className="review-subtitle-textarea"
            readOnly
            value={formatReviewSubtitleEvidence(paragraph.subtitle_segments)}
          />
        </div>

        <div className="review-frame-column">
          <strong>配图</strong>
          {candidates.length === 0 ? (
            <p className="frame-candidate-empty">本段暂无候选配图。</p>
          ) : (
            <div className="frame-candidate-strip review-frame-list">
              {candidates.map((candidate) => {
                const isSelected = selectedSet.has(candidate.id);
                return (
                  <article
                    className={`frame-candidate-card ${isSelected ? "selected" : ""} ${candidate.rejected ? "rejected" : ""}`}
                    key={candidate.id}
                  >
                    <div className="frame-image-wrap">
                      <label className="frame-candidate-check">
                        <input
                          checked={isSelected}
                          disabled={isBusy || isSaving}
                          onChange={() => toggleFrame(candidate.id)}
                          type="checkbox"
                        />
                      </label>
                      <img alt={candidate.reason} src={`/api/jobs/${jobId}/assets/${candidate.path}`} />
                      <button
                        aria-label={`放大预览 ${formatCandidateTime(candidate.time)}`}
                        className="frame-candidate-zoom"
                        onClick={() => onPreviewCandidate(candidate)}
                        title="放大预览"
                        type="button"
                      >
                        <ZoomIn size={15} />
                      </button>
                    </div>
                    <div className="frame-candidate-body">
                      <div className="frame-candidate-meta">
                        <span>{formatCandidateTime(candidate.time)}</span>
                        <span className="mini-badge">{formatCandidateSource(candidate.source)}</span>
                        <span className={candidate.quality_score < 0.5 ? "mini-badge warn" : "mini-badge"}>
                          画质 {Math.round(candidate.quality_score * 100)}%
                        </span>
                        {candidate.scene_sample_count > 0 && (
                          <span className={candidate.stability_score < 0.5 ? "mini-badge warn" : "mini-badge"}>
                            稳定 {Math.round(candidate.stability_score * 100)}%
                          </span>
                        )}
                        {Math.abs(candidate.time_offset) >= 0.1 && (
                          <span className="mini-badge">
                            锚点{candidate.time_offset > 0 ? "+" : ""}
                            {candidate.time_offset.toFixed(1)}s
                          </span>
                        )}
                        {candidate.similarity > 0 && (
                          <span className="mini-badge">相似度 {Math.round(candidate.similarity * 100)}%</span>
                        )}
                        {isSelected && <span className="mini-badge ok">已选</span>}
                        {candidate.rejected && <span className="mini-badge warn">已拒绝</span>}
                        {candidate.risk_flags.map((flag) => (
                          <span className="mini-badge warn" key={flag}>
                            {formatCandidateRisk(flag)}
                          </span>
                        ))}
                      </div>
                    </div>
                  </article>
                );
              })}
            </div>
          )}
        </div>
      </div>
    </section>
  );
}

function findChunkForChapterContext(
  context: FrameCandidateIndex["chapter_contexts"][number] | undefined,
  chunks: NoteChunkMeta[]
) {
  if (!context || chunks.length === 0) {
    return null;
  }
  const midpoint = (context.start_time + context.end_time) / 2;
  return (
    chunks.find((chunk) =>
      rangesOverlap(context.start_time, context.end_time, chunk.start_time, chunk.end_time)
    ) ??
    chunks.find((chunk) => chunk.start_time <= midpoint && midpoint <= chunk.end_time) ??
    null
  );
}

function rangesOverlap(leftStart: number, leftEnd: number, rightStart: number, rightEnd: number) {
  return Math.max(leftStart, rightStart) <= Math.min(leftEnd, rightEnd);
}

function formatCandidateTime(value: number) {
  const seconds = Math.max(0, Math.floor(value));
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  const remainingSeconds = seconds % 60;
  return [hours, minutes, remainingSeconds].map((part) => String(part).padStart(2, "0")).join(":");
}

function formatCandidateSource(source: FrameCandidate["source"]) {
  return source === "note_key_moment" ? "笔记关键点" : "兜底推荐";
}

function formatCandidateRisk(flag: string) {
  const labels: Record<string, string> = {
    duplicate_frame: "重复风险",
    black_frame: "黑屏风险",
    white_frame: "白屏风险",
    underexposed: "画面偏暗",
    overexposed: "画面过曝",
    low_contrast: "对比度低",
    blurry_frame: "可能模糊",
    transition_frame: "转场风险"
  };
  return labels[flag] ?? flag;
}

function formatReviewParagraphStatus(status: ReviewDraftParagraphStatus) {
  if (status === "approved") {
    return "已确认";
  }
  if (status === "edited") {
    return "已修改";
  }
  return "待审核";
}

function formatReviewSubtitleEvidence(segments: ReviewDraftParagraph["subtitle_segments"]) {
  if (segments.length === 0) {
    return "暂无可用字幕片段。";
  }
  return segments.map((segment) => `${formatSecondsRange(segment.start, segment.end)}  ${segment.text}`).join("\n");
}
