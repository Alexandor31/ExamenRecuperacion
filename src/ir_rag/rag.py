"""RAG orchestration: parse Markdown question, retrieve, generate, format."""
from __future__ import annotations

import logging
import re
import time
from typing import Iterable

from .config import Settings
from .llm import OpenAICompatibleLLM
from .models import (
    AnswerRequest,
    AnswerResponse,
    Evidence,
    RAGResult,
    RetrievalOutcome,
)
from .retriever import Retriever

LOGGER = logging.getLogger(__name__)

# Heuristics used when extracting the actual question from a Markdown payload.
# The exam specifies that questions arrive in Markdown, so we strip common
# Markdown noise (code fences, headings, bold, italic, lists) and keep the
# remaining prose as the question text.
_MD_HEADING = re.compile(r"^\s{0,3}#{1,6}\s+", flags=re.MULTILINE)
_MD_BOLD_ITALIC = re.compile(r"(\*\*|__|\*|_)(.*?)\1", flags=re.DOTALL)
_MD_LIST = re.compile(r"^\s{0,3}[-*+]\s+", flags=re.MULTILINE)
_MD_LINK = re.compile(r"\[([^\]]+)\]\([^)]+\)")
_MD_INLINE_CODE = re.compile(r"`([^`]+)`")
_MD_FENCE = re.compile(r"```.*?```", flags=re.DOTALL)
_SPANISH_HINTS = re.compile(
    r"\b(qué|cómo|cuál|cuáles|dónde|por qué|sobre|artículos|investigación|"
    r"modelos|aprendizaje|información|recuperación)\b",
    flags=re.IGNORECASE,
)


def extract_question(markdown_text: str) -> str:
    """Return the user-facing question stripped of Markdown noise."""
    if not markdown_text:
        return ""
    text = markdown_text.strip()
    # Remove fenced code blocks.
    text = _MD_FENCE.sub("", text)
    # Replace links with their visible label.
    text = _MD_LINK.sub(r"\1", text)
    # Drop inline code (often commands or identifiers we still want to see).
    text = _MD_INLINE_CODE.sub(r"\1", text)
    # Drop heading markers.
    text = _MD_HEADING.sub("", text)
    # Drop bullet markers at line starts.
    text = _MD_LIST.sub("", text)
    # Collapse bold/italic markers but keep the inner text.
    text = _MD_BOLD_ITALIC.sub(r"\2", text)
    # Collapse runs of blank lines.
    text = re.sub(r"\n{3,}", "\n\n", text)
    # Collapse internal whitespace.
    text = re.sub(r"[ \t]+", " ", text)
    return text.strip()


class RAGPipeline:
    """End-to-end RAG pipeline: question parse → retrieve → generate."""

    def __init__(
        self,
        settings: Settings,
        retriever: Retriever | None = None,
        llm: OpenAICompatibleLLM | None = None,
    ):
        self.settings = settings
        self.retriever = retriever or Retriever(settings)
        self.llm = llm or OpenAICompatibleLLM(settings)

    # ---------- Helpers ----------

    def _insufficient_answer(self, query: str) -> str:
        if _SPANISH_HINTS.search(query):
            return (
                "El corpus no contiene evidencia suficientemente relevante para "
                "responder esta pregunta con confianza. Reformúlala o consulta "
                "sobre un tema presente en la bibliografía del curso."
            )
        return (
            "The corpus does not contain sufficiently relevant evidence to "
            "answer this question confidently. Try rephrasing it or asking "
            "about another topic covered by the course bibliography."
        )

    def _build_context(self, evidence: Iterable[Evidence]) -> str:
        blocks: list[str] = []
        used = 0
        for item in evidence:
            block = (
                f"[{item.evidence_id}] {item.title} "
                f"({item.kind}, pages {item.page_start}-{item.page_end})\n"
                f"{item.text}"
            )
            if blocks and used + len(block) > self.settings.max_context_chars:
                break
            blocks.append(block)
            used += len(block)
        return "\n\n".join(blocks)

    def _format_references(self, evidence: Iterable[Evidence]) -> tuple[str, ...]:
        return tuple(ev.reference() for ev in evidence)

    # ---------- Public API ----------

    def answer(self, request: AnswerRequest) -> AnswerResponse:
        """Process one Markdown-formatted question and return an AnswerResponse."""
        question_md = request.question
        question = extract_question(question_md)
        if not question:
            raise ValueError("The question is empty after stripping Markdown markup.")

        retrieval = self.retriever.retrieve(question)
        answer_text: str
        insufficient = retrieval.insufficient
        warning = retrieval.warning
        generation_ms = 0.0

        if retrieval.insufficient:
            answer_text = self._insufficient_answer(question)
        else:
            context = self._build_context(retrieval.evidence)
            started = time.perf_counter()
            try:
                raw = self.llm.generate(question, context)
            except Exception as exc:
                LOGGER.exception("LLM call failed: %s", exc)
                raise
            generation_ms = (time.perf_counter() - started) * 1000
            if raw.startswith("[INSUFFICIENT_CONTEXT]"):
                insufficient = True
                answer_text = raw.removeprefix("[INSUFFICIENT_CONTEXT]").strip()
                if not answer_text:
                    answer_text = self._insufficient_answer(question)
            else:
                answer_text = raw

        references = self._format_references(retrieval.evidence)
        evidence_payload = [ev.to_dict() for ev in retrieval.evidence]

        return AnswerResponse(
            question=question,
            answer=answer_text,
            references=references,
            evidence=tuple(evidence_payload),
            retrieval_ms=retrieval.retrieval_ms,
            generation_ms=generation_ms,
            insufficient=insufficient,
            warning=warning,
        )

    # ---------- Backwards-compatible API ----------

    def answer_text(self, question_md: str) -> RAGResult:
        """Return a RAGResult object instead of the API-shaped AnswerResponse."""
        request = AnswerRequest(question=question_md)
        response = self.answer(request)
        evidence_objs = tuple(
            Evidence(
                evidence_id=item["evidence_id"],
                rank=item["rank"],
                chunk_id=item["chunk_id"],
                doc_id=item["doc_id"],
                title=item["title"],
                authors=tuple(item.get("authors", [])),
                year=item.get("year"),
                kind=item.get("kind", ""),
                chapter=item.get("chapter", ""),
                section=item.get("section", ""),
                page_start=item.get("page_start", 0),
                page_end=item.get("page_end", 0),
                text=item["text"],
                semantic_score=item["semantic_score"],
                rerank_score=item.get("rerank_score"),
            )
            for item in response.evidence
        )
        return RAGResult(
            question=response.question,
            answer=response.answer,
            evidence=evidence_objs,
            insufficient=response.insufficient,
            retrieval_ms=response.retrieval_ms,
            generation_ms=response.generation_ms,
            warning=response.warning,
        )
