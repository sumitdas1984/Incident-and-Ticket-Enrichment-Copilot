"""RAG retrieval service (Story 4.2).

The retrieval service consumes the persisted
:class:`rag.ingestion.InMemoryVectorIndex` produced by the
ingestion pipeline (Story 4.1) and returns ranked
:class:`Citation` objects for the user query.

Public surface:

* :class:`RetrievalService` — the orchestrator-facing facade.
* :class:`Citation` — one chunk's citation metadata.
* :class:`RetrievalResult` — the bundle returned by
  :meth:`RetrievalService.retrieve`.
* :class:`RetrievalFilters` — optional metadata filters.
* :data:`DEFAULT_INJECTION_PATTERNS` — the default
  prompt-injection blocklist.

The retrieval service is a library: it has no CLI entry point.
The orchestrator (Story 5.1.3) wires it into the MCP tool
surface in a follow-up PR.
"""
from __future__ import annotations

from .citations import (
    CITATION_EXCERPT_CHARS,
    CONFIDENCE_BANDS,
    CONFIDENCE_HIGH,
    CONFIDENCE_LOW,
    CONFIDENCE_MEDIUM,
    CONFIDENCE_NONE,
    Citation,
    RetrievalFilters,
    RetrievalResult,
)
from .injection import (
    DEFAULT_INJECTION_PATTERNS,
    InjectionDrop,
    filter_injections,
    find_injections,
)
from .ranking import cosine_similarity, rank_candidates, top_k
from .service import RetrievalService

__all__ = [
    # Citations / result
    "CITATION_EXCERPT_CHARS",
    "CONFIDENCE_BANDS",
    "CONFIDENCE_HIGH",
    "CONFIDENCE_LOW",
    "CONFIDENCE_MEDIUM",
    "CONFIDENCE_NONE",
    "Citation",
    "RetrievalFilters",
    "RetrievalResult",
    # Injection defence
    "DEFAULT_INJECTION_PATTERNS",
    "InjectionDrop",
    "filter_injections",
    "find_injections",
    # Ranking
    "cosine_similarity",
    "rank_candidates",
    "top_k",
    # Service
    "RetrievalService",
]
