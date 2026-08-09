"""Unit tests for the retrieval citation dataclasses."""
from __future__ import annotations

import dataclasses

import pytest

from rag.retrieval.citations import (
    CITATION_EXCERPT_CHARS,
    Citation,
    RetrievalFilters,
    RetrievalResult,
)


def test_citation_is_frozen() -> None:
    c = Citation(
        doc_id="doc-1",
        chunk_id="doc-1#0",
        title="Doc 1",
        section=None,
        source_type="troubleshooting",
        asset_class=None,
        severity=None,
        excerpt="text",
        score=0.9,
    )
    with pytest.raises(dataclasses.FrozenInstanceError):
        c.score = 0.5  # type: ignore[misc]


def test_citation_carries_all_metadata() -> None:
    c = Citation(
        doc_id="doc-1",
        chunk_id="doc-1#3",
        title="Doc 1",
        section="Immediate actions",
        source_type="troubleshooting",
        asset_class="boiler",
        severity="critical",
        excerpt="text",
        score=0.42,
    )
    assert c.doc_id == "doc-1"
    assert c.chunk_id == "doc-1#3"
    assert c.section == "Immediate actions"
    assert c.source_type == "troubleshooting"
    assert c.asset_class == "boiler"
    assert c.severity == "critical"
    assert c.score == 0.42


def test_citation_excerpt_truncates_long_text() -> None:
    long_text = "x" * (CITATION_EXCERPT_CHARS + 50)
    c = Citation(
        doc_id="doc-1",
        chunk_id="doc-1#0",
        title="Doc 1",
        section=None,
        source_type="troubleshooting",
        asset_class=None,
        severity=None,
        excerpt=long_text[:CITATION_EXCERPT_CHARS],
        score=0.9,
    )
    assert len(c.excerpt) == CITATION_EXCERPT_CHARS


def test_citation_excerpt_keeps_short_text_intact() -> None:
    c = Citation(
        doc_id="doc-1",
        chunk_id="doc-1#0",
        title="Doc 1",
        section=None,
        source_type="troubleshooting",
        asset_class=None,
        severity=None,
        excerpt="short",
        score=0.9,
    )
    assert c.excerpt == "short"


def test_retrieval_result_is_frozen() -> None:
    r = RetrievalResult(
        citations=[],
        confidence="none",
        top_score=0.0,
        threshold=0.30,
        dropped_count=0,
    )
    with pytest.raises(dataclasses.FrozenInstanceError):
        r.confidence = "high"  # type: ignore[misc]


def test_retrieval_result_defaults_with_empty_citations() -> None:
    r = RetrievalResult(
        citations=[],
        confidence="none",
        top_score=0.0,
        threshold=0.30,
        dropped_count=0,
    )
    assert r.citations == []
    assert r.confidence == "none"
    assert r.top_score == 0.0
    assert r.threshold == 0.30
    assert r.dropped_count == 0


def test_retrieval_filters_all_optional() -> None:
    f = RetrievalFilters()
    assert f.source_type is None
    assert f.asset_class is None
    assert f.severity is None


def test_retrieval_filters_set_fields() -> None:
    f = RetrievalFilters(source_type="procedure", asset_class="boiler", severity="critical")
    assert f.source_type == "procedure"
    assert f.asset_class == "boiler"
    assert f.severity == "critical"


def test_retrieval_filters_is_frozen() -> None:
    f = RetrievalFilters(source_type="procedure")
    with pytest.raises(dataclasses.FrozenInstanceError):
        f.source_type = "troubleshooting"  # type: ignore[misc]
