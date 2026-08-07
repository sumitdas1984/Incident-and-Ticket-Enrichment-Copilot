"""Retrieval service — the orchestrator-facing facade.

The retrieval service combines every Feature 4.2 moving part —

* the persisted :class:`InMemoryVectorIndex`
* the embedding model the index was built with
* the cosine ranking layer
* the prompt-injection blocklist
* the confidence-band classifier

— behind a single :meth:`RetrievalService.retrieve` call. The
orchestrator (Story 5.1.3) talks to this class; the GUI renders
the returned :class:`RetrievalResult`.

Why a class, not a module of functions
--------------------------------------

The service carries state (the index, the embedder, the
calibration thresholds, the blocklist). Tests want to build a
service against a small in-memory index; the orchestrator wants
to build one against the persisted ``var/index/v1.pkl``. A
class is the natural shape.

Why the embedder is injected
----------------------------

The retrieval service must use the *same* embedding model that
built the index. A query vector from a different model is
meaningless on the existing index. The constructor accepts
the protocol so the production wiring (``SentenceTransformerEmbeddingModel``)
and the test wiring (``DeterministicEmbeddingModel``) are
indistinguishable to the service.
"""
from __future__ import annotations

import logging
import re
from collections.abc import Sequence

from rag.ingestion import EmbeddingModel, IndexedChunk, InMemoryVectorIndex

from .citations import (
    CITATION_EXCERPT_CHARS,
    CONFIDENCE_HIGH,
    CONFIDENCE_LOW,
    CONFIDENCE_MEDIUM,
    CONFIDENCE_NONE,
    Citation,
    RetrievalFilters,
    RetrievalResult,
)
from .injection import DEFAULT_INJECTION_PATTERNS, filter_injections
from .ranking import top_k

_logger = logging.getLogger(__name__)


def _classify_confidence(
    top_score: float,
    confidence_threshold: float,
    medium_threshold: float,
) -> str:
    """Map a top score to a confidence band.

    The thresholds are stored on the service so the operator
    can re-calibrate without re-instantiating the bundle. The
    ordering is enforced: ``confidence_threshold`` is the
    "low/no-confidence" cutoff and ``medium_threshold`` is the
    "high-confidence" cutoff. The constructor rejects
    ``medium_threshold < confidence_threshold``.
    """
    if top_score >= medium_threshold:
        return CONFIDENCE_HIGH
    if top_score >= confidence_threshold:
        return CONFIDENCE_MEDIUM
    return CONFIDENCE_LOW


def _excerpt(text: str) -> str:
    """Trim the chunk text to ``CITATION_EXCERPT_CHARS`` characters.

    The trim is on a character boundary. The excerpt is the
    *first* window of the chunk — the orchestrator renders the
    excerpt verbatim, so we want the leading characters which
    are usually the section header.
    """
    if len(text) <= CITATION_EXCERPT_CHARS:
        return text
    return text[:CITATION_EXCERPT_CHARS].rstrip()


def _matches_filters(chunk: IndexedChunk, filters: RetrievalFilters) -> bool:
    if filters.source_type is not None and chunk.chunk.source_type != filters.source_type:
        return False
    if filters.asset_class is not None and chunk.chunk.asset_class != filters.asset_class:
        return False
    if filters.severity is not None and chunk.chunk.severity != filters.severity:
        return False
    return True


class RetrievalService:
    """Consume the persisted index and answer queries with citations.

    The service is a thin orchestration layer over the rank /
    filter / injection / re-rank stages. It is the only public
    surface the orchestrator talks to.

    Parameters
    ----------
    index:
        The vector index to query. Typically loaded from
        ``var/index/v1.pkl`` via
        :meth:`InMemoryVectorIndex.load`.
    embedder:
        The embedding model. Must output vectors compatible
        with the index's ``dimension`` (the service does not
        re-validate; an early call will surface a shape error
        from the rank layer).
    confidence_threshold:
        Below this top score the result is ``"low"`` confidence.
        Defaults to ``0.30``.
    medium_threshold:
        Above this top score the result is ``"high"`` confidence.
        Defaults to ``0.50``.
    injection_blocklist:
        Tuple of compiled regex patterns. Defaults to
        :data:`DEFAULT_INJECTION_PATTERNS`. Pass an empty tuple
        to disable the blocklist entirely (not recommended in
        production; useful for tests that want to inspect the
        pre-filter score distribution).
    """

    def __init__(
        self,
        *,
        index: InMemoryVectorIndex,
        embedder: EmbeddingModel,
        confidence_threshold: float = 0.30,
        medium_threshold: float = 0.50,
        injection_blocklist: Sequence[re.Pattern[str]] | None = None,
    ) -> None:
        if confidence_threshold < 0.0 or confidence_threshold > 1.0:
            raise ValueError(
                f"confidence_threshold must be in [0.0, 1.0], "
                f"got {confidence_threshold}"
            )
        if medium_threshold < 0.0 or medium_threshold > 1.0:
            raise ValueError(
                f"medium_threshold must be in [0.0, 1.0], "
                f"got {medium_threshold}"
            )
        if medium_threshold < confidence_threshold:
            raise ValueError(
                f"medium_threshold ({medium_threshold}) must be "
                f">= confidence_threshold ({confidence_threshold})"
            )
        self._index = index
        self._embedder = embedder
        self._confidence_threshold = confidence_threshold
        self._medium_threshold = medium_threshold
        self._injection_blocklist = (
            tuple(injection_blocklist)
            if injection_blocklist is not None
            else DEFAULT_INJECTION_PATTERNS
        )

    @property
    def confidence_threshold(self) -> float:
        return self._confidence_threshold

    @property
    def medium_threshold(self) -> float:
        return self._medium_threshold

    @property
    def index_size(self) -> int:
        return len(self._index)

    def retrieve(
        self,
        query: str,
        *,
        k: int = 5,
        filters: RetrievalFilters | None = None,
    ) -> RetrievalResult:
        """Return the top-``k`` citations for ``query``.

        Steps:

        1. Embed the query with the configured embedder.
        2. Filter the index by ``filters`` (if any).
        3. Drop injection-blocklisted chunks; log each drop.
        4. Rank by cosine similarity.
        5. Take the top-``k``.
        6. Compute the confidence band from the top score.

        Returns
        -------
        RetrievalResult
            Always carries a confidence band. Empty index and
            below-threshold retrievals are surfaced as
            ``"none"`` / ``"low"`` rather than raising.
        """
        if not query.strip():
            raise ValueError("query must be a non-empty string")

        query_vec = self._embedder.embed([query])[0]

        # Filter first so the blocklist and the ranker see the
        # narrowed candidate set. Cheaper than ranking then
        # filtering.
        candidates: list[IndexedChunk] = list(self._index.entries)
        if filters is not None:
            candidates = [c for c in candidates if _matches_filters(c, filters)]

        survivors, drops = filter_injections(candidates, self._injection_blocklist)
        for drop in drops:
            _logger.info(
                "rag.injection_dropped",
                extra={
                    "chunk_id": drop.chunk_id,
                    "doc_id": drop.doc_id,
                    "matched_pattern": drop.matched_pattern,
                },
            )

        if not survivors:
            return RetrievalResult(
                citations=[],
                confidence=CONFIDENCE_NONE,
                top_score=0.0,
                threshold=self._confidence_threshold,
                dropped_count=len(drops),
            )

        ranked = top_k(query_vec, survivors, k)
        citations: list[Citation] = []
        for entry, score in ranked:
            chunk = entry.chunk
            citations.append(
                Citation(
                    doc_id=chunk.doc_id,
                    chunk_id=chunk.chunk_id,
                    title=_chunk_title(chunk),
                    section=chunk.section,
                    source_type=chunk.source_type,
                    asset_class=chunk.asset_class,
                    severity=chunk.severity,
                    excerpt=_excerpt(chunk.text),
                    score=score,
                )
            )

        top_score = citations[0].score
        confidence = _classify_confidence(
            top_score,
            self._confidence_threshold,
            self._medium_threshold,
        )
        return RetrievalResult(
            citations=citations,
            confidence=confidence,
            top_score=top_score,
            threshold=self._confidence_threshold,
            dropped_count=len(drops),
        )


def _chunk_title(chunk) -> str:
    """Best-effort title for a citation.

    The :class:`rag.ingestion.Chunk` does not carry a title
    field; the title is inherited from the parent document. The
    retrieval service does not have a doc-id → title lookup
    table today, so we fall back to the ``doc_id`` and document
    this as a follow-up. The LLM prompt can still render the
    citation meaningfully — the ``doc_id`` is the filename stem
    and the orchestrator's documentation tells the GUI to render
    the doc_id as the link target.
    """
    return chunk.doc_id


__all__ = ["RetrievalService"]
