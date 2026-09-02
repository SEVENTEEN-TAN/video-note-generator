import { FileText, KeyRound } from "lucide-react";

import {
  BIGMODEL_ANTHROPIC_BASE_URL,
  BIGMODEL_CHAT_BASE_URL,
  BIGMODEL_RESPONSES_BASE_URL,
  OPENAI_BASE_URL,
  QWEN_BASE_URL,
  aiProtocolOptions
} from "./constants";
import type { AIModelInfo, AIProtocol } from "./types";

export type SettingsNoteApiSectionProps = {
  apiKey: string;
  baseUrl: string;
  isLoadingModels: boolean;
  model: string;
  modelError: string;
  models: AIModelInfo[];
  protocol: AIProtocol;
  onApiKeyChange: (value: string) => void;
  onBaseUrlChange: (value: string) => void;
  onModelChange: (value: string) => void;
  onProtocolChange: (value: AIProtocol) => void;
  onRefreshModels: () => void;
};

export function SettingsNoteApiSection({
  apiKey,
  baseUrl,
  isLoadingModels,
  model,
  modelError,
  models,
  protocol,
  onApiKeyChange,
  onBaseUrlChange,
  onModelChange,
  onProtocolChange,
  onRefreshModels
}: SettingsNoteApiSectionProps) {
  function applyPreset(nextProtocol: AIProtocol, nextBaseUrl: string) {
    onProtocolChange(nextProtocol);
    onBaseUrlChange(nextBaseUrl);
  }

  return (
    <section className="api-section">
      <div className="section-title">
        <FileText size={16} />
        <span>笔记生成 API</span>
      </div>
      <p className="field-help">支持 OpenAI Chat Completions、OpenAI Responses 和 Anthropic Messages 协议。</p>
      <label className="field">
        <span className="field-label">接口协议</span>
        <select value={protocol} onChange={(event) => onProtocolChange(event.target.value as AIProtocol)}>
          {aiProtocolOptions.map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </select>
      </label>
      <div className="preset-row" aria-label="常用 Base URL">
        <button type="button" onClick={() => applyPreset("openai_chat_completions", OPENAI_BASE_URL)}>
          OpenAI
        </button>
        <button type="button" onClick={() => applyPreset("openai_chat_completions", QWEN_BASE_URL)}>
          Qwen
        </button>
        <button type="button" onClick={() => applyPreset("openai_chat_completions", BIGMODEL_CHAT_BASE_URL)}>
          智谱 Chat
        </button>
        <button type="button" onClick={() => applyPreset("openai_responses", BIGMODEL_RESPONSES_BASE_URL)}>
          智谱 Responses
        </button>
        <button type="button" onClick={() => applyPreset("anthropic_messages", BIGMODEL_ANTHROPIC_BASE_URL)}>
          智谱 Anthropic
        </button>
      </div>
      <label className="field">
        <span className="field-label">Base URL</span>
        <input value={baseUrl} onChange={(event) => onBaseUrlChange(event.target.value)} />
      </label>
      <label className="field">
        <span className="field-label">笔记模型</span>
        <input list="note-api-models" value={model} onChange={(event) => onModelChange(event.target.value)} />
        <datalist id="note-api-models">
          {models.map((item) => (
            <option key={item.id} value={item.id} label={item.display_name} />
          ))}
        </datalist>
      </label>
      <div className="preset-row">
        <button type="button" disabled={isLoadingModels} onClick={onRefreshModels}>
          {isLoadingModels ? "正在获取模型…" : "获取服务器模型列表"}
        </button>
      </div>
      {models.length > 0 ? <p className="field-help">已获取 {models.length} 个模型，可从输入框建议中选择。</p> : null}
      {modelError ? <p className="inline-error" role="alert">{modelError}</p> : null}
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
