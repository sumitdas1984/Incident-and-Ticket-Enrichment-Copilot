"""RAG step executor — wraps ``RetrievalService.retrieve`` for the chain.

The chain runner calls :meth:`RagStepExecutor.execute` for every
``RAG_QUERY`` step. The executor:

1. Embeds the query via the configured embedder.
2. Ranks chunks by cosine similarity.
3. Drops injection-blocklisted chunks.
4. Returns the :class:`RetrievalResult` so the chain runner can
   record the citations, confidence, and dropped count.

The executor is intentionally thin — the heavy lifting is in
``rag.retrieval.RetrievalService``. The chain runner passes a
fresh :class:`RetrievalService` instance shared across requests.
"""
from __future__ import annotations

from rag.retrieval import RetrievalResult, RetrievalService


class RagStepExecutor:
    """Wrap :class:`RetrievalService` for chain-runner invocation."""

    def __init__(self, service: RetrievalService) -> None:
        self._service = service

    async def execute(self, query: str, *, k: int = 5) -> RetrievalResult:
        """Run the RAG query and return the result."""
        return self._service.retrieve(query, k=k)


__all__ = ["RagStepExecutor"]
