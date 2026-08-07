"""CLI entry point for the ingestion pipeline.

Run with::

    uv run python -m rag.ingestion --corpus rag/documents --index var/index/v1.pkl

The default embedder is the deterministic one so the CLI works
in a clean environment without the ``sentence-transformers``
package. Pass ``--embedder sentence-transformers`` to use the
real model.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .embedder import (
    DEFAULT_DIMENSION,
    DeterministicEmbeddingModel,
    SentenceTransformerEmbeddingModel,
)
from .errors import IngestionError
from .pipeline import run_ingestion


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="rag.ingestion",
        description="Build the RAG vector index from a markdown corpus.",
    )
    parser.add_argument(
        "--corpus",
        type=Path,
        required=True,
        help="Path to the corpus directory containing *.md files.",
    )
    parser.add_argument(
        "--index",
        type=Path,
        required=True,
        help="Output path for the pickled index (e.g. var/index/v1.pkl).",
    )
    parser.add_argument(
        "--embedder",
        choices=("deterministic", "sentence-transformers"),
        default="deterministic",
        help="Embedding model to use. Default is deterministic.",
    )
    parser.add_argument(
        "--chunk-size",
        type=int,
        default=800,
        help="Chunk size in characters (default 800).",
    )
    parser.add_argument(
        "--overlap",
        type=int,
        default=100,
        help="Chunk overlap in characters (default 100).",
    )
    parser.add_argument(
        "--model-name",
        default="all-MiniLM-L6-v2",
        help="SentenceTransformer model name (only used when --embedder=sentence-transformers).",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.embedder == "sentence-transformers":
        embedder: DeterministicEmbeddingModel | SentenceTransformerEmbeddingModel = (
            SentenceTransformerEmbeddingModel(
                model_name=args.model_name,
                dimension=DEFAULT_DIMENSION,
            )
        )
    else:
        embedder = DeterministicEmbeddingModel(dimension=DEFAULT_DIMENSION)

    try:
        report = run_ingestion(
            corpus_dir=args.corpus,
            index_path=args.index,
            embedder=embedder,
            chunk_size=args.chunk_size,
            overlap=args.overlap,
        )
    except IngestionError as exc:
        print(f"ingestion failed: {exc}", file=sys.stderr)
        return 1

    print(  # noqa: T201 — CLI output is the point
        f"documents={report.documents} "
        f"chunks={report.chunks} "
        f"duration={report.duration_s:.2f}s "
        f"embedder={report.embedder_name} "
        f"index={report.index_path}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
