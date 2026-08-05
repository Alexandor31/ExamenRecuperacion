#!/usr/bin/env python3
"""Build (or rebuild) the IR RAG index."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from ir_rag.config import Settings
from ir_rag.indexing import build_index


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Process the IR PDFs and build the Chroma vector index."
    )
    parser.add_argument(
        "--max-documents",
        type=int,
        default=None,
        help="Cap how many source PDFs to index (useful for smoke tests).",
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        default=True,
        help="Drop and recreate the collection before inserting (default).",
    )
    parser.add_argument(
        "--no-reset",
        dest="reset",
        action="store_false",
        help="Upsert into the existing collection instead of resetting it.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    settings = Settings.from_env()

    def progress(done: int, total: int) -> None:
        print(f"  embedding {done:>6d}/{total:<6d} chunks", flush=True)

    manifest = build_index(
        settings,
        max_documents=args.max_documents,
        progress=progress,
        reset=args.reset,
    )
    print(json.dumps(manifest["stats"], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
