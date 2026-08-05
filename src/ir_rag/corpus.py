"""PDF ingestion: extract, clean, detect chapters/sections, and chunk."""
from __future__ import annotations

import hashlib
import logging
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Iterator

import fitz  # PyMuPDF

from .models import Chunk, SourceDocument

LOGGER = logging.getLogger(__name__)

# ---------- Bibliographic registry ----------
#
# Bibliografía obligatoria (examen sección 2):
#   * Baeza-Yates & Ribeiro-Neto — Modern Information Retrieval
#   * Manning, Raghavan & Schütze — Introduction to Information Retrieval
# Bibliografía complementaria (sección 2.1):
#   * Al menos un libro adicional
#   * Tres artículos científicos
#
# IMPORTANTE: los campos "authors", "title", "year" se usan SOLO para
# etiquetar los chunks. El contenido textual siempre proviene del PDF,
# nunca de un modelo de lenguaje (examen, sección 2.1: "No se permite
# incorporar al corpus contenido generado por modelos de lenguaje").

CORPUS_REGISTRY: dict[str, dict] = {
    # Obligatorios
    "baeza-yates-modern-ir.pdf": {
        "title": "Modern Information Retrieval",
        "authors": ("Ricardo Baeza-Yates", "Berthier Ribeiro-Neto"),
        "year": 1999,
        "kind": "book",
        "doc_id": "baeza-yates-1999",
    },
    "manning-introduction-ir.pdf": {
        "title": "An Introduction to Information Retrieval",
        "authors": ("Christopher D. Manning", "Prabhakar Raghavan", "Hinrich Schütze"),
        "year": 2009,
        "kind": "book",
        "doc_id": "manning-2009",
    },
    # Complementarios — libros
    "jurafsky-slp3.pdf": {
        "title": "Speech and Language Processing",
        "authors": ("Daniel Jurafsky", "James H. Martin"),
        "year": 2026,
        "kind": "book",
        "doc_id": "jurafsky-martin-2026",
    },
    # Complementarios — artículos (se buscan en corpus/articles/)
    "robertson-bm25-perspective.pdf": {
        "title": "The Probabilistic Relevance Framework: BM25 and Beyond",
        "authors": ("Stephen Robertson", "Hugo Zaragoza"),
        "year": 2009,
        "kind": "article",
        "doc_id": "robertson-zaragoza-2009",
    },
    "karpukhin-dpr-2020.pdf": {
        "title": "Dense Passage Retrieval for Open-Domain Question Answering",
        "authors": (
            "Vladimir Karpukhin", "Barlas Oğuz", "Sewon Min", "Patrick Lewis",
            "Ledell Wu", "Sergey Edunov", "Danqi Chen", "Wen-tau Yih",
        ),
        "year": 2020,
        "kind": "article",
        "doc_id": "karpukhin-etal-2020",
    },
    "nogueira-monobert-2019.pdf": {
        "title": "Passage Re-ranking with BERT",
        "authors": ("Rodrigo Nogueira", "Kyunghyun Cho"),
        "year": 2019,
        "kind": "article",
        "doc_id": "nogueira-cho-2019",
    },
}


# ---------- Text cleaning helpers ----------


_WHITESPACE = re.compile(r"[ \t]+")
_BLANK_LINES = re.compile(r"\n{3,}")
# Match headers/footers containing short numeric patterns (page numbers)
# and short strings (<= 80 chars) that repeat on many pages.
REPEATED_PAGES_THRESHOLD_RATIO = 0.05  # 5 % of pages is a safe noise floor.
REPEATED_PAGES_THRESHOLD = 10  # Absolute minimum to qualify as noise.
_HYPHEN_BREAK = re.compile(r"(\w)-\n(\w)")


def clean_text(value: str) -> str:
    """Collapse whitespace and normalise newlines in a block of text."""
    if not value:
        return ""
    value = value.replace("\r\n", "\n").replace("\r", "\n")
    # Repair hyphenated line breaks from PDF wrapping
    value = _HYPHEN_BREAK.sub(r"\1\2", value)
    value = _WHITESPACE.sub(" ", value)
    value = _BLANK_LINES.sub("\n\n", value)
    return value.strip()


@dataclass
class _PageText:
    page_number: int  # 1-indexed (printed page, may differ from PDF index)
    text: str
    chapter: str = ""
    section: str = ""


def _page_pdf_index_to_printed(pdf_index: int) -> int:
    """Books often have roman-numbered front matter; printed page = pdf_index + 1
    for first page after front matter. For simplicity we expose 1-indexed pages
    using the PDF page index + 1. The notebook and JSON report both surface this."""
    return pdf_index + 1


def _detect_repeated_lines(pages: list[_PageText]) -> set[str]:
    """Identify lines that repeat on many pages (likely headers/footers).

    The threshold is relative to the total number of pages so that this works
    for short articles and long books alike. We also exclude very short tokens
    (single characters, symbols, plain numbers) which would otherwise be matched
    by coincidental repetition in equations, references or captions.
    """
    counter: Counter[str] = Counter()
    for page in pages:
        for line in page.text.splitlines():
            candidate = line.strip()
            if not candidate or len(candidate) > 90:
                continue
            # Skip very short tokens (likely math symbols, single-letter vars).
            if len(candidate) <= 2:
                continue
            # Skip plain numbers / dot-patterns that are likely page or section indices.
            if candidate.replace(".", "").replace("-", "").isdigit():
                continue
            counter[candidate] += 1
    threshold = max(
        REPEATED_PAGES_THRESHOLD,
        int(len(pages) * REPEATED_PAGES_THRESHOLD_RATIO),
    )
    return {
        line for line, count in counter.items()
        if count >= threshold
    }


def _strip_headers_footers(pages: list[_PageText], noise: set[str]) -> None:
    """Remove repeated headers/footers from each page's text in-place."""
    if not noise:
        return
    for page in pages:
        lines = page.text.splitlines()
        kept = [
            line for line in lines
            if line.strip() not in noise
            # Drop very short lines that are JUST a page number.
            or (len(line.strip()) <= 3 and line.strip().isdigit())
        ]
        page.text = "\n".join(kept).strip()


def _extract_text_with_fonts(page: fitz.Page) -> tuple[str, list[dict]]:
    """Extract text along with span metadata for heading detection."""
    text_dict = page.get_text("dict")
    blocks = []
    for block in text_dict.get("blocks", []):
        if block.get("type") != 0:
            continue
        spans = []
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                spans.append({
                    "text": span.get("text", ""),
                    "size": round(span.get("size", 0), 2),
                    "flags": span.get("flags", 0),
                    "font": span.get("font", ""),
                })
        blocks.append({"spans": spans})
    raw = page.get_text("text")
    return raw, blocks


_HEADING_SIZE_DELTA = 1.5  # font size 1.5pt larger than median = heading candidate
# Minimum font size for a heading. The Contents pages of academic books use
# the body font (around 10pt) for chapter and section entries, so this
# threshold filters them out.
_MIN_HEADING_SIZE = 11.5
_SECTION_NUMBER_RE = re.compile(
    r"^\s*(\d+(?:\.\d+){1,3})\s+(.+)$"  # e.g. "9.1 Relevance feedback"
)
_SECTION_BARE_NUMBER_RE = re.compile(
    r"^\s*(\d+(?:\.\d+){1,3})\s*$"  # e.g. "9.1" on its own line
)
_CHAPTER_NUMBER_RE = re.compile(
    r"^\s*(\d{1,2})\s+(.{2,})$"  # e.g. "1 Boolean retrieval"
)
_CHAPTER_BARE_NUMBER_RE = re.compile(r"^\s*(\d{1,2})\s*$")


def _classify_heading(
    line_text: str,
    line_size: float,
    is_bold: bool,
    all_lines: list[tuple[str, float, bool]],
) -> tuple[str, str] | None:
    """Classify a line as 'chapter', 'section' or None.

    A line qualifies as a heading when:
      * it is rendered in BOLD (flags bit 16 set), AND
      * its font size is >= _MIN_HEADING_SIZE (filters out TOC entries which
        use the body font size).
    Headings additionally need to match a numbering pattern so that running
    text is never mistaken for a heading.
    """
    if not line_text or len(line_text) > 160:
        return None
    if not is_bold or line_size < _MIN_HEADING_SIZE:
        return None

    section_match = _SECTION_NUMBER_RE.match(line_text)
    if section_match:
        return ("section", line_text)

    chapter_match = _CHAPTER_NUMBER_RE.match(line_text)
    if chapter_match:
        return ("chapter", line_text)

    # The section / chapter number is sometimes printed on its own line
    # ("1" or "9.1") in larger bold font, followed by the title on the next
    # line. Capture it here and patch the title in the caller.
    bare_section = _SECTION_BARE_NUMBER_RE.match(line_text)
    if bare_section and 10.0 <= line_size <= 30.0:
        return ("section_number", line_text.strip())

    bare_chapter = _CHAPTER_BARE_NUMBER_RE.match(line_text)
    if bare_chapter and line_size >= 24.0:
        return ("chapter_number", line_text.strip())

    return None


# ---------- Public API ----------


def discover_sources(corpus_dir: Path, articles_dir: Path) -> list[SourceDocument]:
    """Find all PDFs in the corpus folders and return SourceDocument objects."""
    sources: list[SourceDocument] = []
    for pdf_path in sorted(corpus_dir.glob("*.pdf")):
        meta = CORPUS_REGISTRY.get(pdf_path.name.lower())
        if meta is None:
            LOGGER.warning(
                "PDF '%s' no está registrado en CORPUS_REGISTRY; se omitirá. "
                "Añade su entrada en src/ir_rag/corpus.py para incluirlo.",
                pdf_path.name,
            )
            continue
        sources.append(
            SourceDocument(
                doc_id=meta["doc_id"],
                title=meta["title"],
                authors=tuple(meta["authors"]),
                year=meta["year"],
                kind=meta["kind"],
                file_path=str(pdf_path),
                chapter_hint="",
            )
        )
    for pdf_path in sorted(articles_dir.glob("*.pdf")):
        meta = CORPUS_REGISTRY.get(pdf_path.name.lower())
        if meta is None:
            LOGGER.warning(
                "Artículo '%s' no registrado en CORPUS_REGISTRY; se omitirá.",
                pdf_path.name,
            )
            continue
        sources.append(
            SourceDocument(
                doc_id=meta["doc_id"],
                title=meta["title"],
                authors=tuple(meta["authors"]),
                year=meta["year"],
                kind=meta["kind"],
                file_path=str(pdf_path),
                chapter_hint="",
            )
        )
    return sources


def _page_lines_with_fonts(page: fitz.Page) -> list[tuple[str, float, bool]]:
    """Return [(line_text, max_font_size, is_bold), ...] for one page.

    PyMuPDF's `lines` entries can contain embedded newlines (when the same
    typographic line wraps onto two visual lines). We split on `\n` so that
    repeated-line detection can match each visual line individually.
    """
    text_dict = page.get_text("dict")
    lines: list[tuple[str, float, bool]] = []
    for block in text_dict.get("blocks", []):
        if block.get("type") != 0:
            continue
        for line in block.get("lines", []):
            spans = line.get("spans", [])
            text = "".join(s.get("text", "") for s in spans).strip()
            if not text:
                continue
            max_size = max((s.get("size", 0) for s in spans), default=0.0)
            is_bold = any(bool(s.get("flags", 0) & 16) for s in spans)
            for sub in text.split("\n"):
                sub = sub.strip()
                if sub:
                    lines.append((sub, max_size, is_bold))
    return lines


def extract_pages(source: SourceDocument) -> list[_PageText]:
    """Extract cleaned pages from a PDF, attaching chapter/section info."""
    path = Path(source.file_path)
    if not path.exists():
        raise FileNotFoundError(f"PDF no encontrado: {path}")
    doc = fitz.open(path)
    try:
        # Step 1: pull raw text + per-line font info for every page.
        raw_pages: list[_PageText] = []
        line_info: list[list[tuple[str, float, bool]]] = []
        for pdf_idx in range(len(doc)):
            raw = doc[pdf_idx].get_text("text")
            text = clean_text(raw)
            raw_pages.append(
                _PageText(
                    page_number=_page_pdf_index_to_printed(pdf_idx),
                    text=text,
                    chapter="",
                    section="",
                )
            )
            line_info.append(_page_lines_with_fonts(doc[pdf_idx]))
    finally:
        doc.close()

    # Step 2: detect repeated running heads / footers from the cleaned text.
    noise = _detect_repeated_lines(raw_pages)
    LOGGER.info(
        "'%s' — %d páginas, %d líneas repetidas detectadas",
        path.name, len(raw_pages), len(noise),
    )

    # Step 3: build per-page filtered line list (no headers / footers).
    cleaned_lines: list[list[tuple[str, float, bool]]] = []
    for page_text, page_lines in zip(raw_pages, line_info):
        kept = []
        for ln in page_lines:
            text, size, _ = ln
            if text in noise:
                continue
            # Filter out printed page numbers (small numeric tokens that are
            # *only* digits or hyphenated digits, e.g. "3" or "1-3"). Section
            # numbers like "1.1" or "10.3" must remain visible.
            if (
                len(text) <= 4
                and text.replace("-", "").isdigit()
                and size < 14.0
            ):
                continue
            kept.append(ln)
        cleaned_lines.append(kept)
        # Re-render page text without the noise lines.
        page_text.text = "\n".join(ln[0] for ln in kept).strip()

    # Step 4: walk the cleaned lines to detect chapter / section headings.
    pages: list[_PageText] = []
    current_chapter = ""
    current_section = ""
    pending_chapter_number: str | None = None
    pending_section_number: str | None = None
    for page, lines in zip(raw_pages, cleaned_lines):
        consumed_chapter_number = False
        consumed_section_number = False
        for idx, (line_text, size, is_bold) in enumerate(lines):
            # If the previous line was a bare chapter number, the current line
            # is probably the chapter title — combine them.
            if pending_chapter_number and is_bold and 12.0 <= size <= 30.0:
                combined = f"{pending_chapter_number} {line_text}"
                current_chapter = combined
                current_section = ""
                pending_chapter_number = None
                consumed_chapter_number = True
                break
            # If the previous line was a bare section number, combine.
            if pending_section_number and is_bold and 11.5 <= size <= 20.0:
                combined = f"{pending_section_number} {line_text}"
                current_section = combined
                pending_section_number = None
                consumed_section_number = True
                break
            heading = _classify_heading(line_text, size, is_bold, lines)
            if heading is None:
                continue
            kind, label = heading
            if kind == "section":
                current_section = label
                break
            elif kind == "chapter":
                current_chapter = label
                current_section = ""
                break
            elif kind == "chapter_number":
                pending_chapter_number = label
                continue
            elif kind == "section_number":
                pending_section_number = label
                continue
        # Reset any pending number that was not consumed in this page.
        if not consumed_chapter_number:
            pending_chapter_number = None
        if not consumed_section_number:
            pending_section_number = None
        page.chapter = current_chapter
        page.section = current_section
        pages.append(page)

    # Drop empty pages (e.g. blank pages after a chapter title).
    return [p for p in pages if len(p.text) >= 30]


def _split_text(text: str, chunk_size: int, overlap: int) -> list[tuple[str, int, int]]:
    """Split a string into character windows. Returns (text, start, end) tuples
    where start/end are character offsets relative to the input."""
    if not text:
        return []
    if len(text) <= chunk_size:
        return [(text, 0, len(text))]

    pieces: list[tuple[str, int, int]] = []
    start = 0
    while start < len(text):
        proposed_end = min(start + chunk_size, len(text))
        end = proposed_end
        if proposed_end < len(text):
            boundary = text.rfind(" ", start + int(chunk_size * 0.65), proposed_end)
            if boundary > start:
                end = boundary
        piece = text[start:end].strip()
        if piece:
            pieces.append((piece, start, end))
        if end >= len(text):
            break
        next_start = max(0, end - overlap)
        boundary = text.find(" ", next_start, end)
        start = boundary + 1 if boundary != -1 else next_start
        if start >= end:
            start = end
    return pieces


def _slugify(text: str, max_length: int = 30) -> str:
    """Compact, deterministic slug from arbitrary text."""
    cleaned = re.sub(r"[^A-Za-z0-9]+", "-", text.lower()).strip("-")
    if not cleaned:
        return "chunk"
    return cleaned[:max_length]


def chunk_source(
    source: SourceDocument,
    pages: list[_PageText],
    chunk_size: int,
    chunk_overlap: int,
    min_chars: int,
) -> Iterator[Chunk]:
    """Yield chunks from a single document. Each chunk is anchored to the page
    on which it begins (page_end is computed by walking forward while the chunk
    spans text from later pages)."""
    counter = 0
    for page in pages:
        pieces = _split_text(page.text, chunk_size, chunk_overlap)
        for piece_text, _, _ in pieces:
            if len(piece_text) < min_chars:
                continue
            chunk_id = "{doc}:p{page}:c{idx:04d}-{slug}".format(
                doc=source.doc_id,
                page=page.page_number,
                idx=counter,
                slug=_slugify(page.section or page.chapter or "chunk"),
            )
            counter += 1
            yield Chunk(
                chunk_id=chunk_id,
                doc_id=source.doc_id,
                title=source.title,
                authors=source.authors,
                year=source.year,
                kind=source.kind,
                chapter=page.chapter,
                section=page.section,
                page_start=page.page_number,
                page_end=page.page_number,
                text=piece_text,
                chunk_index=counter,
            )


def build_corpus(
    sources: Iterable[SourceDocument],
    chunk_size: int,
    chunk_overlap: int,
    min_chars: int,
) -> tuple[list[Chunk], dict]:
    """Process all sources and return (chunks, stats)."""
    all_chunks: list[Chunk] = []
    per_source: dict[str, int] = {}
    failed: list[str] = []
    for source in sources:
        try:
            pages = extract_pages(source)
            count = 0
            for chunk in chunk_source(source, pages, chunk_size, chunk_overlap, min_chars):
                all_chunks.append(chunk)
                count += 1
            per_source[source.doc_id] = count
        except Exception as exc:
            LOGGER.exception("Fallo al procesar '%s': %s", source.file_path, exc)
            failed.append(source.file_path)
    stats = {
        "documents": len(per_source),
        "chunks": len(all_chunks),
        "per_source": per_source,
        "failed": failed,
    }
    LOGGER.info(
        "Corpus construido: %d chunks de %d documentos", len(all_chunks), len(per_source)
    )
    return all_chunks, stats


def chunk_fingerprint(chunk: Chunk) -> str:
    """Deterministic id used to deduplicate chunks across rebuilds."""
    return hashlib.sha1(
        f"{chunk.doc_id}|{chunk.page_start}|{chunk.chunk_index}|{chunk.text}".encode("utf-8")
    ).hexdigest()
