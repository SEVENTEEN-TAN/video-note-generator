from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from backend.app import ai_protocols
from backend.app import llm
from backend.app.ai_protocols import (
    AIProtocol,
    fetch_models,
    request_json_text,
)
from backend.app.main import app
from backend.app.models import NoteGenerationConfig, NoteLanguage


def test_chat_completion_request_uses_messages_and_bearer_auth(monkeypatch) -> None:
    calls: list[dict] = []

    class FakeCompletions:
        def create(self, **kwargs):
            calls.append(kwargs)
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content='{"title":"Demo"}'))]
            )

    monkeypatch.setattr(
        "backend.app.ai_protocols.make_client",
        lambda *_args, **_kwargs: SimpleNamespace(chat=SimpleNamespace(completions=FakeCompletions())),
    )

    text = request_json_text(
        protocol=AIProtocol.openai_chat_completions,
        api_key="key",
        base_url="https://example.test/v1",
        model="glm-5.3",
        messages=[{"role": "user", "content": "Return JSON"}],
        max_tokens=128,
    )

    assert text == '{"title":"Demo"}'
    assert calls[0]["messages"][0]["role"] == "user"
    assert calls[0]["max_tokens"] == 128
    assert calls[0]["response_format"] == {"type": "json_object"}
    assert "extra_body" not in calls[0]


def test_chat_request_disables_thinking_when_requested(monkeypatch) -> None:
    calls: list[dict] = []

    class FakeCompletions:
        def create(self, **kwargs):
            calls.append(kwargs)
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content='{"title":"Demo"}'))])

    monkeypatch.setattr(
        "backend.app.ai_protocols.make_client",
        lambda *_args, **_kwargs: SimpleNamespace(chat=SimpleNamespace(completions=FakeCompletions())),
    )

    request_json_text(
        protocol=AIProtocol.openai_chat_completions,
        api_key="key",
        base_url="https://open.bigmodel.cn/api/coding/paas/v4",
        model="glm-5.3-flash",
        messages=[{"role": "user", "content": "Return JSON"}],
        max_tokens=128,
        thinking_enabled=False,
    )

    assert calls[0]["reasoning_effort"] == "none"


def test_responses_request_extracts_output_text(monkeypatch) -> None:
    calls: list[dict] = []

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"output_text": '{"title":"Demo"}'}

    def fake_post(url, **kwargs):
        calls.append({"url": url, **kwargs})
        return FakeResponse()

    monkeypatch.setattr("backend.app.ai_protocols.httpx.post", fake_post)

    text = request_json_text(
        protocol=AIProtocol.openai_responses,
        api_key="key",
        base_url="https://example.test/v1",
        model="glm-5.3",
        messages=[{"role": "system", "content": "You return JSON."}, {"role": "user", "content": "Return JSON"}],
        max_tokens=128,
    )

    assert text == '{"title":"Demo"}'
    assert calls[0]["json"]["model"] == "glm-5.3"
    assert calls[0]["json"]["max_output_tokens"] == 128
    assert calls[0]["json"]["input"] == [{"role": "user", "content": "Return JSON"}]
    assert "reasoning" not in calls[0]["json"]


def test_responses_request_disables_reasoning_when_requested(monkeypatch) -> None:
    calls: list[dict] = []

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"output_text": '{"title":"Demo"}'}

    def fake_post(url, **kwargs):
        calls.append({"url": url, **kwargs})
        return FakeResponse()

    monkeypatch.setattr("backend.app.ai_protocols.httpx.post", fake_post)

    request_json_text(
        protocol=AIProtocol.openai_responses,
        api_key="key",
        base_url="https://open.bigmodel.cn/api/v1",
        model="glm-5.3-flash",
        messages=[{"role": "user", "content": "Return JSON"}],
        max_tokens=128,
        thinking_enabled=False,
    )

    assert calls[0]["json"]["reasoning"] == {"effort": "none"}


def test_anthropic_request_uses_messages_api_and_extracts_text(monkeypatch) -> None:
    calls: list[dict] = []

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"content": [{"type": "text", "text": '{"title":"Demo"}'}]}

    def fake_post(url, **kwargs):
        calls.append({"url": url, **kwargs})
        return FakeResponse()

    monkeypatch.setattr("backend.app.ai_protocols.httpx.post", fake_post)

    text = request_json_text(
        protocol=AIProtocol.anthropic_messages,
        api_key="key",
        base_url="https://example.test/anthropic",
        model="glm-5.3",
        messages=[{"role": "system", "content": "You return JSON."}, {"role": "user", "content": "Return JSON"}],
        max_tokens=128,
    )

    assert text == '{"title":"Demo"}'
    assert calls[0]["headers"] == {
        "x-api-key": "key",
        "anthropic-version": "2023-06-01",
        "Content-Type": "application/json",
    }
    assert calls[0]["url"] == "https://example.test/anthropic/v1/messages"
    assert calls[0]["json"]["system"] == "You return JSON."
    assert calls[0]["json"]["messages"] == [{"role": "user", "content": "Return JSON"}]
    assert calls[0]["json"]["max_tokens"] == 128
    assert "thinking" not in calls[0]["json"]


def test_anthropic_request_disables_thinking_when_requested(monkeypatch) -> None:
    calls: list[dict] = []

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"content": [{"type": "text", "text": '{"title":"Demo"}'}]}

    def fake_post(url, **kwargs):
        calls.append({"url": url, **kwargs})
        return FakeResponse()

    monkeypatch.setattr("backend.app.ai_protocols.httpx.post", fake_post)

    request_json_text(
        protocol=AIProtocol.anthropic_messages,
        api_key="key",
        base_url="https://open.bigmodel.cn/api/anthropic",
        model="glm-5.3-flash",
        messages=[{"role": "user", "content": "Return JSON"}],
        max_tokens=128,
        thinking_enabled=False,
    )

    assert calls[0]["json"]["thinking"] == {"type": "disabled"}


def test_fetch_models_normalizes_chat_and_responses_shapes(monkeypatch) -> None:
    class FakeResponse:
        def __init__(self, payload):
            self.payload = payload

        def raise_for_status(self):
            return None

        def json(self):
            return self.payload

    payloads = {
        "https://chat.test/v1/models": {"data": [{"id": "glm-5.3", "owned_by": "z-ai"}]},
        "https://responses.test/v1/models": {"models": [{"slug": "glm-5.3", "display_name": "GLM 5.3"}]},
    }

    def fake_get(url, **kwargs):
        assert kwargs["headers"]["Authorization"] == "Bearer key"
        return FakeResponse(payloads[url])

    monkeypatch.setattr("backend.app.ai_protocols.httpx.get", fake_get)

    chat_models = fetch_models(AIProtocol.openai_chat_completions, "key", "https://chat.test/v1")
    response_models = fetch_models(AIProtocol.openai_responses, "key", "https://responses.test/v1")

    assert chat_models[0].id == "glm-5.3"
    assert chat_models[0].display_name == "glm-5.3"
    assert response_models[0].id == "glm-5.3"
    assert response_models[0].display_name == "GLM 5.3"


def test_fetch_models_uses_anthropic_headers(monkeypatch) -> None:
    seen: dict = {}

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"data": [{"id": "claude-test", "display_name": "Claude Test"}]}

    def fake_get(url, **kwargs):
        seen["url"] = url
        seen.update(kwargs)
        return FakeResponse()

    monkeypatch.setattr("backend.app.ai_protocols.httpx.get", fake_get)

    models = fetch_models(AIProtocol.anthropic_messages, "key", "https://anthropic.test/v1")

    assert models[0].id == "claude-test"
    assert seen["url"] == "https://anthropic.test/v1/models"
    assert seen["headers"] == {"x-api-key": "key", "anthropic-version": "2023-06-01"}


def test_model_list_api_returns_normalized_models(monkeypatch) -> None:
    monkeypatch.setattr(
        ai_protocols,
        "fetch_models",
        lambda protocol, api_key, base_url: [ai_protocols.AIModel("glm-5.3", "GLM 5.3", "z-ai")],
    )

    response = TestClient(app).post(
        "/api/ai/models",
        json={
            "protocol": "openai_responses",
            "api_key": "key",
            "base_url": "https://open.bigmodel.cn/api/v1",
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "models": [{"id": "glm-5.3", "display_name": "GLM 5.3", "owned_by": "z-ai"}]
    }


@pytest.mark.parametrize(
    ("protocol", "thinking_enabled"),
    [
        ("openai_chat_completions", False),
        ("openai_responses", True),
        ("anthropic_messages", False),
    ],
)
def test_ai_connection_api_uses_selected_protocol_and_thinking_mode(
    protocol, thinking_enabled, monkeypatch
) -> None:
    calls: list[dict] = []
    monkeypatch.setattr(
        ai_protocols,
        "request_json_text",
        lambda **kwargs: calls.append(kwargs) or '{"ok":true}',
    )

    response = TestClient(app).post(
        "/api/ai/test",
        json={
            "protocol": protocol,
            "api_key": "test-secret",
            "base_url": "https://example.test/v1",
            "model": "model-test",
            "thinking_enabled": thinking_enabled,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["protocol"] == protocol
    assert payload["model"] == "model-test"
    assert payload["response_length"] == len('{"ok":true}')
    assert payload["json_valid"] is True
    assert payload["elapsed_ms"] >= 0
    assert "test-secret" not in response.text
    assert '{"ok":true}' not in response.text
    assert calls[0]["protocol"] == protocol
    assert calls[0]["thinking_enabled"] is thinking_enabled
    assert calls[0]["model"] == "model-test"
    assert calls[0]["max_tokens"] == 8192


def test_ai_connection_api_maps_provider_errors_to_bad_request(monkeypatch) -> None:
    def fail_request(**_kwargs):
        raise ai_protocols.AIProtocolError("provider rejected request")

    monkeypatch.setattr(ai_protocols, "request_json_text", fail_request)

    response = TestClient(app).post(
        "/api/ai/test",
        json={
            "protocol": "openai_chat_completions",
            "api_key": "test-secret",
            "base_url": "https://example.test/v1",
            "model": "model-test",
            "thinking_enabled": False,
        },
    )

    assert response.status_code == 400
    assert response.json() == {"detail": "provider rejected request"}
    assert "test-secret" not in response.text


@pytest.mark.parametrize("protocol", [AIProtocol.openai_responses, AIProtocol.anthropic_messages])
def test_call_note_model_routes_non_chat_protocols_through_adapter(protocol, monkeypatch) -> None:
    calls: list[dict] = []
    monkeypatch.setattr(
        llm,
        "request_json_text",
        lambda **kwargs: calls.append(kwargs)
        or '{"title":"Demo","summary":"ok","chapters":[],"key_moments":[]}',
    )
    config = NoteGenerationConfig(
        original_filename="demo.mp4",
        note_api_key="key",
        note_api_protocol=protocol,
        note_base_url="https://example.test/v1",
        note_model="glm-5.3",
        note_context_window_tokens=256000,
        note_max_output_tokens=32768,
        note_language=NoteLanguage.zh,
    )

    draft = llm.call_note_model(config, [{"role": "user", "content": "Return JSON"}])

    assert draft.summary == "ok"
    assert calls[0]["protocol"] == protocol
    assert calls[0]["model"] == "glm-5.3"
    assert calls[0]["max_tokens"] == 32768


def test_call_json_model_routes_responses_protocol_through_adapter(monkeypatch) -> None:
    monkeypatch.setattr(llm, "request_json_text", lambda **_kwargs: '{"segments":[]}')
    config = NoteGenerationConfig(
        original_filename="demo.mp4",
        note_api_key="key",
        note_api_protocol=AIProtocol.openai_responses,
        note_base_url="https://example.test/v1",
        note_model="glm-5.3",
        note_language=NoteLanguage.zh,
    )

    assert llm.call_json_model(config, [{"role": "user", "content": "Return JSON"}]) == {"segments": []}
