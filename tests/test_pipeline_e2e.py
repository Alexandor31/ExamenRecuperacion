"""End-to-end integration test for the RAG pipeline.

This test verifies that the full chain (question parsing → retrieval →
answer formatting → response assembly) works against the real Chroma index
without needing a live LLM. The LLM is replaced by a deterministic stub that
records the prompt and returns a fixed answer.
"""
from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

import pytest


class _StubLLM:
    """Deterministic stand-in for the real OpenAI-compatible LLM."""

    last_prompt: str | None = None

    def generate(self, query: str, context: str) -> str:
        _StubLLM.last_prompt = context
        return (
            "According to [E1], the response is grounded in the corpus. "
            "No external knowledge was used. [E2] corroborates this."
        )


@pytest.fixture(scope="module")
def pipeline():
    """Build a tiny index from one article and return the pipeline."""
    project = Path(__file__).resolve().parents[1]
    corpus = project / "corpus"
    if not (corpus / "articles" / "robertson-bm25-perspective.pdf").exists():
        pytest.skip("Robertson article missing — corpus incomplete")

    # Isolated data directory for this test only.
    tmp_dir = Path(tempfile.mkdtemp(prefix="rag_e2e_"))
    os.environ["DATA_DIR"] = str(tmp_dir)
    os.environ["CHROMA_DIR"] = str(tmp_dir / "chroma")
    os.environ["CHROMA_COLLECTION"] = "rag_e2e"
    os.environ["AUTO_BUILD_INDEX"] = "false"
    os.environ.pop("LLM_API_KEY", None)

    # Reset modules so env vars are picked up.
    from importlib import reload
    from ir_rag import config as cfg
    reload(cfg)
    from ir_rag import vector_store as vs_mod
    reload(vs_mod)
    from ir_rag import retriever as rt_mod
    reload(rt_mod)
    from ir_rag import rag as rag_mod
    reload(rag_mod)

    settings = cfg.Settings.from_env()

    # Build a tiny index with just the Robertson article.
    from ir_rag.corpus import discover_sources
    from ir_rag.indexing import build_index

    sources = [
        s for s in discover_sources(settings.corpus_dir, settings.articles_dir)
        if s.doc_id == "robertson-zaragoza-2009"
    ]
    if not sources:
        pytest.skip("Robertson source missing from corpus")

    build_index(settings, sources=sources)

    pipeline_obj = rag_mod.RAGPipeline(settings, llm=_StubLLM())
    yield pipeline_obj

    shutil.rmtree(tmp_dir, ignore_errors=True)


def test_pipeline_returns_structured_response(pipeline):
    response = pipeline.answer_text("What is BM25?")
    assert response.question == "What is BM25?"
    assert "[E1]" in response.answer
    assert response.evidence
    assert response.retrieval_ms >= 0
    assert response.insufficient is False


def test_pipeline_includes_separated_scores(pipeline):
    response = pipeline.answer_text("What is BM25?")
    ev = response.evidence[0]
    # Both scores are required per exam section 4.
    assert isinstance(ev.semantic_score, float)
    assert ev.rerank_score is not None
    assert ev.rerank_score != ev.semantic_score  # cross-encoder ≠ cosine similarity


def test_pipeline_includes_references_and_chunk_ids(pipeline):
    response = pipeline.answer_text("What is BM25?")
    assert response.evidence[0].chunk_id.startswith("robertson-zaragoza-2009:")
    # The references list (separate field on AnswerResponse) contains page info.
    from ir_rag.models import AnswerRequest
    full = pipeline.answer(AnswerRequest(question="What is BM25?"))
    assert full.references
    assert any("pp." in ref or "p." in ref for ref in full.references)
    assert any("Robertson" in ref for ref in full.references)


def test_pipeline_insufficient_branch(pipeline):
    """A query completely outside the corpus should trigger insufficient."""
    response = pipeline.answer_text("Cuál es la capital política de Mongolia?")
    assert response.insufficient
    assert "corpus" in response.answer.lower() or "no contiene" in response.answer.lower()
