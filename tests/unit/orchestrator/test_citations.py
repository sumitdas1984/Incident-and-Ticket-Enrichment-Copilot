"""Unit tests for the citation adapter."""
from __future__ import annotations

import pytest

from core.domain import Citation as DomainCitation
from rag.retrieval import Citation as RagCitation


def test_to_domain_citation_copies_fields() -> None:
    from apps.backend.orchestrator.citations import to_domain_citation

    rag = RagCitation(
        doc_id="boiler-tube-leak",
        chunk_id="boiler-tube-leak#0",
        title="boiler-tube-leak",
        section="1. Immediate actions",
        source_type="troubleshooting",
        asset_class="boiler",
        severity="critical",
        excerpt="leak in the boiler",
        score=0.42,
    )
    domain = to_domain_citation(rag)
    assert isinstance(domain, DomainCitation)
    assert domain.doc_id == "boiler-tube-leak"
    assert domain.section == "1. Immediate actions"
    assert domain.score == pytest.approx(0.42)
    assert domain.excerpt == "leak in the boiler"
    assert domain.page is None


def test_to_domain_citation_drops_rag_specific_fields() -> None:
    from apps.backend.orchestrator.citations import to_domain_citation

    rag = RagCitation(
        doc_id="x",
        chunk_id="x#0",
        title="x",
        section=None,
        source_type="troubleshooting",
        asset_class="boiler",
        severity="critical",
        excerpt="x",
        score=0.0,
    )
    domain = to_domain_citation(rag)
    # The domain model has no `chunk_id`, `title`, `source_type`,
    # `asset_class`, or `severity` fields — confirm those are
    # not propagated (silent-bug guard).
    assert not hasattr(domain, "chunk_id")
    assert not hasattr(domain, "source_type")
    assert not hasattr(domain, "asset_class")
    assert not hasattr(domain, "severity")
