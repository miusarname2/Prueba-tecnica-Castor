"""Factory de LLM: Groq por defecto, OpenAI opcional.

Ambos proveedores se exponen como `BaseChatModel` de LangChain para poder
reutilizar el mismo agente (function calling + streaming) sin cambios.
"""
from __future__ import annotations

from functools import lru_cache
from typing import Literal

from langchain_core.language_models.chat_models import BaseChatModel

from app.config import Settings, get_settings


ProviderName = Literal["groq", "openai"]


def _build_groq(settings: Settings) -> BaseChatModel:
    from langchain_groq import ChatGroq

    return ChatGroq(
        api_key=settings.groq_api_key,
        model=settings.groq_model,
        temperature=settings.llm_temperature,
        max_tokens=settings.llm_max_tokens,
        timeout=settings.llm_timeout_seconds,
    )


def _build_openai(settings: Settings) -> BaseChatModel:
    from langchain_openai import ChatOpenAI

    return ChatOpenAI(
        api_key=settings.openai_api_key,
        model=settings.openai_model,
        temperature=settings.llm_temperature,
        max_tokens=settings.llm_max_tokens,
        timeout=settings.llm_timeout_seconds,
    )


@lru_cache(maxsize=4)
def _cached_llm(provider: ProviderName) -> BaseChatModel:
    settings = get_settings()
    if provider == "groq":
        return _build_groq(settings)
    if provider == "openai":
        return _build_openai(settings)
    raise ValueError(f"Proveedor LLM no soportado: {provider!r}")


def get_llm(provider: str | None = None) -> tuple[BaseChatModel, ProviderName]:
    """Devuelve un `(llm, provider_efectivo)`.

    Si `provider` es None, usa el proveedor por defecto (Groq).
    Lanza `ValueError` si falta la API key del proveedor solicitado.
    """
    settings = get_settings()
    chosen = settings.validate_provider(provider)  # type: ignore[assignment]
    return _cached_llm(chosen), chosen  # type: ignore[return-value]
