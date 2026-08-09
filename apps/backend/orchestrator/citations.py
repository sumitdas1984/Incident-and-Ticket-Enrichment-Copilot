"""Adapter between ``rag.retrieval.Citation`` and ``core.domain.Citation``.

The two classes are *similar* but not identical — the
project-wide domain model (``core.domain.Citation``) is what
the response envelope carries on the wire; the retrieval
service returns ``rag.retrieval.Citation`` with additional
fields (chunk_id, title, source_type, asset_class, severity)
that the domain model does not carry.

This adapter is the single most likely silent bug source if
skipped: both classes import cleanly, but the field mapping
is wrong. The :func:`to_domain_citation` adapter is the only
adapter that crosses the boundary, and it is unit-tested for
the round-trip.
"""
from __future__ import annotations

from core.domain import Citation as DomainCitation
from rag.retrieval import Citation as RagCitation


def to_domain_citation(rag_citation: RagCitation) -> DomainCitation:
    """Map a ``rag.retrieval.Citation`` to a ``core.domain.Citation``.

    Fields carried over: ``doc_id``, ``section``, ``score``,
    ``excerpt``. The retrieval-side ``chunk_id``, ``title``,
    ``source_type``, ``asset_class``, ``severity`` are
    *available* for the trace but not propagated here — the
    domain model is the response-side projection; details
    are surfaced in the trace instead.

    Fields carried over:
    * ``doc_id``
    * ``section``
    * ``score``
    * ``excerpt`` (truncated to the first 200 chars by the
      retrieval service; the domain model accepts the same
      length)

    Fields dropped:
    * ``chunk_id`` — the retrieval-side ``chunk_id`` is the
      citeable unit on the RAG side; the trace carries the
      tool's output verbatim. The domain model projects the
      citation at the document level.
    * ``title`` — the retrieval service does not propagate the
      document title today (it uses ``doc_id`` as a fallback).
    * ``source_type`` / ``asset_class`` / ``severity`` — the
      document-level metadata; not part of the response envelope.
    """
    return DomainCitation(
        doc_id=rag_citation.doc_id,
        section=rag_citation.section,
        page=None,  # retrieval service does not carry page info
        score=rag_citation.score,
        excerpt=rag_citation.excerpt,
    )


__all__ = ["to_domain_citation"]
