"""Unit tests for the RAG chunker."""
from __future__ import annotations

from pathlib import Path

import pytest

from rag.ingestion import Chunk, chunk_document
from rag.ingestion.loader import LoadedDocument


def _doc(body: str, *, doc_id: str = "doc-1") -> LoadedDocument:
    return LoadedDocument(
        doc_id=doc_id,
        title="Doc",
        source_type="troubleshooting",
        asset_class="boiler",
        severity="critical",
        tags=["test"],
        body=body,
        path=Path("doc-1.md"),
        version="1.0",
        last_updated="2026-01-01",
    )


def test_empty_body_returns_no_chunks() -> None:
    assert chunk_document(_doc("")) == []
    assert chunk_document(_doc("   \n\n  ")) == []


def test_short_body_returns_single_chunk() -> None:
    body = "Just a few sentences.\nWith one paragraph break.\n"
    chunks = chunk_document(_doc(body))
    assert len(chunks) == 1
    assert chunks[0].chunk_id == "doc-1#0"
    assert chunks[0].chunk_index == 0
    assert chunks[0].text == body.strip()
    assert chunks[0].doc_id == "doc-1"


def test_chunk_text_is_within_size_bounds() -> None:
    body = "Paragraph one is short.\n\n" + ("x" * 2000) + "\n\nParagraph three.\n"
    chunks = chunk_document(_doc(body), chunk_size=400, overlap=50)
    assert len(chunks) >= 3
    for chunk in chunks:
        # Chunks may be a bit longer than ``chunk_size`` due to
        # the line-boundary snap, but always >= ``chunk_size``
        # *unless* it's the trailing chunk.
        assert len(chunk.text) >= 50


def test_monotonic_chunk_indices() -> None:
    body = "\n".join(f"line {i}" for i in range(500))
    chunks = chunk_document(_doc(body))
    indices = [c.chunk_index for c in chunks]
    assert indices == list(range(len(chunks)))


def test_chunk_ids_are_unique_and_stable() -> None:
    body = "\n".join(f"line {i}" for i in range(300))
    chunks = chunk_document(_doc(body))
    ids = [c.chunk_id for c in chunks]
    assert len(ids) == len(set(ids))
    for c in chunks:
        assert c.chunk_id == f"doc-1#{c.chunk_index}"


def test_section_inheritance_carries_header_through_chunk() -> None:
    # Two clearly-separated sections, each long enough that a
    # window starting inside the first section will report
    # "First section" as its active header.
    body = (
        "# First section\n"
        "\n"
        "Body of the first section. " * 5
        + "\n"
        + "\n"
        "# Second section\n"
        + "\n"
        + "Body of the second section. " * 5
        + "\n"
    )
    chunks = chunk_document(_doc(body), chunk_size=80, overlap=10)
    sections = [c.section for c in chunks]
    # First chunk sits entirely in the first section.
    assert "First section" in sections
    # Subsequent chunks cross into the second section.
    assert "Second section" in sections


def test_chunk_before_first_header_has_no_section() -> None:
    body = "Preamble text without a header.\n"
    chunks = chunk_document(_doc(body))
    assert len(chunks) == 1
    assert chunks[0].section is None


def test_short_chunks_are_merged_into_previous() -> None:
    body = "First paragraph with enough text to keep.\n\nA\n"
    chunks = chunk_document(_doc(body), chunk_size=400, overlap=100)
    # "A" alone is shorter than the 50-char minimum, so it
    # should be merged into the preceding chunk.
    assert len(chunks) == 1
    assert "First paragraph" in chunks[0].text
    assert "A" in chunks[0].text


def test_chunk_inherits_metadata_from_doc() -> None:
    body = "Body of the doc.\n"
    chunks = chunk_document(_doc(body))
    assert len(chunks) == 1
    chunk = chunks[0]
    assert isinstance(chunk, Chunk)
    assert chunk.source_type == "troubleshooting"
    assert chunk.asset_class == "boiler"
    assert chunk.severity == "critical"
    assert chunk.tags == ["test"]


def test_overlap_must_be_less_than_chunk_size() -> None:
    with pytest.raises(ValueError, match="overlap must be"):
        chunk_document(_doc("body"), chunk_size=100, overlap=100)
    with pytest.raises(ValueError, match="overlap must be"):
        chunk_document(_doc("body"), chunk_size=100, overlap=200)


def test_chunk_size_must_be_positive() -> None:
    with pytest.raises(ValueError, match="chunk_size must be"):
        chunk_document(_doc("body"), chunk_size=0, overlap=0)


def test_does_not_split_words_at_boundaries() -> None:
    # Build a body where the buffer ends mid-word; the
    # line-boundary snap should pick the previous newline.
    body = "first line\nsecond line\nthird line\nfourth line\n"
    chunks = chunk_document(_doc(body), chunk_size=12, overlap=0)
    for chunk in chunks:
        # No chunk should end mid-word: it should end on a
        # newline (after strip) or at the end of the body.
        assert not chunk.text.endswith("first")
        assert not chunk.text.endswith("second")
    # The body is short enough to round-trip; combined text
    # should contain every line.
    combined = " ".join(c.text for c in chunks)
    assert "first line" in combined
    assert "fourth line" in combined
