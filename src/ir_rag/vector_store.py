"""ChromaDB wrapper for the IR RAG service."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Iterable

import chromadb
from chromadb.config import Settings as ChromaSettings

from .embeddings import EmbeddingService
from .models import Chunk

LOGGER = logging.getLogger(__name__)


class VectorStore:
    """Persistent Chroma collection with cosine similarity."""

    def __init__(self, persist_dir: Path, collection_name: str, embedding_model: str):
        self.persist_dir = Path(persist_dir)
        self.collection_name = collection_name
        self.embedding_model_name = embedding_model
        self.persist_dir.mkdir(parents=True, exist_ok=True)
        self._client = chromadb.PersistentClient(
            path=str(self.persist_dir),
            settings=ChromaSettings(anonymized_telemetry=False, allow_reset=True),
        )
        self._collection = self._client.get_or_create_collection(
            name=self.collection_name,
            metadata={"hnsw:space": "cosine"},
        )

    # ---------- Properties ----------

    @property
    def count(self) -> int:
        return self._collection.count()

    # ---------- Embeddings ----------

    def _embedder(self) -> EmbeddingService:
        return EmbeddingService(self.embedding_model_name)

    # ---------- Mutations ----------

    def reset(self) -> None:
        """Drop and recreate the collection."""
        LOGGER.warning("Resetting collection '%s'", self.collection_name)
        self._client.delete_collection(self.collection_name)
        self._collection = self._client.get_or_create_collection(
            name=self.collection_name,
            metadata={"hnsw:space": "cosine"},
        )

    def upsert_chunks(
        self,
        chunks: Iterable[Chunk],
        embedder: EmbeddingService | None = None,
    ) -> int:
        chunks = list(chunks)
        if not chunks:
            return 0
        embedder = embedder or self._embedder()
        texts = [c.embedding_text for c in chunks]
        vectors = embedder.encode_documents(texts)
        ids = [c.chunk_id for c in chunks]
        documents = [c.text for c in chunks]
        metadatas = [c.metadata for c in chunks]
        self._collection.upsert(
            ids=ids,
            embeddings=vectors,
            documents=documents,
            metadatas=metadatas,
        )
        LOGGER.info("Upserted %d chunks into '%s'", len(chunks), self.collection_name)
        return len(chunks)

    # ---------- Retrieval ----------

    def query(
        self,
        query_vector: list[float],
        top_k: int,
    ) -> list[dict]:
        """Return the top-k candidates for a query vector.

        Each candidate dict contains: chunk_id, text, metadata, semantic_score,
        distance. ``semantic_score`` is the cosine *similarity* (1 - distance)
        which is the natural retrieval score to report.
        """
        if self._collection.count() == 0:
            return []
        response = self._collection.query(
            query_embeddings=[query_vector],
            n_results=top_k,
            include=["documents", "metadatas", "distances"],
        )
        ids = response.get("ids", [[]])[0]
        documents = response.get("documents", [[]])[0]
        metadatas = response.get("metadatas", [[]])[0]
        distances = response.get("distances", [[]])[0]
        candidates: list[dict] = []
        for cid, doc, meta, dist in zip(ids, documents, metadatas, distances):
            similarity = max(0.0, 1.0 - float(dist))
            candidates.append({
                "chunk_id": cid,
                "text": doc,
                "metadata": dict(meta) if meta else {},
                "distance": float(dist),
                "semantic_score": similarity,
            })
        return candidates
