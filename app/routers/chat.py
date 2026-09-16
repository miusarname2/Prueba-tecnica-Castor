"""Endpoints /chat y /chat/stream."""
from __future__ import annotations

import json
import logging

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from sse_starlette.sse import EventSourceResponse

from app.models.schemas import ChatRequest, ChatResponse, ToolTrace
from app.security.guardrails import check_prompt, output_contains_restricted
from app.services.agent import run_agent, stream_agent


logger = logging.getLogger(__name__)
router = APIRouter(prefix="/chat", tags=["Chat"])


@router.post(
    "",
    response_model=ChatResponse,
    summary="Consulta al agente (respuesta completa)",
    responses={
        400: {"description": "Petición bloqueada por guardrails."},
        502: {"description": "Fallo del LLM upstream."},
        503: {"description": "Fallo del ERP / servicios externos."},
    },
)
async def chat(request: ChatRequest) -> ChatResponse:
    guard = check_prompt(request.message, request.user_role)
    if not guard.allowed:
        return ChatResponse(
            response=guard.reason,
            provider=request.provider or "n/a",
            blocked=True,
            block_reason=guard.category,
        )

    try:
        result = run_agent(
            message=request.message,
            user_role=request.user_role,
            year_filter=request.year_filter,
            provider=request.provider,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.exception("Error del agente")
        raise HTTPException(status_code=502, detail=f"LLM/agent error: {e}")

    if output_contains_restricted(result.response, request.user_role):
        return ChatResponse(
            response="Acceso denegado: La respuesta contenía datos fuera de tu alcance.",
            provider=result.provider,
            sources=result.sources,
            tools_used=result.tools_used,
            blocked=True,
            block_reason="restricted_data",
        )

    return ChatResponse(
        response=result.response,
        provider=result.provider,
        sources=result.sources,
        tools_used=result.tools_used,
    )


@router.post(
    "/stream",
    summary="Consulta al agente con streaming de tokens (SSE)",
)
async def chat_stream(request: ChatRequest, req: Request):
    guard = check_prompt(request.message, request.user_role)
    if not guard.allowed:
        return JSONResponse(
            status_code=400,
            content={
                "error": "blocked",
                "category": guard.category,
                "message": guard.reason,
            },
        )

    async def event_generator():
        try:
            async for event in stream_agent(
                message=request.message,
                user_role=request.user_role,
                year_filter=request.year_filter,
                provider=request.provider,
            ):
                if await req.is_disconnected():
                    logger.info("Cliente desconectado del stream.")
                    return
                yield {
                    "event": event.get("type", "message"),
                    "data": json.dumps(event, ensure_ascii=False, default=str),
                }
        except Exception as e:
            logger.exception("Error inesperado en el stream")
            yield {
                "event": "error",
                "data": json.dumps({"type": "error", "message": str(e)}),
            }

    return EventSourceResponse(event_generator())
