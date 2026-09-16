"""Modelos Pydantic para requests y responses de la API."""
from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


UserRole = Literal["viewer", "analyst", "admin"]


class ChatRequest(BaseModel):
    """Payload de entrada al endpoint /chat y /chat/stream."""

    message: str = Field(..., min_length=1, max_length=4000, description="Pregunta del usuario.")
    user_role: UserRole = Field(
        default="viewer",
        description="Rol del usuario. Controla qué información puede revelar el agente.",
    )
    year_filter: Optional[int] = Field(
        default=None,
        ge=1990,
        le=2100,
        description="Filtro de metadata para el RAG (ej. 2024). Si es null no filtra por año.",
    )
    provider: Optional[Literal["groq", "openai"]] = Field(
        default=None,
        description="Proveedor LLM a usar en esta petición. Si es null se usa el default (Groq).",
    )

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "message": "Para la orden ORD-1001, obtén sus datos del ERP y calcula si tiene discrepancia fiscal.",
                    "user_role": "analyst",
                    "year_filter": 2024,
                    "provider": "groq",
                }
            ]
        }
    }


class SourceRef(BaseModel):
    file: str
    year: Optional[int] = None
    score: Optional[float] = None
    snippet: str = ""


class ToolTrace(BaseModel):
    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    output: Any = None


class ChatResponse(BaseModel):
    response: str
    provider: str
    sources: list[SourceRef] = Field(default_factory=list)
    tools_used: list[ToolTrace] = Field(default_factory=list)
    blocked: bool = False
    block_reason: Optional[str] = None


class ErrorResponse(BaseModel):
    error: str
    detail: Optional[str] = None
