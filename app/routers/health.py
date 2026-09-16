"""Endpoints de salud."""
from __future__ import annotations

from fastapi import APIRouter

from app import __version__
from app.config import get_settings


router = APIRouter()


@router.get("/", tags=["Health"], summary="Root")
async def root() -> dict[str, str]:
    return {"service": "ERP-Agent MVP", "version": __version__}


@router.get("/health", tags=["Health"], summary="Health check")
async def health() -> dict[str, object]:
    settings = get_settings()
    return {
        "status": "ok",
        "version": __version__,
        "llm_provider_default": settings.llm_provider,
        "groq_configured": bool(settings.groq_api_key),
        "openai_configured": bool(settings.openai_api_key),
    }
