from __future__ import annotations

from typing import Any

import httpx
from openai import OpenAI

from .models import AIProtocol


class AIProtocolError(RuntimeError):
    pass


class AIModel:
    def __init__(self, model_id: str, display_name: str = "", owned_by: str = "") -> None:
        self.id = model_id
        self.display_name = display_name or model_id
        self.owned_by = owned_by

    def as_dict(self) -> dict[str, str]:
        payload = {"id": self.id, "display_name": self.display_name}
        if self.owned_by:
            payload["owned_by"] = self.owned_by
        return payload


def make_client(api_key: str, base_url: str) -> OpenAI:
    return OpenAI(api_key=api_key, base_url=base_url.strip().rstrip("/"), timeout=60.0, max_retries=0)


def request_json_text(
    *,
    protocol: AIProtocol | str,
    api_key: str,
    base_url: str,
    model: str,
    messages: list[dict],
    max_tokens: int,
    temperature: float = 0.2,
) -> str:
    selected = AIProtocol(protocol)
    if selected == AIProtocol.openai_chat_completions:
        response = make_client(api_key, base_url).chat.completions.create(
            model=model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            response_format={"type": "json_object"},
        )
        return str(response.choices[0].message.content or "")
    if selected == AIProtocol.openai_responses:
        system, _user_messages = _split_system_messages(messages)
        payload = {
            "model": model,
            "input": _responses_input(messages),
            "temperature": temperature,
            "max_output_tokens": max_tokens,
        }
        if system:
            payload["instructions"] = system
        response = _post_json(base_url, "responses", {"Authorization": f"Bearer {api_key}"}, payload)
        return _extract_responses_text(response)

    system, user_messages = _split_system_messages(messages)
    payload = {
        "model": model,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "messages": user_messages,
    }
    if system:
        payload["system"] = system
    response = _post_json(
        base_url,
        _anthropic_endpoint(base_url, "messages"),
        {"x-api-key": api_key, "anthropic-version": "2023-06-01"},
        payload,
    )
    return _extract_anthropic_text(response)


def fetch_models(protocol: AIProtocol | str, api_key: str, base_url: str) -> list[AIModel]:
    selected = AIProtocol(protocol)
    endpoint = _anthropic_endpoint(base_url, "models") if selected == AIProtocol.anthropic_messages else "models"
    response = _get_json(base_url, endpoint, _headers_for(selected, api_key))
    raw_models = response.get("data")
    if not isinstance(raw_models, list):
        raw_models = response.get("models")
    if not isinstance(raw_models, list):
        raise AIProtocolError("Model list response did not contain data or models.")

    models: list[AIModel] = []
    for item in raw_models:
        if not isinstance(item, dict):
            continue
        model_id = str(item.get("id") or item.get("slug") or "").strip()
        if model_id:
            models.append(AIModel(model_id, str(item.get("display_name") or model_id), str(item.get("owned_by") or "")))
    return models


def _headers_for(protocol: AIProtocol, api_key: str) -> dict[str, str]:
    if protocol == AIProtocol.anthropic_messages:
        return {"x-api-key": api_key, "anthropic-version": "2023-06-01"}
    return {"Authorization": f"Bearer {api_key}"}


def _anthropic_endpoint(base_url: str, resource: str) -> str:
    return resource if base_url.strip().rstrip("/").endswith("/v1") else f"v1/{resource}"


def _post_json(base_url: str, endpoint: str, headers: dict[str, str], payload: dict[str, Any]) -> dict[str, Any]:
    try:
        response = httpx.post(
            f"{base_url.strip().rstrip('/')}/{endpoint}",
            headers={**headers, "Content-Type": "application/json"},
            json=payload,
            timeout=60.0,
        )
        response.raise_for_status()
        body = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise AIProtocolError(f"AI request failed: {exc}") from exc
    if not isinstance(body, dict):
        raise AIProtocolError("AI response must be a JSON object.")
    _raise_api_body_error(body)
    return body


def _get_json(base_url: str, endpoint: str, headers: dict[str, str]) -> dict[str, Any]:
    try:
        response = httpx.get(
            f"{base_url.strip().rstrip('/')}/{endpoint}",
            headers=headers,
            timeout=30.0,
        )
        response.raise_for_status()
        body = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise AIProtocolError(f"Model list request failed: {exc}") from exc
    if not isinstance(body, dict):
        raise AIProtocolError("Model list response must be a JSON object.")
    _raise_api_body_error(body)
    return body


def _raise_api_body_error(body: dict[str, Any]) -> None:
    error = body.get("error")
    if error:
        if isinstance(error, dict):
            detail = error.get("message") or error.get("code") or error
        else:
            detail = error
        raise AIProtocolError(f"AI service returned an error: {detail}")
    if body.get("success") is False:
        detail = body.get("msg") or body.get("message") or body.get("code") or "unknown error"
        raise AIProtocolError(f"AI service returned an error: {detail}")


def _split_system_messages(messages: list[dict]) -> tuple[str, list[dict]]:
    system_parts: list[str] = []
    user_messages: list[dict] = []
    for message in messages:
        if message.get("role") == "system":
            system_parts.append(_content_to_text(message.get("content")))
        else:
            user_messages.append(message)
    return "\n\n".join(part for part in system_parts if part), user_messages


def _responses_input(messages: list[dict]) -> list[dict]:
    return [
        {"role": message.get("role", "user"), "content": _content_to_text(message.get("content"))}
        for message in messages
        if message.get("role") != "system"
    ]


def _content_to_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(_content_to_text(item.get("text", "") if isinstance(item, dict) else item) for item in content)
    return str(content or "")


def _extract_responses_text(response: dict[str, Any]) -> str:
    if isinstance(response.get("output_text"), str):
        return response["output_text"]
    parts: list[str] = []
    for item in response.get("output", []):
        if not isinstance(item, dict):
            continue
        for content in item.get("content", []):
            if isinstance(content, dict) and content.get("type") in {"output_text", "text"}:
                parts.append(str(content.get("text") or ""))
    return "".join(parts)


def _extract_anthropic_text(response: dict[str, Any]) -> str:
    return "".join(
        str(block.get("text") or "")
        for block in response.get("content", [])
        if isinstance(block, dict) and block.get("type") == "text"
    )
