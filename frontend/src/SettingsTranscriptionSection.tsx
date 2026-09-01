import { Captions } from "lucide-react";

import { SettingsLocalTranscriptionSection } from "./SettingsLocalTranscriptionSection";
import type { SettingsLocalTranscriptionSectionProps } from "./SettingsLocalTranscriptionSection";
import { SettingsRemoteTranscriptionSection } from "./SettingsRemoteTranscriptionSection";
import type { TranscriptionLanguage, TranscriptionMode } from "./types";

export type SettingsTranscriptionSectionProps = SettingsLocalTranscriptionSectionProps & {
  onTranscriptionApiKeyChange: (value: string) => void;
  onTranscriptionBaseUrlChange: (value: string) => void;
  onTranscriptionLanguageChange: (value: TranscriptionLanguage) => void;
  onTranscriptionModeChange: (value: TranscriptionMode) => void;
  transcriptionApiKey: string;
  transcriptionBaseUrl: string;
  transcriptionLanguage: TranscriptionLanguage;
  transcriptionMode: TranscriptionMode;
};

export function SettingsTranscriptionSection(props: SettingsTranscriptionSectionProps) {
  const {
    onTranscriptionApiKeyChange,
    onTranscriptionBaseUrlChange,
    onTranscriptionLanguageChange,
    onTranscriptionModeChange,
    onTranscriptionModelChange,
    transcriptionApiKey,
    transcriptionBaseUrl,
    transcriptionLanguage,
    transcriptionMode,
    transcriptionModel
  } = props;
  const isLocalTranscription = transcriptionMode === "local_faster_whisper";

  function handleTranscriptionModeChange(nextMode: TranscriptionMode) {
    onTranscriptionModeChange(nextMode);
    if (nextMode === "local_faster_whisper") {
      onTranscriptionModelChange("small");
    } else if (transcriptionMode === "local_faster_whisper") {
      onTranscriptionModelChange(nextMode === "chat_audio" ? "gpt-5.5" : "whisper-1");
    }
  }

  return (
    <section className="api-section">
      <div className="section-title">
        <Captions size={16} />
        <span>字幕转写配置</span>
      </div>
      <p className="field-help">
        {isLocalTranscription
          ? "本地 Faster Whisper 使用内置依赖或外部 Python worker；缺模型时可在这里下载。"
          : "远端转写使用 OpenAI-compatible API，请确认模型支持音频转写或多模态音频。"}
      </p>

      <label className="field">
        <span className="field-label">转写来源</span>
        <select
          value={transcriptionMode}
          onChange={(event) => handleTranscriptionModeChange(event.target.value as TranscriptionMode)}
        >
          <option value="local_faster_whisper">本地 Faster Whisper</option>
          <option value="audio_transcriptions">Audio Transcriptions 端点</option>
          <option value="chat_audio">Chat 多模态音频兜底</option>
        </select>
      </label>

      <label className="field">
        <span className="field-label">字幕语言</span>
        <select
          value={transcriptionLanguage}
          onChange={(event) => onTranscriptionLanguageChange(event.target.value as TranscriptionLanguage)}
        >
          <option value="auto">自动检测</option>
          <option value="zh">中文</option>
          <option value="en">English</option>
        </select>
      </label>

      {isLocalTranscription ? (
        <SettingsLocalTranscriptionSection {...props} />
      ) : (
        <SettingsRemoteTranscriptionSection
          apiKey={transcriptionApiKey}
          baseUrl={transcriptionBaseUrl}
          model={transcriptionModel}
          onApiKeyChange={onTranscriptionApiKeyChange}
          onBaseUrlChange={onTranscriptionBaseUrlChange}
          onModelChange={onTranscriptionModelChange}
        />
      )}
    </section>
  );
}
