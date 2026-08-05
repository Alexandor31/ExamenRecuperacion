"""Sentence-Transformer wrapper used for query and passage encoding."""
from __future__ import annotations

import logging
from functools import cached_property

from sentence_transformers import SentenceTransformer

LOGGER = logging.getLogger(__name__)


class EmbeddingService:
    """Wraps a sentence-transformer model and exposes a small batch API."""

    def __init__(self, model_name: str, batch_size: int = 128):
        self.model_name = model_name
        self.batch_size = batch_size

    @cached_property
    def model(self) -> SentenceTransformer:
        LOGGER.info("Loading embedding model '%s'…", self.model_name)
        model = SentenceTransformer(self.model_name)
        return model

    def encode_query(self, query: str) -> list[float]:
        if not query or not query.strip():
            raise ValueError("The query cannot be empty")
        vector = self.model.encode(
            [query.strip()],
            convert_to_numpy=True,
            normalize_embeddings=True,
            show_progress_bar=False,
        )[0]
        return vector.tolist()

    def encode_documents(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        LOGGER.info("Embedding %d chunks (batch=%d)…", len(texts), self.batch_size)
        vectors = self.model.encode(
            texts,
            batch_size=self.batch_size,
            convert_to_numpy=True,
            normalize_embeddings=True,
            show_progress_bar=False,
        )
        return vectors.tolist()
