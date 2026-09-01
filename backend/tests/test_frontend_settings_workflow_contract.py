from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_settings_state_and_persistence_are_owned_by_a_focused_hook() -> None:
    app_source = (ROOT / "frontend" / "src" / "App.tsx").read_text(encoding="utf-8")
    hook_source = (ROOT / "frontend" / "src" / "useSettings.ts").read_text(encoding="utf-8")
    api_source = (ROOT / "frontend" / "src" / "api.ts").read_text(encoding="utf-8")

    assert 'from "./useSettings"' in app_source
    assert "useSettings(refreshHealth)" in app_source
    assert 'updateSetting("extras", value)' in app_source
    assert 'updateSetting("transcription_mode", value)' in app_source

    assert "/api/settings" not in app_source
    assert "/api/settings" in api_source
    assert "fetchUserSettings()" in hook_source
    assert "saveUserSettings(settings)" in hook_source
    assert "clearUserSettings()" in hook_source

    for legacy_setter in (
        "setTranscriptionApiKey",
        "setTranscriptionMode",
        "setLocalWhisperDevice",
        "setPerformanceMode",
        "setNoteApiKey",
        "setNoteLanguage",
        "setExtras",
        "setFrameLimit",
        "setIsSavingSettings",
        "setSettingsMessage",
    ):
        assert legacy_setter not in app_source

    assert "const DEFAULT_SETTINGS: UserSettings" in hook_source
    assert "useState<UserSettings>(DEFAULT_SETTINGS)" in hook_source
    assert "keyof UserSettings" in hook_source
    assert "mountedRef.current" in hook_source
    assert "loadEpochRef.current" in hook_source
    assert "设置已保存到本地配置文件。" in hook_source
    assert "本地设置已清除。" in hook_source


def test_settings_api_helpers_use_generated_user_settings_type() -> None:
    api_source = (ROOT / "frontend" / "src" / "api.ts").read_text(encoding="utf-8")
    types_source = (ROOT / "frontend" / "src" / "types.ts").read_text(encoding="utf-8")

    assert 'export type UserSettings = ApiSchemas["UserSettings"];' in types_source
    assert "export async function fetchUserSettings(): Promise<UserSettings>" in api_source
    assert "export async function saveUserSettings(settings: UserSettings): Promise<UserSettings>" in api_source
    assert "export async function clearUserSettings(): Promise<UserSettings>" in api_source
    assert 'method: "PATCH"' in api_source
    assert 'method: "DELETE"' in api_source
    assert "设置读取失败。" in api_source
    assert "设置保存失败。" in api_source
    assert "设置清除失败。" in api_source
