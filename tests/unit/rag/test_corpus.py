"""Corpus-shape tests for the committed RAG documents.

These tests guard the corpus's structural integrity so future
edits don't accidentally drop a required front-matter field,
collapse the source-type diversity, or accidentally commit a
restricted-content doc.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from rag.ingestion import (
    ALLOWED_SOURCE_TYPES,
    OPTIONAL_FIELDS,
    REQUIRED_FIELDS,
    load_documents,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
CORPUS_DIR = REPO_ROOT / "rag" / "documents"


@pytest.fixture(scope="module")
def corpus_docs():
    if not CORPUS_DIR.exists() or not any(CORPUS_DIR.glob("*.md")):
        pytest.skip("committed corpus not present")
    return load_documents(CORPUS_DIR)


def test_corpus_has_at_least_six_documents(corpus_docs) -> None:
    assert len(corpus_docs) >= 6


def test_corpus_covers_at_least_four_source_types(corpus_docs) -> None:
    types = {d.source_type for d in corpus_docs}
    assert len(types) >= 4
    # All types must be in the allowed set.
    assert types <= ALLOWED_SOURCE_TYPES


def test_every_doc_has_required_fields(corpus_docs) -> None:
    for doc in corpus_docs:
        # The loader's __post_init__ enforces the doc_id shape
        # and the source_type, but the remaining REQUIRED_FIELDS
        # are enforced only via __init__ kwargs. We re-check
        # here by reading the attributes.
        for field_name in REQUIRED_FIELDS:
            value = getattr(doc, field_name)
            assert value, f"{doc.doc_id}: {field_name} is empty"
        for field_name in OPTIONAL_FIELDS:
            value = getattr(doc, field_name)
            if field_name == "tags":
                # ``tags`` is allowed to be missing (defaults to []).
                continue
            # Optional fields may be None but must not be empty
            # strings when present.
            if value is not None:
                assert value, f"{doc.doc_id}: optional field {field_name} is empty"


def test_no_doc_references_restricted_content(corpus_docs) -> None:
    """Sanity check: no doc accidentally includes restricted markers.

    The corpus is synthetic and we control it, so this is a
    belt-and-braces guard against future copy-paste mistakes.
    """
    for doc in corpus_docs:
        body = doc.body.lower()
        for marker in ("proprietary", "confidential", "do not distribute"):
            assert marker not in body, (
                f"{doc.doc_id}: body contains restricted marker {marker!r}"
            )


def test_doc_ids_are_unique_across_corpus(corpus_docs) -> None:
    ids = [d.doc_id for d in corpus_docs]
    assert len(ids) == len(set(ids))


def test_critical_docs_have_severity(corpus_docs) -> None:
    """Every doc with severity ``critical`` should also carry an asset_class."""
    for doc in corpus_docs:
        if doc.severity == "critical":
            # Critical docs apply to a specific asset; site-wide
            # critical docs are tagged ``site``.
            assert doc.asset_class in {"boiler", "compressor", "site", "distillation_column", "cooling_water"}


def test_prompt_injection_seeds_are_present_for_story_4_2(corpus_docs) -> None:
    """At least two docs contain prompt-injection seed text.

    Story 4.2 (prompt-injection defence) needs at least two
    real seeds to defend against. The test loader is *not*
    expected to strip these — retrieval is responsible for
    sanitisation.
    """
    seeds = ("ignore previous instructions", "override mode")
    seen = set()
    for doc in corpus_docs:
        body = doc.body.lower()
        for seed in seeds:
            if seed in body:
                seen.add(seed)
    # Both seeds should be present.
    assert seen == set(seeds), f"missing seeds: {seeds - seen}"
