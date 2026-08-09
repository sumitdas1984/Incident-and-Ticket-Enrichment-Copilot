"""Top-level ingestion pipeline: load → chunk → embed → persist.

The CLI entry in :mod:`__main__` calls :func:`run_ingestion`. The
function is also the right unit for tests — pass a synthetic
corpus directory, a target index path, and an embedder; assert
the resulting :class:`IngestionReport`.

Why a single function
---------------------

The pipeline is linear. Splitting it across multiple functions
would only add argument-bag plumbing. The four stages are
already independent modules; the orchestrator composes them.

Determinism
-----------

The pipeline is fully deterministic given a deterministic
embedder and a sorted corpus walk. Sorting by ``doc_id`` in
:func:`load_documents` keeps the chunk order identical across
rebuilds, which (with a deterministic embedder) makes the
persisted index byte-identical across rebuilds. We verify this
in :file:`tests/rag/test_pipeline.py`.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

from .chunker import chunk_document
from .embedder import (
    DEFAULT_DIMENSION,
    DeterministicEmbeddingModel,
    EmbeddingModel,
    SentenceTransformerEmbeddingModel,
)
from .index import INDEX_VERSION, IndexMetadata, InMemoryVectorIndex
from .loader import load_documents


@dataclass(frozen=True)
class IngestionReport:
    """Summary of one ingestion run. Written to stdout by the CLI."""

    documents: int
    chunks: int
    duration_s: float
    index_path: Path
    embedder_name: str


def run_ingestion(
    *,
    corpus_dir: Path,
    index_path: Path,
    embedder: EmbeddingModel | None = None,
    chunk_size: int = 800,
    overlap: int = 100,
) -> IngestionReport:
    """Load the corpus, chunk it, embed it, and persist the index.

    Parameters
    ----------
    corpus_dir:
        Directory containing ``*.md`` files with front-matter.
    index_path:
        Pickle destination. The parent directory is created
        if missing.
    embedder:
        Optional embedder. Defaults to a
        :class:`DeterministicEmbeddingModel` at
        :data:`DEFAULT_DIMENSION` so the CLI is runnable
        without the ``sentence-transformers`` dependency.
        Production use passes in a
        :class:`SentenceTransformerEmbeddingModel`.
    chunk_size:
        Chunk size in characters. 800 by default.
    overlap:
        Chunk overlap in characters. 100 by default.

    Returns
    -------
    IngestionReport
        Counters and the persisted index path. The CLI is
        responsible for printing this to stdout.
    """
    start = time.perf_counter()

    if embedder is None:
        embedder = DeterministicEmbeddingModel(dimension=DEFAULT_DIMENSION)

    docs = load_documents(corpus_dir)
    chunks: list = []
    for doc in docs:
        chunks.extend(chunk_document(doc, chunk_size=chunk_size, overlap=overlap))

    vectors = embedder.embed([c.text for c in chunks])

    embedder_name = _embedder_name(embedder)
    metadata = IndexMetadata(
        version=INDEX_VERSION,
        dimension=_embedder_dimension(embedder),
        embedder_name=embedder_name,
        chunk_count=len(chunks),
        document_count=len(docs),
    )
    index = InMemoryVectorIndex(metadata=metadata)
    index.add(chunks, vectors)
    index.save(index_path)

    duration = time.perf_counter() - start
    return IngestionReport(
        documents=len(docs),
        chunks=len(chunks),
        duration_s=duration,
        index_path=index_path,
        embedder_name=embedder_name,
    )


def _embedder_name(embedder: EmbeddingModel) -> str:
    if isinstance(embedder, SentenceTransformerEmbeddingModel):
        return f"sentence-transformers:{embedder.model_name}"
    if isinstance(embedder, DeterministicEmbeddingModel):
        return f"deterministic:{embedder.dimension}"
    return type(embedder).__name__


def _embedder_dimension(embedder: EmbeddingModel) -> int:
    if isinstance(embedder, DeterministicEmbeddingModel):
        return embedder.dimension
    if isinstance(embedder, SentenceTransformerEmbeddingModel):
        return DEFAULT_DIMENSION
    # Fall back to a default shape — the embedder is *expected*
    # to be one of the two concrete types we ship, but the
    # Protocol leaves room for a future implementation.
    return DEFAULT_DIMENSION


__all__ = [
    "IngestionReport",
    "run_ingestion",
]
