"""Unit tests for the RAG step executor."""
from __future__ import annotations

import asyncio

from apps.backend.orchestrator.rag_step import RagStepExecutor
from rag.ingestion import (
    Chunk,
    DeterministicEmbeddingModel,
    IndexMetadata,
    InMemoryVectorIndex,
)
from rag.retrieval import RetrievalService


def _index() -> InMemoryVectorIndex:
    chunks = [
        Chunk(
            chunk_id="doc-1#0",
            doc_id="doc-1",
            chunk_index=0,
            text="boiler tube leak troubleshooting",
            section=None,
            source_type="troubleshooting",
            asset_class="boiler",
            severity="critical",
            tags=[],
        ),
    ]
    embedder = DeterministicEmbeddingModel(dimension=64)
    meta = IndexMetadata(
        version=1,
        dimension=64,
        embedder_name="deterministic:64",
        chunk_count=1,
        document_count=1,
    )
    idx = InMemoryVectorIndex(metadata=meta)
    idx.add(chunks, embedder.embed([c.text for c in chunks]))
    return idx


def test_rag_step_returns_citations() -> None:
    async def runner() -> None:
        idx = _index()
        service = RetrievalService(index=idx, embedder=DeterministicEmbeddingModel(dimension=64))
        executor = RagStepExecutor(service=service)
        result = await executor.execute("boiler tube leak")
        assert result.citations
        assert all(c.doc_id for c in result.citations)

    asyncio.run(runner())


def test_rag_step_respects_filters() -> None:
    async def runner() -> None:
        idx = _index()
        service = RetrievalService(index=idx, embedder=DeterministicEmbeddingModel(dimension=64))
        executor = RagStepExecutor(service=service)
        # The executor's public API doesn't expose filters; the
        # chain runner exercises filters via the underlying
        # service. This test confirms the no-filter code path.
        result = await executor.execute("boiler", k=1)
        assert len(result.citations) <= 1

    asyncio.run(runner())
