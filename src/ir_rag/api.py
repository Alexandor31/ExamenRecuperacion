"""FastAPI application exposing the IR RAG service."""
from __future__ import annotations

import logging
import os
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from .config import Settings
from .indexing import build_index
from .llm import LLMConfigurationError, LLMRequestError
from .rag import RAGPipeline, extract_question
from .vector_store import VectorStore

LOGGER = logging.getLogger(__name__)

# Public service metadata (consumed by / and /health).
SERVICE_NAME = "ir-rag-service"
SERVICE_DESCRIPTION = (
    "Web service that answers Information Retrieval questions using a "
    "Retrieval-Augmented Generation (RAG) pipeline backed by the course "
    "bibliography. Receives Markdown-formatted questions and returns "
    "evidence-grounded answers with bibliographic references."
)


# ---------- Request / Response schemas (Pydantic) ----------


class AnswerRequestIn(BaseModel):
    """Body for POST /answer."""

    question: str = Field(
        default="",
        description=(
            "Markdown-formatted question. Headings, bold, italic, lists, links "
            "and fenced code blocks are stripped automatically before retrieval. "
            "Must contain a non-empty question; otherwise the service returns "
            "HTTP 400 (missing/empty) or HTTP 422 (no question detected)."
        ),
    )


class EvidenceOut(BaseModel):
    evidence_id: str
    rank: int
    chunk_id: str
    doc_id: str
    title: str
    authors: list[str]
    year: int | None
    kind: str
    chapter: str
    section: str
    page_start: int
    page_end: int
    text: str
    semantic_score: float
    rerank_score: float | None


class AnswerResponseOut(BaseModel):
    question: str
    answer: str
    references: list[str]
    evidence: list[EvidenceOut]
    retrieval_ms: float
    generation_ms: float
    insufficient: bool
    warning: str | None = None
    candidates_considered: int | None = None


class HealthResponse(BaseModel):
    status: str
    collection: str
    chunks: int
    embedding_model: str
    reranker_model: str
    llm_configured: bool


class ServiceInfo(BaseModel):
    name: str
    description: str
    endpoints: list[dict]
    status_codes: dict


# ---------- Application factory ----------


def _index_count(settings: Settings) -> int:
    store = VectorStore(
        settings.chroma_dir, settings.collection_name, settings.embedding_model
    )
    return store.count


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        logging.basicConfig(
            level=getattr(logging, settings.log_level, logging.INFO),
            format="%(asctime)s %(levelname)s %(name)s :: %(message)s",
        )
        LOGGER.info("Starting %s", SERVICE_NAME)

        # Build the index eagerly if asked (HF Spaces startup).
        if settings.auto_build_index and _index_count(settings) == 0:
            LOGGER.info("AUTO_BUILD_INDEX=true → building index at startup")
            try:
                stats = build_index(settings)
                LOGGER.info("Index ready: %s", stats)
            except Exception as exc:
                LOGGER.exception("Auto-build failed: %s", exc)
        yield
        LOGGER.info("Shutting down %s", SERVICE_NAME)

    app = FastAPI(
        title=SERVICE_NAME,
        description=SERVICE_DESCRIPTION,
        version="1.0.0",
        lifespan=lifespan,
    )

    # Cached pipeline (re-built on first request).
    pipeline_state: dict = {"pipeline": None, "error": None}

    def _get_pipeline() -> RAGPipeline:
        if pipeline_state["pipeline"] is None:
            if pipeline_state["error"] is not None:
                raise pipeline_state["error"]
            try:
                pipeline_state["pipeline"] = RAGPipeline(settings)
            except Exception as exc:
                pipeline_state["error"] = exc
                raise
        return pipeline_state["pipeline"]

    # ---------- Error handlers ----------

    @app.exception_handler(LLMConfigurationError)
    async def llm_configuration_handler(request: Request, exc: LLMConfigurationError):
        return JSONResponse(
            status_code=503,
            content={
                "detail": str(exc),
                "component": "llm",
                "hint": (
                    "Configure the LLM_API_KEY environment variable. "
                    "On Hugging Face Spaces add it as a secret in Settings."
                ),
            },
        )

    @app.exception_handler(LLMRequestError)
    async def llm_request_handler(request: Request, exc: LLMRequestError):
        return JSONResponse(
            status_code=503,
            content={"detail": str(exc), "component": "llm"},
        )

    # ---------- Routes ----------

    @app.get("/", response_model=ServiceInfo)
    async def index() -> ServiceInfo:
        return ServiceInfo(
            name=SERVICE_NAME,
            description=SERVICE_DESCRIPTION,
            endpoints=[
                {"path": "/", "method": "GET", "purpose": "Service metadata"},
                {"path": "/health", "method": "GET", "purpose": "Health probe"},
                {"path": "/answer", "method": "POST", "purpose": "Main RAG endpoint"},
                {"path": "/docs", "method": "GET", "purpose": "OpenAPI / Swagger UI"},
                {"path": "/openapi.json", "method": "GET", "purpose": "OpenAPI schema"},
            ],
            status_codes={
                "200": "Solicitud procesada correctamente.",
                "400": "Solicitud inválida o ausencia del campo 'question'.",
                "404": "Endpoint o recurso no encontrado.",
                "422": "La solicitud es válida pero no fue posible identificar "
                       "preguntas en el contenido recibido.",
                "500": "Error interno del servidor.",
                "503": "El modelo, la base vectorial o algún componente "
                       "requerido no se encuentra disponible.",
            },
        )

    @app.get("/health", response_model=HealthResponse)
    async def health() -> HealthResponse:
        try:
            count = _index_count(settings)
        except Exception as exc:
            raise HTTPException(
                status_code=503,
                detail=(
                    f"Vector store unavailable: {exc}. The collection "
                    f"'{settings.collection_name}' could not be opened."
                ),
            ) from exc
        if count == 0:
            raise HTTPException(
                status_code=503,
                detail=(
                    "Vector store is empty. Trigger a build with "
                    "`python scripts/build_index.py --reset`."
                ),
            )
        return HealthResponse(
            status="ok",
            collection=settings.collection_name,
            chunks=count,
            embedding_model=settings.embedding_model,
            reranker_model=(
                settings.reranker_model if settings.enable_reranker else "disabled"
            ),
            llm_configured=bool(settings.llm_api_key),
        )

    @app.post("/answer", response_model=AnswerResponseOut)
    async def answer(body: AnswerRequestIn) -> AnswerResponseOut:
        question_md = (body.question or "").strip()
        if not question_md:
            raise HTTPException(
                status_code=400,
                detail="The 'question' field is required and cannot be empty.",
            )

        question = extract_question(question_md)
        if not question:
            # 422 — the request was syntactically valid but no question
            # could be extracted from the Markdown content.
            raise HTTPException(
                status_code=422,
                detail=(
                    "The request is valid but no question could be extracted "
                    "from the supplied Markdown content."
                ),
            )

        try:
            response = _get_pipeline().answer(body)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        # LLMConfigurationError and LLMRequestError are converted to 503
        # by the dedicated exception handlers above.

        return AnswerResponseOut(
            question=response.question,
            answer=response.answer,
            references=list(response.references),
            evidence=[EvidenceOut(**item) for item in response.evidence],
            retrieval_ms=response.retrieval_ms,
            generation_ms=response.generation_ms,
            insufficient=response.insufficient,
            warning=response.warning,
        )

    @app.get("/stats")
    async def stats() -> dict:
        try:
            count = _index_count(settings)
        except Exception as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        return {
            "collection": settings.collection_name,
            "chunks": count,
            "embedding_model": settings.embedding_model,
            "reranker_model": (
                settings.reranker_model if settings.enable_reranker else "disabled"
            ),
            "retrieval_candidates": settings.retrieval_candidates,
            "top_k": settings.top_k,
        }

    @app.exception_handler(404)
    async def not_found_handler(request: Request, exc: HTTPException):
        return JSONResponse(
            status_code=404,
            content={
                "detail": (
                    f"Endpoint '{request.method} {request.url.path}' was not found."
                )
            },
        )

    return app


# Module-level app for `uvicorn ir_rag.api:app` use in development.
# This is a thin wrapper that delegates to get_app() so that environment
# variables are re-read at every start (useful for tests and HF Spaces).
def _app_factory() -> FastAPI:
    return create_app(Settings.from_env())


def get_app() -> FastAPI:
    """Public ASGI factory used by `uvicorn ir_rag.api:get_app --factory`."""
    return _app_factory()


# Alias so that `uvicorn ir_rag.api:app` also works.
app = get_app()
