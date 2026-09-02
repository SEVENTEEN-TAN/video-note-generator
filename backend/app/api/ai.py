from __future__ import annotations

from fastapi import APIRouter, HTTPException

from .. import ai_protocols
from ..models import AIModelInfo, AIModelListRequest, AIModelListResponse


router = APIRouter(prefix="/api/ai", tags=["ai"])


@router.post("/models", response_model=AIModelListResponse)
def list_ai_models(request: AIModelListRequest) -> AIModelListResponse:
    try:
        models = ai_protocols.fetch_models(request.protocol, request.api_key, request.base_url)
    except (ai_protocols.AIProtocolError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return AIModelListResponse(models=[AIModelInfo(**model.as_dict()) for model in models])
