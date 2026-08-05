"""Tests for the corpus extraction / chunking pipeline."""
from __future__ import annotations

from pathlib import Path

import pytest

from ir_rag.corpus import (
    _PageText,
    _detect_repeated_lines,
    _split_text,
    build_corpus,
    chunk_source,
    clean_text,
    discover_sources,
)


def test_clean_text_collapses_whitespace():
    assert clean_text("a  b\n\n\nc") == "a b\n\nc"
    # PDF hyphenation should be repaired.
    assert "computing" in clean_text("com-\nputing")
    assert clean_text("") == ""


def test_split_text_short_input():
    pieces = _split_text("hello world", chunk_size=100, overlap=0)
    assert pieces == [("hello world", 0, 11)]


def test_split_text_produces_overlap():
    text = "lorem ipsum dolor sit amet consectetur adipiscing elit " * 10
    pieces = _split_text(text, chunk_size=80, overlap=20)
    assert len(pieces) >= 2
    # Adjacent chunks should share some content because of overlap.
    assert pieces[0][0][-10:] in pieces[1][0] or pieces[1][0][:10] in pieces[0][0]


def test_detect_repeated_lines_ignores_short_tokens():
    pages = [
        _PageText(page_number=i + 1, text="A\nlong\nheader")
        for i in range(10)
    ] + [_PageText(page_number=11, text="only body")]
    noise = _detect_repeated_lines(pages)
    assert "header" in noise  # appears in 10 pages -> threshold ≈ 5
    assert "A" not in noise   # too short
    assert "only body" not in noise


def test_chunk_source_attaches_metadata():
    from ir_rag.models import SourceDocument

    source = SourceDocument(
        doc_id="doc1",
        title="Test Book",
        authors=("Author A",),
        year=2024,
        kind="book",
        file_path="ignored",
    )
    pages = [
        _PageText(page_number=5, text="alpha " * 200, chapter="1 Intro", section="1.1 First"),
    ]
    chunks = list(chunk_source(source, pages, chunk_size=200, chunk_overlap=20, min_chars=10))
    assert chunks
    chunk = chunks[0]
    assert chunk.doc_id == "doc1"
    assert chunk.title == "Test Book"
    assert chunk.page_start == 5
    assert chunk.page_end == 5
    assert chunk.chapter == "1 Intro"
    assert chunk.section == "1.1 First"
    assert chunk.chunk_id.startswith("doc1:p5:")
    assert "alpha" in chunk.text


def test_build_corpus_smoke(tmp_path):
    """Indexing the real PDFs should produce non-empty chunks for each one."""
    project = Path(__file__).resolve().parents[1]
    sources = discover_sources(project / "corpus", project / "corpus" / "articles")
    if not sources:
        pytest.skip("No corpus PDFs available")
    chunks, stats = build_corpus(sources, chunk_size=400, chunk_overlap=50, min_chars=50)
    assert chunks
    # At least one chunk per registered source.
    indexed_doc_ids = {c.doc_id for c in chunks}
    for s in sources:
        assert s.doc_id in indexed_doc_ids, f"No chunks for {s.doc_id}"
    assert stats["failed"] == []
