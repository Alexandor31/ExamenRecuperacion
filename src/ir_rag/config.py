"""Application configuration loaded from environment variables."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


def _as_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def _as_int(name: str, default: int) -> int:
    value = os.getenv(name)
    return int(value) if value not in (None, "") else default


def _as_float(name: str, default: float) -> float:
    value = os.getenv(name)
    return float(value) if value not in (None, "") else default


def _optional_int(name: str) -> int | None:
    value = os.getenv(name)
    if value in (None, "", "0"):
        return None
    return int(value)


@dataclass(frozen=True)
class Settings:
    """Application settings loaded from environment variables."""

    data_dir: Path
    chroma_dir: Path
    collection_name: str
    corpus_dir: Path
    articles_dir: Path

    embedding_model: str
    reranker_model: str
    embedding_batch_size: int
    retrieval_candidates: int
    top_k: int
    max_chunks_per_document: int
    min_semantic_score: float
    min_rerank_score: float
    enable_reranker: bool

    chunk_size: int
    chunk_overlap: int
    min_chunk_chars: int
    max_context_chars: int

    llm_api_key: str
    llm_api_base: str
    llm_model: str
    llm_temperature: float
    llm_max_tokens: int
    request_timeout: int

    auto_build_index: bool
    max_documents: int | None
    log_level: str

    @classmethod
    def from_env(cls) -> "Settings":
        project_root = Path(__file__).resolve().parents[2]
        data_dir = Path(os.getenv("DATA_DIR", str(project_root / "data"))).expanduser().resolve()
        corpus_dir = Path(os.getenv("CORPUS_DIR", str(project_root / "corpus"))).expanduser().resolve()
        articles_dir = corpus_dir / "articles"

        settings = cls(
            data_dir=data_dir,
            chroma_dir=Path(os.getenv("CHROMA_DIR", str(data_dir / "chroma"))).expanduser().resolve(),
            collection_name=os.getenv("CHROMA_COLLECTION", "ir_corpus"),
            corpus_dir=corpus_dir,
            articles_dir=articles_dir,
            embedding_model=os.getenv(
                "EMBEDDING_MODEL", "sentence-transformers/all-MiniLM-L6-v2"
            ),
            reranker_model=os.getenv(
                "RERANKER_MODEL", "cross-encoder/ms-marco-MiniLM-L-6-v2"
            ),
            embedding_batch_size=_as_int("EMBEDDING_BATCH_SIZE", 128),
            retrieval_candidates=_as_int("RETRIEVAL_CANDIDATES", 20),
            top_k=_as_int("TOP_K", 5),
            max_chunks_per_document=_as_int("MAX_CHUNKS_PER_DOCUMENT", 2),
            min_semantic_score=_as_float("MIN_SEMANTIC_SCORE", 0.20),
            min_rerank_score=_as_float("MIN_RERANK_SCORE", 0.05),
            enable_reranker=_as_bool("ENABLE_RERANKER", True),
            chunk_size=_as_int("CHUNK_SIZE", 1200),
            chunk_overlap=_as_int("CHUNK_OVERLAP", 200),
            min_chunk_chars=_as_int("MIN_CHUNK_CHARS", 120),
            max_context_chars=_as_int("MAX_CONTEXT_CHARS", 14000),
            llm_api_key=os.getenv("LLM_API_KEY", os.getenv("GROQ_API_KEY", "")),
            llm_api_base=os.getenv(
                "LLM_API_BASE", "https://api.groq.com/openai/v1"
            ).rstrip("/"),
            llm_model=os.getenv("LLM_MODEL", "llama-3.3-70b-versatile"),
            llm_temperature=_as_float("LLM_TEMPERATURE", 0.1),
            llm_max_tokens=_as_int("LLM_MAX_TOKENS", 900),
            request_timeout=_as_int("REQUEST_TIMEOUT", 90),
            auto_build_index=_as_bool("AUTO_BUILD_INDEX", False),
            max_documents=_optional_int("MAX_DOCUMENTS"),
            log_level=os.getenv("LOG_LEVEL", "INFO").upper(),
        )
        settings.validate()
        return settings

    def validate(self) -> None:
        if self.chunk_size <= 0:
            raise ValueError("CHUNK_SIZE must be positive")
        if self.chunk_overlap < 0 or self.chunk_overlap >= self.chunk_size:
            raise ValueError("CHUNK_OVERLAP must be non-negative and smaller than CHUNK_SIZE")
        if self.min_chunk_chars <= 0:
            raise ValueError("MIN_CHUNK_CHARS must be positive")
        if self.max_context_chars <= 0:
            raise ValueError("MAX_CONTEXT_CHARS must be positive")
        if self.top_k <= 0 or self.retrieval_candidates < self.top_k:
            raise ValueError("RETRIEVAL_CANDIDATES must be greater than or equal to TOP_K")
        if self.embedding_batch_size <= 0:
            raise ValueError("EMBEDDING_BATCH_SIZE must be positive")
        if self.max_chunks_per_document <= 0:
            raise ValueError("MAX_CHUNKS_PER_DOCUMENT must be positive")
        if self.llm_temperature < 0 or self.llm_temperature > 2:
            raise ValueError("LLM_TEMPERATURE must be between 0 and 2")

    @property
    def manifest_path(self) -> Path:
        return self.data_dir / "index_manifest.json"
