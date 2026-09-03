from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_frontend_exposes_protocol_selection_and_server_model_loading() -> None:
    section = (ROOT / "frontend" / "src" / "SettingsNoteApiSection.tsx").read_text(encoding="utf-8")
    api = (ROOT / "frontend" / "src" / "api.ts").read_text(encoding="utf-8")
    creation = (ROOT / "frontend" / "src" / "useJobCreation.ts").read_text(encoding="utf-8")

    assert "OpenAI Chat Completions" in section
    assert "OpenAI Responses" in section
    assert "Anthropic Messages" in section
    assert "获取服务器模型列表" in section
    assert "启用模型思考模式" in section
    assert "模型上下文窗口" in section
    assert "最大输出 Tokens" in section
    assert "测试当前接口" in section
    assert 'requestJson("/api/ai/models"' in api
    assert 'requestJson("/api/ai/test"' in api
    assert 'formData.append("note_api_protocol", currentSettings.note_api_protocol)' in creation
    assert 'formData.append("note_thinking_enabled", String(currentSettings.note_thinking_enabled))' in creation
    assert 'formData.append("note_context_window_tokens", String(currentSettings.note_context_window_tokens))' in creation
    assert 'formData.append("note_max_output_tokens", String(currentSettings.note_max_output_tokens))' in creation


def test_bigmodel_protocol_presets_use_documented_base_urls() -> None:
    constants = (ROOT / "frontend" / "src" / "constants.ts").read_text(encoding="utf-8")

    assert "https://open.bigmodel.cn/api/anthropic" in constants
    assert "https://open.bigmodel.cn/api/coding/paas/v4" in constants
    assert "https://open.bigmodel.cn/api/v1" in constants
