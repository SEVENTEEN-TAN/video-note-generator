import { KeyRound } from "lucide-react";

export type SettingsRemoteTranscriptionSectionProps = {
  apiKey: string;
  baseUrl: string;
  model: string;
  onApiKeyChange: (value: string) => void;
  onBaseUrlChange: (value: string) => void;
  onModelChange: (value: string) => void;
};

export function SettingsRemoteTranscriptionSection({
  apiKey,
  baseUrl,
  model,
  onApiKeyChange,
  onBaseUrlChange,
  onModelChange
}: SettingsRemoteTranscriptionSectionProps) {
  return (
    <>
      <label className="field">
        <span className="field-label">Base URL</span>
        <input value={baseUrl} onChange={(event) => onBaseUrlChange(event.target.value)} />
      </label>
      <label className="field">
        <span className="field-label">转写模型</span>
        <input value={model} onChange={(event) => onModelChange(event.target.value)} />
      </label>
      <label className="field">
        <span className="field-label">
          <KeyRound size={15} />
          转写 API Key
        </span>
        <input
          autoComplete="off"
          placeholder="可保存到本地设置"
          type="password"
          value={apiKey}
          onChange={(event) => onApiKeyChange(event.target.value)}
        />
      </label>
    </>
  );
}
