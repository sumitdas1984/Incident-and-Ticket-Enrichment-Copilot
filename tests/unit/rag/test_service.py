"""Unit tests for the retrieval service — happy path."""
from __future__ import annotations

import re

import pytest

from rag.ingestion import (
    Chunk,
    DeterministicEmbeddingModel,
    IndexMetadata,
    InMemoryVectorIndex,
)
from rag.retrieval import RetrievalFilters, RetrievalService


def _chunk(
    cid: str,
    text: str,
    *,
    source_type: str = "troubleshooting",
    asset_class: str | None = None,
    severity: str | None = None,
    section: str | None = None,
) -> Chunk:
    doc_id, _, idx = cid.partition("#")
    return Chunk(
        chunk_id=cid,
        doc_id=doc_id,
        chunk_index=int(idx),
        text=text,
        section=section,
        source_type=source_type,
        asset_class=asset_class,
        severity=severity,
        tags=[],
    )


def _build_index(chunks: list[Chunk]) -> tuple[InMemoryVectorIndex, DeterministicEmbeddingModel]:
    embedder = DeterministicEmbeddingModel(dimension=64)
    meta = IndexMetadata(
        version=1,
        dimension=64,
        embedder_name="deterministic:64",
        chunk_count=len(chunks),
        document_count=len({c.doc_id for c in chunks}),
    )
    idx = InMemoryVectorIndex(metadata=meta)
    idx.add(chunks, embedder.embed([c.text for c in chunks]))
    return idx, embedder


def test_retrieve_returns_top_k_citations_sorted_descending() -> None:
    chunks = [
        _chunk("a#0", "alpha content"),
        _chunk("b#0", "beta content"),
        _chunk("c#0", "gamma content"),
    ]
    idx, embedder = _build_index(chunks)
    service = RetrievalService(index=idx, embedder=embedder)

    result = service.retrieve("alpha content", k=3)

    assert len(result.citations) == 3
    scores = [c.score for c in result.citations]
    assert scores == sorted(scores, reverse=True)


def test_retrieve_returns_fewer_than_k_when_index_is_small() -> None:
    chunks = [_chunk("a#0", "alpha")]
    idx, embedder = _build_index(chunks)
    service = RetrievalService(index=idx, embedder=embedder)

    result = service.retrieve("alpha", k=5)

    assert len(result.citations) == 1


def test_citations_carry_doc_and_chunk_identifiers() -> None:
    chunks = [
        _chunk("boiler#0", "leak in the boiler tube"),
        _chunk("pump#0", "pump cavitation event"),
    ]
    idx, embedder = _build_index(chunks)
    service = RetrievalService(index=idx, embedder=embedder)

    result = service.retrieve("boiler tube leak", k=2)

    assert all(c.chunk_id for c in result.citations)
    assert all(c.doc_id for c in result.citations)


def test_citation_excerpt_is_first_chars_of_chunk_text() -> None:
    text = "lorem ipsum " * 50  # long enough to trip truncation
    chunks = [_chunk("a#0", text)]
    idx, embedder = _build_index(chunks)
    service = RetrievalService(index=idx, embedder=embedder)

    [citation] = service.retrieve("lorem ipsum", k=1).citations
    assert citation.excerpt == text[:200].rstrip()


def test_filters_narrow_candidates_by_source_type() -> None:
    chunks = [
        _chunk("a#0", "same text", source_type="troubleshooting"),
        _chunk("b#0", "same text", source_type="procedure"),
    ]
    idx, embedder = _build_index(chunks)
    service = RetrievalService(index=idx, embedder=embedder)

    result = service.retrieve(
        "same text",
        k=5,
        filters=RetrievalFilters(source_type="procedure"),
    )

    assert len(result.citations) == 1
    assert result.citations[0].source_type == "procedure"


def test_filters_narrow_candidates_by_asset_class() -> None:
    chunks = [
        _chunk("a#0", "shared", asset_class="boiler"),
        _chunk("b#0", "shared", asset_class="compressor"),
    ]
    idx, embedder = _build_index(chunks)
    service = RetrievalService(index=idx, embedder=embedder)

    result = service.retrieve(
        "shared",
        k=5,
        filters=RetrievalFilters(asset_class="boiler"),
    )

    assert len(result.citations) == 1
    assert result.citations[0].asset_class == "boiler"


def test_filters_narrow_candidates_by_severity() -> None:
    chunks = [
        _chunk("a#0", "shared", severity="critical"),
        _chunk("b#0", "shared", severity="low"),
    ]
    idx, embedder = _build_index(chunks)
    service = RetrievalService(index=idx, embedder=embedder)

    result = service.retrieve(
        "shared",
        k=5,
        filters=RetrievalFilters(severity="critical"),
    )

    assert len(result.citations) == 1
    assert result.citations[0].severity == "critical"


def test_filters_combine_with_and() -> None:
    chunks = [
        _chunk(
            "a#0",
            "shared",
            source_type="troubleshooting",
            asset_class="boiler",
            severity="critical",
        ),
        _chunk(
            "b#0",
            "shared",
            source_type="procedure",
            asset_class="boiler",
            severity="critical",
        ),
    ]
    idx, embedder = _build_index(chunks)
    service = RetrievalService(index=idx, embedder=embedder)

    result = service.retrieve(
        "shared",
        k=5,
        filters=RetrievalFilters(source_type="troubleshooting", severity="critical"),
    )

    assert len(result.citations) == 1
    assert result.citations[0].doc_id == "a"


def test_service_rejects_inverted_thresholds() -> None:
    chunks = [_chunk("a#0", "alpha")]
    idx, embedder = _build_index(chunks)
    with pytest.raises(ValueError, match="medium_threshold"):
        RetrievalService(
            index=idx,
            embedder=embedder,
            confidence_threshold=0.50,
            medium_threshold=0.30,
        )


def test_service_rejects_out_of_range_threshold() -> None:
    chunks = [_chunk("a#0", "alpha")]
    idx, embedder = _build_index(chunks)
    with pytest.raises(ValueError, match="confidence_threshold"):
        RetrievalService(index=idx, embedder=embedder, confidence_threshold=1.5)


def test_retrieve_rejects_empty_query() -> None:
    chunks = [_chunk("a#0", "alpha")]
    idx, embedder = _build_index(chunks)
    service = RetrievalService(index=idx, embedder=embedder)
    with pytest.raises(ValueError, match="non-empty"):
        service.retrieve("   ")


def test_retrieve_deterministic_for_same_query() -> None:
    chunks = [
        _chunk("a#0", "alpha"),
        _chunk("b#0", "beta"),
        _chunk("c#0", "gamma"),
    ]
    idx, embedder = _build_index(chunks)
    service = RetrievalService(index=idx, embedder=embedder)

    a = service.retrieve("alpha", k=3)
    b = service.retrieve("alpha", k=3)

    assert [c.chunk_id for c in a.citations] == [c.chunk_id for c in b.citations]
    assert [c.score for c in a.citations] == [c.score for c in b.citations]


def test_custom_blocklist_can_be_disabled() -> None:
    # An empty blocklist means nothing is dropped; the test
    # asserts that the constructor accepts a tuple as a valid
    # sentinel for "no blocklist" and the retrieve path
    # completes without dropping.
    chunks = [_chunk("a#0", "alpha"), _chunk("b#0", "beta")]
    idx, embedder = _build_index(chunks)
    service = RetrievalService(
        index=idx,
        embedder=embedder,
        injection_blocklist=(),
    )
    result = service.retrieve("alpha", k=2)
    assert result.dropped_count == 0
    assert len(result.citations) == 2


def test_blocklist_accepts_pattern_object() -> None:
    # The constructor type is ``Sequence[re.Pattern[str]]``;
    # a list of regex objects should be accepted.
    chunks = [_chunk("a#0", "alpha")]
    idx, embedder = _build_index(chunks)
    blocklist = [re.compile(r"ignore", re.IGNORECASE)]
    service = RetrievalService(
        index=idx,
        embedder=embedder,
        injection_blocklist=blocklist,
    )
    result = service.retrieve("alpha", k=1)
    assert result.dropped_count == 0
