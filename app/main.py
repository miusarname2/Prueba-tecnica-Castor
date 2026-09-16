from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app import __version__
from app.config import get_settings
from app.routers import chat as chat_router
from app.routers import health as health_router


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title="ERP-Agent MVP",
        version=__version__,
        description=(
            "Prototipo funcional: agente ERP con LangChain (function calling), "
            "RAG con LlamaIndex (metadata filtering), FastAPI con streaming SSE "
            "y guardrails contra prompt injection. Proveedor LLM por defecto: **Groq**."
        ),
        openapi_tags=[
            {"name": "Health", "description": "Chequeos de salud."},
            {"name": "Chat", "description": "Interacción con el agente."},
        ],
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins_list(),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(health_router.router)
    app.include_router(chat_router.router)

    web_dir = settings.project_root / "web"
    if web_dir.exists():
        app.mount("/web", StaticFiles(directory=str(web_dir), html=False), name="web")

        @app.get("/ui", include_in_schema=False)
        async def _ui() -> FileResponse:
            return FileResponse(web_dir / "index.html")

    @app.exception_handler(Exception)
    async def _unhandled(_: Request, exc: Exception):
        logging.getLogger("app").exception("Unhandled error")
        return JSONResponse(
            status_code=500,
            content={"error": "internal_error", "detail": str(exc)},
        )

    return app


app = create_app()
