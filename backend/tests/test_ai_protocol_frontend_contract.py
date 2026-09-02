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
    assert 'requestJson("/api/ai/models"' in api
    assert 'formData.append("note_api_protocol", currentSettings.note_api_protocol)' in creation


def test_bigmodel_protocol_presets_use_documented_base_urls() -> None:
    constants = (ROOT / "frontend" / "src" / "constants.ts").read_text(encoding="utf-8")

    assert "https://open.bigmodel.cn/api/anthropic" in constants
    assert "https://open.bigmodel.cn/api/coding/paas/v4" in constants
    assert "https://open.bigmodel.cn/api/v1" in constants
