"""Tests for the RAG orchestration layer."""
from __future__ import annotations

import pytest

from ir_rag.models import AnswerRequest, Evidence, RetrievalOutcome
from ir_rag.rag import RAGPipeline, extract_question


def test_extract_question_strips_markdown():
    md = (
        "# Pregunta\n"
        "¿Qué es el modelo **BM25** y cómo se usa en *information retrieval*?\n"
        "\n"
        "- Es importante destacar\n"
        "- que es robusto\n"
    )
    out = extract_question(md)
    assert "BM25" in out
    assert "information retrieval" in out
    assert "#" not in out
    assert "**" not in out
    assert "- " not in out


def test_extract_question_strips_code_fences_and_links():
    md = (
        "Cómo se computa la métrica [NDCG](https://en.wikipedia.org/wiki/NDCG)\n"
        "```python\nprint('skip me')\n```\n"
        "según el libro?"
    )
    out = extract_question(md)
    assert "NDCG" in out
    assert "print(" not in out
    assert "https://" not in out


def test_pipeline_rejects_empty_question():
    from ir_rag.config import Settings

    settings = Settings.from_env()
    pipeline = RAGPipeline(settings)
    with pytest.raises(ValueError):
        pipeline.answer(AnswerRequest(question=""))


def test_insufficient_branch_when_no_evidence(monkeypatch):
    from ir_rag.config import Settings

    settings = Settings.from_env()
    pipeline = RAGPipeline(settings)

    # Stub retriever to return no evidence.
    class _Stub:
        def retrieve(self, query):
            return RetrievalOutcome(
                query=query,
                evidence=tuple(),
                insufficient=True,
                retrieval_ms=0.0,
                warning="no candidates",
            )

    pipeline.retriever = _Stub()  # type: ignore[assignment]
    response = pipeline.answer(AnswerRequest(question="hola"))
    assert response.insufficient
    assert "no contiene" in response.answer.lower() or "corpus" in response.answer.lower()


def test_format_references_includes_pages_and_scores():
    from ir_rag.config import Settings

    settings = Settings.from_env()
    pipeline = RAGPipeline(settings)
    evidence = [
        Evidence(
            evidence_id="E1",
            rank=1,
            chunk_id="abc:p12:c0001",
            doc_id="manning-2009",
            title="An Introduction to Information Retrieval",
            authors=("Manning", "Raghavan", "Schütze"),
            year=2009,
            kind="book",
            chapter="1 Boolean retrieval",
            section="1.1 First example",
            page_start=12,
            page_end=13,
            text="...",
            semantic_score=0.42,
            rerank_score=0.97,
        )
    ]
    formatted = pipeline._format_references(evidence)
    assert formatted and "Manning" in formatted[0]
    assert "pp. 12–13" in formatted[0]
    assert "1 Boolean retrieval" in formatted[0]
