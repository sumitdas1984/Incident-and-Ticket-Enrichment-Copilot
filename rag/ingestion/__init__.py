"""RAG ingestion pipeline — load, chunk, embed, persist.

Story 4.1.2 ships the four-stage pipeline. The CLI entry is
``python -m rag.ingestion``; the Makefile target ``make ingest``
wraps it.

Public surface:

* :func:`run_ingestion` — the orchestrator used by tests and the CLI.
* :class:`IngestionReport` — the run summary.
* :class:`InMemoryVectorIndex` — the default index, reloadable.
* Re-exports of the data classes so test code can import from
  ``rag.ingestion`` without reaching into private modules.
"""
from __future__ import annotations

from .chunker import Chunk, chunk_document
from .embedder import (
    DEFAULT_DIMENSION,
    DeterministicEmbeddingModel,
    EmbeddingModel,
    SentenceTransformerEmbeddingModel,
)
from .errors import IngestionError
from .index import (
    INDEX_VERSION,
    IndexedChunk,
    IndexMetadata,
    InMemoryVectorIndex,
    VectorIndex,
)
from .loader import (
    ALLOWED_SOURCE_TYPES,
    OPTIONAL_FIELDS,
    REQUIRED_FIELDS,
    LoadedDocument,
    load_documents,
)
from .pipeline import IngestionReport, run_ingestion

__all__ = [
    # Loader
    "ALLOWED_SOURCE_TYPES",
    "OPTIONAL_FIELDS",
    "REQUIRED_FIELDS",
    "LoadedDocument",
    "load_documents",
    # Chunker
    "Chunk",
    "chunk_document",
    # Embedder
    "DEFAULT_DIMENSION",
    "DeterministicEmbeddingModel",
    "EmbeddingModel",
    "SentenceTransformerEmbeddingModel",
    # Index
    "INDEX_VERSION",
    "IndexedChunk",
    "IndexMetadata",
    "InMemoryVectorIndex",
    "VectorIndex",
    # Pipeline
    "IngestionReport",
    "run_ingestion",
    # Errors
    "IngestionError",
]
