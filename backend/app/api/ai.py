from __future__ import annotations

from time import perf_counter

from fastapi import APIRouter, HTTPException

from .. import ai_protocols
from ..llm import extract_json
from ..models import (
    AIConnectionTestRequest,
    AIConnectionTestResponse,
    AIModelInfo,
    AIModelListRequest,
    AIModelListResponse,
)


router = APIRouter(prefix="/api/ai", tags=["ai"])


@router.post("/models", response_model=AIModelListResponse)
def list_ai_models(request: AIModelListRequest) -> AIModelListResponse:
    try:
        models = ai_protocols.fetch_models(request.protocol, request.api_key, request.base_url)
    except (ai_protocols.AIProtocolError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return AIModelListResponse(models=[AIModelInfo(**model.as_dict()) for model in models])


@router.post("/test", response_model=AIConnectionTestResponse)
def test_ai_connection(request: AIConnectionTestRequest) -> AIConnectionTestResponse:
    started_at = perf_counter()
    try:
        text = ai_protocols.request_json_text(
            protocol=request.protocol,
            api_key=request.api_key,
            base_url=request.base_url,
            model=request.model,
            messages=[
                {"role": "system", "content": "Return strict JSON only."},
                {"role": "user", "content": 'Return exactly {"ok":true}.'},
            ],
            max_tokens=request.max_output_tokens,
            temperature=0.1,
            thinking_enabled=request.thinking_enabled,
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    try:
        extract_json(text)
        json_valid = True
    except ValueError:
        json_valid = False
    return AIConnectionTestResponse(
        protocol=request.protocol,
        model=request.model,
        elapsed_ms=max(0, round((perf_counter() - started_at) * 1000)),
        response_length=len(text),
        json_valid=json_valid,
    )
