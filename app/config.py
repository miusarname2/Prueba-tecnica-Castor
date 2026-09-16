"""Configuración centralizada con soporte multi-proveedor (Groq por defecto).

Todos los valores se leen desde variables de entorno / `.env`.
El proveedor por defecto es Groq (siguiendo el patrón de `AIService-master`),
pero el usuario puede cambiar a OpenAI con `LLM_PROVIDER=openai` o al invocar
el endpoint pasando `provider` en el request.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Configuración de la aplicación."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    llm_provider: Literal["groq", "openai"] = Field(default="groq")

    groq_api_key: str = Field(default="")
    groq_model: str = Field(default="openai/gpt-oss-20b")

    openai_api_key: str = Field(default="")
    openai_model: str = Field(default="gpt-4o-mini")

    llm_temperature: float = Field(default=0.2)
    llm_max_tokens: int = Field(default=1024)
    llm_timeout_seconds: int = Field(default=30)

    knowledge_dir: str = Field(default="knowledge")
    rag_top_k: int = Field(default=4)
    embedding_model: str = Field(default="sentence-transformers/all-MiniLM-L6-v2")

    api_host: str = Field(default="0.0.0.0")
    api_port: int = Field(default=8000)
    api_cors_origins: str = Field(default="*")

    @property
    def project_root(self) -> Path:
        return Path(__file__).resolve().parent.parent

    @property
    def knowledge_path(self) -> Path:
        p = Path(self.knowledge_dir)
        return p if p.is_absolute() else self.project_root / p

    def cors_origins_list(self) -> list[str]:
        raw = self.api_cors_origins.strip()
        if raw == "*" or not raw:
            return ["*"]
        return [o.strip() for o in raw.split(",") if o.strip()]

    def validate_provider(self, provider: str | None = None) -> str:
        """Devuelve el proveedor efectivo y valida que su API key esté presente."""
        chosen = (provider or self.llm_provider).lower()
        if chosen not in {"groq", "openai"}:
            raise ValueError(f"Proveedor LLM no soportado: {chosen!r}")
        if chosen == "groq" and not self.groq_api_key:
            raise ValueError("Falta GROQ_API_KEY en el entorno.")
        if chosen == "openai" and not self.openai_api_key:
            raise ValueError("Falta OPENAI_API_KEY en el entorno.")
        return chosen


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
