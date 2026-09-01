import { CheckCircle2, Loader2, Server, X } from "lucide-react";

import { RuntimeStatusCard } from "./RuntimeStatus";
import { SettingsNoteApiSection } from "./SettingsNoteApiSection";
import type { SettingsNoteApiSectionProps } from "./SettingsNoteApiSection";
import { SettingsTranscriptionSection } from "./SettingsTranscriptionSection";
import type { SettingsTranscriptionSectionProps } from "./SettingsTranscriptionSection";
import type { HealthState } from "./types";

type SettingsModalProps = {
  health: HealthState | null;
  modal: {
    isOpen: boolean;
    isSaving: boolean;
    message: string;
    onClear: () => void;
    onClose: () => void;
    onSave: () => void;
  };
  note: SettingsNoteApiSectionProps;
  transcription: Omit<SettingsTranscriptionSectionProps, "health">;
};

export function SettingsModal({ health, modal, note, transcription }: SettingsModalProps) {
  const { isOpen, isSaving, message, onClear, onClose, onSave } = modal;
  if (!isOpen) {
    return null;
  }

  return (
    <div className="modal-backdrop" onMouseDown={onClose}>
      <section
        aria-label="设置"
        aria-modal="true"
        className="settings-modal"
        onMouseDown={(event) => event.stopPropagation()}
        role="dialog"
      >
        <div className="modal-header">
          <div>
            <p className="eyebrow">Local Settings</p>
            <h2>模型与运行环境设置</h2>
          </div>
          <button className="icon-button" onClick={onClose} title="关闭设置" type="button">
            <X size={18} />
          </button>
        </div>

        <div className="modal-body">
          <section className="settings-strip" aria-label="本地设置">
            <div>
              <strong>本地配置文件</strong>
              <span title={health?.runtime?.settings.path}>
                保存 Base URL、模型和 API Key。{health?.runtime?.settings.warning || "API Key 会使用系统凭据保护后写入本机配置。"}
              </span>
            </div>
            <div className="settings-actions">
              <button className="small-button strong" disabled={isSaving} onClick={onSave} type="button">
                {isSaving ? <Loader2 className="spin" size={15} /> : <CheckCircle2 size={15} />}
                保存设置
              </button>
              <button className="small-button" disabled={isSaving} onClick={onClear} type="button">
                清除设置
              </button>
            </div>
            {message && <p className="settings-message">{message}</p>}
          </section>

          <SettingsTranscriptionSection health={health} {...transcription} />
          <SettingsNoteApiSection {...note} />

          <section className="api-section">
            <div className="section-title">
              <Server size={16} />
              <span>运行环境</span>
            </div>
            <RuntimeStatusCard runtime={health?.runtime ?? null} />
          </section>
        </div>

        <div className="modal-footer">
          <button className="small-button" onClick={onClose} type="button">
            关闭
          </button>
          <button className="small-button strong" disabled={isSaving} onClick={onSave} type="button">
            {isSaving ? <Loader2 className="spin" size={15} /> : <CheckCircle2 size={15} />}
            保存设置
          </button>
        </div>
      </section>
    </div>
  );
}
