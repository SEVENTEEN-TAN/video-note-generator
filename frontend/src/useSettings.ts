import { useCallback, useEffect, useRef, useState } from "react";

import { clearUserSettings, fetchUserSettings, saveUserSettings } from "./api";
import { OPENAI_BASE_URL } from "./constants";
import type { UserSettings } from "./types";

const DEFAULT_SETTINGS: UserSettings = {
  external_python_path: "",
  extras: "",
  faster_whisper_model_dir: "",
  frame_limit: 6,
  local_whisper_compute_type: "default",
  local_whisper_device: "auto",
  note_api_key: "",
  note_base_url: OPENAI_BASE_URL,
  note_language: "zh",
  note_model: "gpt-5.5",
  note_style: "detailed",
  performance_mode: "balanced",
  python_package_install_mode: "default",
  transcription_api_key: "",
  transcription_base_url: OPENAI_BASE_URL,
  transcription_language: "auto",
  transcription_mode: "local_faster_whisper",
  transcription_model: "small"
};

type SettingsController = {
  clearSettings: () => Promise<void>;
  isSavingSettings: boolean;
  saveSettings: () => Promise<void>;
  settings: UserSettings;
  settingsMessage: string;
  updateSetting: <K extends keyof UserSettings>(key: K, value: UserSettings[K]) => void;
};

export function useSettings(onRefreshHealth: () => Promise<void>): SettingsController {
  const [settings, setSettings] = useState<UserSettings>(DEFAULT_SETTINGS);
  const [isSavingSettings, setIsSavingSettings] = useState(false);
  const [settingsMessage, setSettingsMessage] = useState("");
  const mountedRef = useRef(true);
  const loadEpochRef = useRef(0);
  const onRefreshHealthRef = useRef(onRefreshHealth);
  onRefreshHealthRef.current = onRefreshHealth;

  useEffect(() => {
    mountedRef.current = true;
    const loadEpoch = loadEpochRef.current + 1;
    loadEpochRef.current = loadEpoch;
    fetchUserSettings()
      .then((loadedSettings) => {
        if (mountedRef.current && loadEpochRef.current === loadEpoch) {
          setSettings(loadedSettings);
        }
      })
      .catch(() => undefined);
    return () => {
      mountedRef.current = false;
      loadEpochRef.current += 1;
    };
  }, []);

  const updateSetting = useCallback(
    <K extends keyof UserSettings>(key: K, value: UserSettings[K]) => {
      setSettings((current) => ({ ...current, [key]: value }));
    },
    []
  );

  async function saveSettings() {
    setIsSavingSettings(true);
    setSettingsMessage("");
    try {
      const savedSettings = await saveUserSettings(settings);
      if (!mountedRef.current) {
        return;
      }
      setSettings(savedSettings);
      await onRefreshHealthRef.current();
      if (mountedRef.current) {
        setSettingsMessage("设置已保存到本地配置文件。");
      }
    } catch (error) {
      if (mountedRef.current) {
        setSettingsMessage(error instanceof Error ? error.message : "设置保存失败。");
      }
    } finally {
      if (mountedRef.current) {
        setIsSavingSettings(false);
      }
    }
  }

  async function clearSettings() {
    setIsSavingSettings(true);
    setSettingsMessage("");
    try {
      const clearedSettings = await clearUserSettings();
      if (!mountedRef.current) {
        return;
      }
      setSettings(clearedSettings);
      await onRefreshHealthRef.current();
      if (mountedRef.current) {
        setSettingsMessage("本地设置已清除。");
      }
    } catch (error) {
      if (mountedRef.current) {
        setSettingsMessage(error instanceof Error ? error.message : "设置清除失败。");
      }
    } finally {
      if (mountedRef.current) {
        setIsSavingSettings(false);
      }
    }
  }

  return {
    clearSettings,
    isSavingSettings,
    saveSettings,
    settings,
    settingsMessage,
    updateSetting
  };
}
