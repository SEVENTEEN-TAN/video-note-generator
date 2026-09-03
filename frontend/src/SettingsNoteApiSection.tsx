import { FileText, KeyRound, Loader2, PlugZap } from "lucide-react";

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
  contextWindowTokens: number;
  isLoadingModels: boolean;
  isTestingConnection: boolean;
  maxOutputTokens: number;
  model: string;
  modelError: string;
  models: AIModelInfo[];
  protocol: AIProtocol;
  testMessage: string;
  testSucceeded: boolean;
  thinkingEnabled: boolean;
  onApiKeyChange: (value: string) => void;
  onBaseUrlChange: (value: string) => void;
  onContextWindowTokensChange: (value: number) => void;
  onMaxOutputTokensChange: (value: number) => void;
  onModelChange: (value: string) => void;
  onProtocolChange: (value: AIProtocol) => void;
  onRefreshModels: () => void;
  onTestConnection: () => void;
  onThinkingEnabledChange: (value: boolean) => void;
};

export function SettingsNoteApiSection({
  apiKey,
  baseUrl,
  contextWindowTokens,
  isLoadingModels,
  isTestingConnection,
  maxOutputTokens,
  model,
  modelError,
  models,
  protocol,
  testMessage,
  testSucceeded,
  thinkingEnabled,
  onApiKeyChange,
  onBaseUrlChange,
  onContextWindowTokensChange,
  onMaxOutputTokensChange,
  onModelChange,
  onProtocolChange,
  onRefreshModels,
  onTestConnection,
  onThinkingEnabledChange
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
      <div className="two-col token-budget-fields">
        <label className="field">
          <span className="field-label">模型上下文窗口</span>
          <input
            list="note-context-window-presets"
            max={2000000}
            min={8192}
            step={1024}
            type="number"
            value={contextWindowTokens}
            onChange={(event) => onContextWindowTokensChange(Number(event.target.value))}
          />
          <datalist id="note-context-window-presets">
            <option value="32768">32K</option>
            <option value="65536">64K</option>
            <option value="131072">128K</option>
            <option value="256000">256K</option>
          </datalist>
        </label>
        <label className="field">
          <span className="field-label">最大输出 Tokens</span>
          <input
            list="note-output-token-presets"
            max={262144}
            min={256}
            step={256}
            type="number"
            value={maxOutputTokens}
            onChange={(event) => onMaxOutputTokensChange(Number(event.target.value))}
          />
          <datalist id="note-output-token-presets">
            <option value="4096">4K</option>
            <option value="8192">8K</option>
            <option value="16384">16K</option>
            <option value="32768">32K</option>
          </datalist>
        </label>
      </div>
      <p className="field-help token-budget-help">
        上下文窗口决定长字幕何时分块；最大输出会映射为当前协议的输出上限，并自动预留输入空间。
      </p>
      <label className="thinking-toggle">
        <input
          checked={thinkingEnabled}
          onChange={(event) => onThinkingEnabledChange(event.target.checked)}
          type="checkbox"
        />
        <span>
          <strong>启用模型思考模式</strong>
          <small>关闭后会按当前协议请求模型跳过深度推理，结构化笔记通常更快、更稳定。</small>
        </span>
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
      <div className="preset-row">
        <button type="button" disabled={isTestingConnection} onClick={onTestConnection}>
          {isTestingConnection ? <Loader2 className="spin" size={14} /> : <PlugZap size={14} />}
          {isTestingConnection ? "正在测试接口…" : "测试当前接口"}
        </button>
      </div>
      {testMessage ? (
        <p className={testSucceeded ? "connection-test-success" : "inline-error"} role="status">
          {testMessage}
        </p>
      ) : null}
    </section>
  );
}
