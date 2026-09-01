import { AlertTriangle, CheckCircle2, Loader2, X } from "lucide-react";

import { formatSecondsRange } from "./format";
import type { TranscriptCorrectionPreview } from "./types";

export function TranscriptCorrectionModal({
  error,
  isApplying,
  onApply,
  onClose,
  preview
}: {
  error: string;
  isApplying: boolean;
  onApply: () => void;
  onClose: () => void;
  preview: TranscriptCorrectionPreview | null;
}) {
  if (!preview) {
    return null;
  }
  return (
    <div className="modal-backdrop" onMouseDown={onClose}>
      <section
        className="settings-modal correction-modal"
        aria-label="AI 字幕修正对比"
        onMouseDown={(event) => event.stopPropagation()}
      >
        <div className="modal-header">
          <div>
            <p className="eyebrow">Transcript correction</p>
            <h2>AI 字幕修正对比</h2>
          </div>
          <button className="icon-button" disabled={isApplying} onClick={onClose} type="button">
            <X size={18} />
          </button>
        </div>

        <div className="modal-body correction-body">
          <p className="correction-summary">
            共 {preview.segments.length} 段，AI 建议修改 {preview.changed_count} 段。采用后会重写字幕文件，并基于修正版生成新的笔记版本。
          </p>
          {error && (
            <p className="inline-error">
              <AlertTriangle size={15} />
              {error}
            </p>
          )}
          <div className="correction-diff-grid">
            <div className="correction-column-title">原始字幕</div>
            <div className="correction-column-title">AI 修正版</div>
            {preview.segments.map((segment) => (
              <div className="correction-row-pair" key={segment.index}>
                <div className={segment.changed ? "correction-row changed" : "correction-row"}>
                  <strong>{formatSecondsRange(segment.start, segment.end)}</strong>
                  <span>{segment.original_text}</span>
                </div>
                <div className={segment.changed ? "correction-row changed" : "correction-row"}>
                  <strong>{formatSecondsRange(segment.start, segment.end)}</strong>
                  <span>{segment.corrected_text}</span>
                </div>
              </div>
            ))}
          </div>
        </div>

        <div className="modal-footer">
          <button className="small-button" disabled={isApplying} onClick={onClose} type="button">
            取消
          </button>
          <button className="small-button strong" disabled={isApplying} onClick={onApply} type="button">
            {isApplying ? <Loader2 className="spin" size={15} /> : <CheckCircle2 size={15} />}
            采用修正版并重新生成笔记
          </button>
        </div>
      </section>
    </div>
  );
}
