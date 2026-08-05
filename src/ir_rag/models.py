"""Domain models for the IR RAG service."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field


@dataclass(frozen=True)
class SourceDocument:
    """Bibliographic source loaded into the corpus."""

    doc_id: str
    title: str
    authors: tuple[str, ...]
    year: int | None
    kind: str  # "book" or "article"
    file_path: str
    chapter_hint: str = ""

    def citation(self) -> str:
        authors = ", ".join(self.authors) if self.authors else "Unknown"
        year = f" ({self.year})" if self.year else ""
        return f"{authors}{year}. {self.title} [{self.kind}]"


@dataclass(frozen=True)
class Chunk:
    """A chunk of text extracted from a source document."""

    chunk_id: str
    doc_id: str
    title: str
    authors: tuple[str, ...]
    year: int | None
    kind: str
    chapter: str
    section: str
    page_start: int
    page_end: int
    text: str
    chunk_index: int

    @property
    def embedding_text(self) -> str:
        """Text used to produce the embedding. Adds bibliographic context."""
        header_parts = [f"Title: {self.title}"]
        if self.authors:
            header_parts.append(f"Authors: {', '.join(self.authors)}")
        if self.year:
            header_parts.append(f"Year: {self.year}")
        if self.chapter:
            header_parts.append(f"Chapter: {self.chapter}")
        if self.section:
            header_parts.append(f"Section: {self.section}")
        header_parts.append(f"Pages: {self.page_start}-{self.page_end}")
        return "\n".join(header_parts) + "\n\n" + self.text

    @property
    def metadata(self) -> dict[str, str | int]:
        return {
            "doc_id": self.doc_id,
            "title": self.title,
            "authors": ", ".join(self.authors),
            "year": self.year or 0,
            "kind": self.kind,
            "chapter": self.chapter,
            "section": self.section,
            "page_start": self.page_start,
            "page_end": self.page_end,
            "chunk_index": self.chunk_index,
        }

    def reference(self) -> str:
        """Returns a structured bibliographic reference (markdown)."""
        authors = ", ".join(self.authors) if self.authors else "Unknown"
        year = f" ({self.year})" if self.year else ""
        page_range = (
            f"p. {self.page_start}"
            if self.page_start == self.page_end
            else f"pp. {self.page_start}–{self.page_end}"
        )
        where = self.chapter or self.section
        location = f"{where} — {page_range}" if where else page_range
        return f"- {authors}{year}. *{self.title}*. {location}."


@dataclass(frozen=True)
class Evidence:
    """A chunk used as evidence in a RAG answer."""

    evidence_id: str
    rank: int
    chunk_id: str
    doc_id: str
    title: str
    authors: tuple[str, ...]
    year: int | None
    kind: str
    chapter: str
    section: str
    page_start: int
    page_end: int
    text: str
    semantic_score: float
    rerank_score: float | None = None

    def to_dict(self) -> dict:
        return asdict(self)

    def reference(self) -> str:
        """Returns a structured bibliographic reference (Markdown)."""
        authors = ", ".join(self.authors) if self.authors else "Unknown"
        year = f" ({self.year})" if self.year else ""
        page_range = (
            f"p. {self.page_start}"
            if self.page_start == self.page_end
            else f"pp. {self.page_start}–{self.page_end}"
        )
        where = self.chapter or self.section
        location = f"{where} — {page_range}" if where else page_range
        return f"- {authors}{year}. *{self.title}*. {location}."


@dataclass(frozen=True)
class RetrievalOutcome:
    query: str
    evidence: tuple[Evidence, ...]
    insufficient: bool
    retrieval_ms: float
    warning: str | None = None
    candidates_considered: int = 0


@dataclass(frozen=True)
class RAGResult:
    question: str  # The extracted/identified question
    answer: str
    evidence: tuple[Evidence, ...]
    insufficient: bool
    retrieval_ms: float
    generation_ms: float
    warning: str | None = None
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        data = asdict(self)
        data["evidence"] = [e.to_dict() for e in self.evidence]
        return data


# ---------- HTTP API models ----------


@dataclass(frozen=True)
class AnswerRequest:
    """Payload for the main /answer endpoint."""

    question: str  # Markdown-formatted question


@dataclass(frozen=True)
class AnswerResponse:
    """Response payload (matches exam section 1 and section 8)."""

    question: str
    answer: str
    references: tuple[str, ...]
    evidence: tuple[dict, ...]  # evidence metadata + scores
    retrieval_ms: float
    generation_ms: float
    insufficient: bool
    warning: str | None = None
