"""Pipeline RAG con LlamaIndex + Metadata Filtering.

- Carga documentos Markdown de `knowledge/` con front-matter YAML sencillo.
- Construye un `VectorStoreIndex` en memoria con embeddings HuggingFace locales
  (no requiere API key externa).
- Expone `retrieve(query, year=None, allowed_roles=None, top_k=None)` que aplica
  **Metadata Filtering** para:
    * filtrar por año (evitar ruido de documentos antiguos, ej. sólo 2024).
    * filtrar por rol permitido (nunca devolver documentos confidenciales a
      usuarios sin permiso).

Este módulo hace lazy-init del índice para acelerar el arranque de la app.
"""
from __future__ import annotations

import logging
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable

from llama_index.core import Document, Settings as LISettings, VectorStoreIndex
from llama_index.core.vector_stores import (
    FilterCondition,
    FilterOperator,
    MetadataFilter,
    MetadataFilters,
)
from llama_index.embeddings.huggingface import HuggingFaceEmbedding

from app.config import get_settings
from app.models.schemas import SourceRef


logger = logging.getLogger(__name__)


_FRONT_MATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n?(.*)$", re.DOTALL)


def _parse_front_matter(text: str) -> tuple[dict[str, Any], str]:
    # Workaround manual porque LlamaIndex 0.11 no acepta booleanos en MetadataFilter
    m = _FRONT_MATTER_RE.match(text)
    if not m:
        return {}, text
    header, body = m.group(1), m.group(2)
    meta: dict[str, Any] = {}
    for line in header.splitlines():
        if ":" not in line:
            continue
        k, _, v = line.partition(":")
        key = k.strip()
        val_raw = v.strip().strip('"').strip("'")
        low = val_raw.lower()
        if low in {"true", "false"}:
            meta[key] = low
        else:
            try:
                meta[key] = int(val_raw)
            except ValueError:
                try:
                    meta[key] = float(val_raw)
                except ValueError:
                    meta[key] = val_raw
    return meta, body


def _iter_knowledge_files(root: Path) -> Iterable[Path]:
    if not root.exists():
        return []
    return sorted(p for p in root.rglob("*.md") if p.is_file())


@lru_cache(maxsize=1)
def _build_index() -> VectorStoreIndex:
    settings = get_settings()

    logger.info("Inicializando embeddings %s...", settings.embedding_model)
    LISettings.embed_model = HuggingFaceEmbedding(model_name=settings.embedding_model)
    LISettings.llm = None

    docs: list[Document] = []
    for path in _iter_knowledge_files(settings.knowledge_path):
        raw = path.read_text(encoding="utf-8")
        meta, body = _parse_front_matter(raw)
        meta.setdefault("year", 0)
        meta.setdefault("confidential", "false")   
        meta.setdefault("allowed_roles", "viewer,analyst,admin")
        meta["file"] = path.name
        docs.append(Document(text=body, metadata=meta))

    if not docs:
        logger.warning("No se encontraron documentos en %s", settings.knowledge_path)
    else:
        logger.info("Indexando %d documentos desde %s", len(docs), settings.knowledge_path)

    return VectorStoreIndex.from_documents(docs)


def _build_filters(
    year: int | None,
    user_role: str,
) -> MetadataFilters | None:
    """Construye filtros de metadata para el retriever.

    - year=None -> no filtra por año.
    - confidential=True + rol != admin -> excluye (regla de seguridad).
    """
    filters: list[MetadataFilter] = []

    if year is not None:
        filters.append(MetadataFilter(key="year", value=int(year), operator=FilterOperator.EQ))

    if user_role != "admin":
        filters.append(
            MetadataFilter(key="confidential", value="false", operator=FilterOperator.EQ)
        )

    if not filters:
        return None
    return MetadataFilters(filters=filters, condition=FilterCondition.AND)


def retrieve(
    query: str,
    year: int | None = None,
    user_role: str = "viewer",
    top_k: int | None = None,
) -> list[SourceRef]:
    """Recupera pasajes relevantes con metadata filtering aplicado."""
    settings = get_settings()
    k = top_k or settings.rag_top_k
    index = _build_index()
    filters = _build_filters(year=year, user_role=user_role)

    retriever = index.as_retriever(similarity_top_k=k, filters=filters)
    nodes = retriever.retrieve(query)

    sources: list[SourceRef] = []
    for n in nodes:
        meta = dict(n.node.metadata or {})
        snippet = (n.node.get_content() or "").strip().replace("\n", " ")
        if len(snippet) > 320:
            snippet = snippet[:320] + "..."
        sources.append(
            SourceRef(
                file=str(meta.get("file", "unknown")),
                year=meta.get("year") if isinstance(meta.get("year"), int) else None,
                score=float(n.score) if n.score is not None else None,
                snippet=snippet,
            )
        )
    return sources


def format_context(sources: list[SourceRef]) -> str:
    """Formatea las fuentes recuperadas para inyectarlas en el system prompt."""
    if not sources:
        return "(sin documentos relevantes recuperados)"
    parts = []
    for i, s in enumerate(sources, start=1):
        header = f"[Doc {i}] file={s.file} year={s.year} score={s.score:.3f}" if s.score else f"[Doc {i}] file={s.file}"
        parts.append(f"{header}\n{s.snippet}")
    return "\n---\n".join(parts)
