import { FileText, KeyRound } from "lucide-react";

import { OPENAI_BASE_URL, QWEN_BASE_URL } from "./constants";

export type SettingsNoteApiSectionProps = {
  apiKey: string;
  baseUrl: string;
  model: string;
  onApiKeyChange: (value: string) => void;
  onBaseUrlChange: (value: string) => void;
  onModelChange: (value: string) => void;
};

export function SettingsNoteApiSection({
  apiKey,
  baseUrl,
  model,
  onApiKeyChange,
  onBaseUrlChange,
  onModelChange
}: SettingsNoteApiSectionProps) {
  return (
    <section className="api-section">
      <div className="section-title">
        <FileText size={16} />
        <span>笔记生成 API</span>
      </div>
      <p className="field-help">用于把字幕整理为结构化笔记。可填 OpenAI、Qwen 或其他 OpenAI-compatible Chat API。</p>
      <div className="preset-row" aria-label="常用 Base URL">
        <button type="button" onClick={() => onBaseUrlChange(OPENAI_BASE_URL)}>
          OpenAI
        </button>
        <button type="button" onClick={() => onBaseUrlChange(QWEN_BASE_URL)}>
          Qwen
        </button>
      </div>
      <label className="field">
        <span className="field-label">Base URL</span>
        <input value={baseUrl} onChange={(event) => onBaseUrlChange(event.target.value)} />
      </label>
      <label className="field">
        <span className="field-label">笔记模型</span>
        <input value={model} onChange={(event) => onModelChange(event.target.value)} />
      </label>
      <label className="field">
        <span className="field-label">
          <KeyRound size={15} />
          笔记 API Key
        </span>
        <input
          autoComplete="off"
          placeholder="可保存到本地设置"
          type="password"
          value={apiKey}
          onChange={(event) => onApiKeyChange(event.target.value)}
        />
      </label>
    </section>
  );
}
