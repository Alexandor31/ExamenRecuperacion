#!/usr/bin/env python3
"""Download the open-access PDFs required for the IR RAG service.

The Baeza-Yates & Ribeiro-Neto book is copyrighted and is NOT downloaded
automatically. Place your own copy at corpus/baeza-yates-modern-ir.pdf and
register its bibliographic data in src/ir_rag/corpus.py if it differs.

The other items in this script are publicly available.
"""
from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CORPUS_DIR = PROJECT_ROOT / "corpus"
ARTICLES_DIR = CORPUS_DIR / "articles"

# (filename, public URL, kind)
PUBLIC_DOWNLOADS: list[tuple[str, str, str]] = [
    (
        "manning-introduction-ir.pdf",
        "https://nlp.stanford.edu/IR-book/pdf/irbookonlinereading.pdf",
        "book",
    ),
    (
        "jurafsky-slp3.pdf",
        "https://web.stanford.edu/~jurafsky/slp3/ed3book.pdf",
        "book",
    ),
    (
        "karpukhin-dpr-2020.pdf",
        "https://arxiv.org/pdf/2004.04906",
        "article",
    ),
    (
        "nogueira-monobert-2019.pdf",
        "https://arxiv.org/pdf/1901.04085",
        "article",
    ),
    (
        "robertson-bm25-perspective.pdf",
        "https://www.staff.city.ac.uk/~sbrp622/papers/foundations_bm25_review.pdf",
        "article",
    ),
]


def main() -> int:
    try:
        import urllib.request
    except ImportError:  # pragma: no cover
        print("urllib.request is required", file=sys.stderr)
        return 1

    ARTICLES_DIR.mkdir(parents=True, exist_ok=True)
    print("Downloading open-access PDFs...")
    for filename, url, kind in PUBLIC_DOWNLOADS:
        target_dir = ARTICLES_DIR if kind == "article" else CORPUS_DIR
        target = target_dir / filename
        if target.exists() and target.stat().st_size > 0:
            print(f"  ✓ {filename} already present ({target.stat().st_size:,} bytes)")
            continue
        print(f"  ↓ {filename} <- {url}")
        try:
            urllib.request.urlretrieve(url, target)
            print(f"    saved {target.stat().st_size:,} bytes")
        except Exception as exc:
            print(f"    FAILED: {exc}", file=sys.stderr)

    print("\nReminder:")
    print("  Place your copy of Baeza-Yates & Ribeiro-Neto's")
    print("  'Modern Information Retrieval' at:")
    print(f"    {CORPUS_DIR / 'baeza-yates-modern-ir.pdf'}")
    print("  The bibliographic metadata is already registered in")
    print("  src/ir_rag/corpus.py. If your edition has different authors")
    print("  or year, edit that registry accordingly.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
