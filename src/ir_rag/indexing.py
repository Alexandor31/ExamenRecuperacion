"""Build / rebuild the persistent vector index for the IR corpus."""
from __future__ import annotations

import json
import logging
import time
from dataclasses import asdict
from pathlib import Path
from typing import Callable

from .config import Settings
from .corpus import build_corpus, discover_sources
from .embeddings import EmbeddingService
from .models import SourceDocument
from .vector_store import VectorStore

LOGGER = logging.getLogger(__name__)


ProgressCallback = Callable[[int, int], None]


def build_index(
    settings: Settings,
    max_documents: int | None = None,
    progress: ProgressCallback | None = None,
    reset: bool = True,
    sources: list[SourceDocument] | None = None,
) -> dict:
    """Discover sources, extract chunks, embed them and persist to Chroma.

    Returns a stats dict with the number of documents / chunks indexed.

    If ``sources`` is provided, the corpus discovery step is skipped and the
    supplied list is used as-is. Otherwise, ``discover_sources`` is called on
    the configured corpus directories.
    """
    if sources is None:
        sources = discover_sources(settings.corpus_dir, settings.articles_dir)
    if not sources:
        raise RuntimeError(
            "No PDFs were found. Place the required books and articles in "
            f"{settings.corpus_dir}/ and {settings.articles_dir}/, or run "
            "scripts/download_corpus.py to fetch the open-access ones."
        )
    if max_documents:
        sources = sources[:max_documents]
    LOGGER.info("Building index from %d sources", len(sources))
    chunks, corpus_stats = build_corpus(
        sources,
        chunk_size=settings.chunk_size,
        chunk_overlap=settings.chunk_overlap,
        min_chars=settings.min_chunk_chars,
    )
    if not chunks:
        raise RuntimeError("Corpus extraction produced zero chunks.")

    store = VectorStore(
        settings.chroma_dir, settings.collection_name, settings.embedding_model
    )
    if reset:
        store.reset()

    embedder = EmbeddingService(settings.embedding_model, settings.embedding_batch_size)
    started = time.perf_counter()
    total = len(chunks)

    # Embed in batches to allow progress reporting.
    batch_size = settings.embedding_batch_size
    inserted = 0
    for start in range(0, total, batch_size):
        batch = chunks[start:start + batch_size]
        store.upsert_chunks(batch, embedder=embedder)
        inserted += len(batch)
        if progress:
            progress(inserted, total)
    elapsed = time.perf_counter() - started

    manifest = {
        "collection": settings.collection_name,
        "embedding_model": settings.embedding_model,
        "reranker_model": settings.reranker_model,
        "chunk_size": settings.chunk_size,
        "chunk_overlap": settings.chunk_overlap,
        "documents": [
            {
                "doc_id": s.doc_id,
                "title": s.title,
                "authors": list(s.authors),
                "year": s.year,
                "kind": s.kind,
                "file": str(Path(s.file_path).relative_to(settings.corpus_dir.parent))
                if settings.corpus_dir in Path(s.file_path).parents
                else s.file_path,
            }
            for s in sources
        ],
        "stats": {
            **corpus_stats,
            "collection_count": store.count,
            "embedding_seconds": round(elapsed, 2),
        },
        "built_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    settings.manifest_path.parent.mkdir(parents=True, exist_ok=True)
    settings.manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False))
    LOGGER.info("Manifest written to %s", settings.manifest_path)
    return manifest
