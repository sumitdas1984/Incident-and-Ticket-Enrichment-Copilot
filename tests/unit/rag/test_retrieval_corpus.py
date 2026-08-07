"""Retrieval tests against the committed corpus (load → chunk → embed → retrieve).

Loads the synthetic documents from ``rag/documents/`` into a
fresh in-memory index and runs a small set of hand-picked
queries against the deterministic embedder. These tests do
not depend on the persisted index artefact; they build the
index inline so the corpus's well-formedness is what the test
exercises, not the build pipeline.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from rag.ingestion import (
    Chunk,
    DeterministicEmbeddingModel,
    IndexMetadata,
    InMemoryVectorIndex,
    chunk_document,
    load_documents,
)
from rag.retrieval import RetrievalFilters, RetrievalService

CORPUS_DIR = Path("rag/documents")


def _build_index(corpus: Path) -> InMemoryVectorIndex:
    docs = load_documents(corpus)
    embedder = DeterministicEmbeddingModel(dimension=64)
    chunks: list[Chunk] = []
    for doc in docs:
        chunks.extend(chunk_document(doc))
    meta = IndexMetadata(
        version=1,
        dimension=64,
        embedder_name="deterministic:64",
        chunk_count=len(chunks),
        document_count=len(docs),
    )
    idx = InMemoryVectorIndex(metadata=meta)
    idx.add(chunks, embedder.embed([c.text for c in chunks]))
    return idx


@pytest.fixture
def corpus_index() -> InMemoryVectorIndex:
    if not CORPUS_DIR.exists():
        pytest.skip(f"Corpus directory not present: {CORPUS_DIR}")
    return _build_index(CORPUS_DIR)


@pytest.fixture
def corpus_service(corpus_index: InMemoryVectorIndex) -> RetrievalService:
    return RetrievalService(
        index=corpus_index,
        embedder=DeterministicEmbeddingModel(dimension=64),
    )


def test_corpus_loads_with_more_than_one_doc(corpus_index: InMemoryVectorIndex) -> None:
    assert corpus_index.metadata.document_count >= 2


def test_corpus_index_contains_more_than_one_chunk(corpus_index: InMemoryVectorIndex) -> None:
    assert len(corpus_index) > 1


def test_corpus_query_returns_a_citation(corpus_service: RetrievalService) -> None:
    result = corpus_service.retrieve("boiler tube leak", k=3)
    assert result.citations
    assert all(c.chunk_id for c in result.citations)


def test_corpus_query_returns_distinct_citations(corpus_service: RetrievalService) -> None:
    result = corpus_service.retrieve("boiler tube leak", k=5)
    ids = [c.chunk_id for c in result.citations]
    assert len(ids) == len(set(ids))


def test_corpus_query_for_injection_seed_is_dropped(corpus_service: RetrievalService) -> None:
    # The boiler-tube-leak troubleshooting doc contains an
    # injection seed. The default blocklist must drop it.
    result = corpus_service.retrieve("boiler tube leak", k=10)
    assert result.dropped_count >= 1


def test_corpus_filter_narrows_to_source_type(corpus_service: RetrievalService) -> None:
    result = corpus_service.retrieve(
        "boiler",
        k=10,
        filters=RetrievalFilters(source_type="procedure"),
    )
    assert all(c.source_type == "procedure" for c in result.citations)


def test_corpus_filter_narrows_to_asset_class(corpus_service: RetrievalService) -> None:
    result = corpus_service.retrieve(
        "common",
        k=10,
        filters=RetrievalFilters(asset_class="boiler"),
    )
    assert all(c.asset_class == "boiler" for c in result.citations)


def test_corpus_query_returns_sized_top_k(corpus_service: RetrievalService) -> None:
    result = corpus_service.retrieve("boiler", k=3)
    assert len(result.citations) <= 3
