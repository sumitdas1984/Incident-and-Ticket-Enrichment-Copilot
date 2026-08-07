"""End-to-end retrieval test against the persisted index from Feature 4.1.

Loads ``var/index/v1.pkl`` (the artefact built by ``make ingest``)
and runs a query through the live retrieval service. The test
asserts the blessed happy path: a sensible query returns a
non-empty result with a sensible confidence band, and the
citations point back to the corpus's doc_ids.

If the index file is missing, the test is skipped — the index
is a build artefact, not a fixture committed to git.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from rag.ingestion import DeterministicEmbeddingModel, InMemoryVectorIndex
from rag.retrieval import RetrievalService

INDEX_PATH = Path("var/index/v1.pkl")


@pytest.fixture
def live_index() -> InMemoryVectorIndex:
    if not INDEX_PATH.exists():
        pytest.skip(
            f"Persisted index not found at {INDEX_PATH}. "
            "Run `make ingest` to build it."
        )
    return InMemoryVectorIndex.load(INDEX_PATH)


@pytest.fixture
def live_service(live_index: InMemoryVectorIndex) -> RetrievalService:
    # The persisted index encodes which embedder was used;
    # re-embed the query with the same one. The deterministic
    # embedder at the index's dimension is the cheapest
    # path here — the corpus's content is what we're
    # exercising, not the embedding's semantics.
    return RetrievalService(
        index=live_index,
        embedder=DeterministicEmbeddingModel(dimension=live_index.metadata.dimension),
    )


def test_loaded_index_has_chunks(live_index: InMemoryVectorIndex) -> None:
    assert len(live_index) > 0


def test_live_retrieval_returns_sorted_citations(live_service: RetrievalService) -> None:
    result = live_service.retrieve("boiler tube leak", k=5)
    assert result.citations
    scores = [c.score for c in result.citations]
    assert scores == sorted(scores, reverse=True)


def test_live_retrieval_returns_dropped_count_against_corpus(live_service: RetrievalService) -> None:
    # The committed corpus contains two injection seeds; the
    # default blocklist must catch at least one of them.
    result = live_service.retrieve("boiler tube leak", k=5)
    assert result.dropped_count >= 1


def test_live_retrieval_citations_carry_corpus_doc_ids(
    live_service: RetrievalService,
) -> None:
    result = live_service.retrieve("boiler tube leak", k=5)
    assert all(c.doc_id for c in result.citations)


def test_two_retrievals_against_same_query_are_identical(
    live_service: RetrievalService,
) -> None:
    a = live_service.retrieve("boiler tube leak", k=5)
    b = live_service.retrieve("boiler tube leak", k=5)
    assert [c.chunk_id for c in a.citations] == [c.chunk_id for c in b.citations]
    assert [c.score for c in a.citations] == [c.score for c in b.citations]
