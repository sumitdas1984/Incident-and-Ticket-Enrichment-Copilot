"""Unit tests for the RAG vector index."""
from __future__ import annotations

from pathlib import Path

import pytest

from rag.ingestion import (
    INDEX_VERSION,
    Chunk,
    IndexMetadata,
    InMemoryVectorIndex,
)


def _chunk(chunk_id: str = "doc-1#0") -> Chunk:
    return Chunk(
        chunk_id=chunk_id,
        doc_id="doc-1",
        chunk_index=0,
        text="text",
        section=None,
        source_type="troubleshooting",
        asset_class=None,
        severity=None,
        tags=[],
    )


def _metadata(*, dimension: int = 4, chunk_count: int = 0) -> IndexMetadata:
    return IndexMetadata(
        version=INDEX_VERSION,
        dimension=dimension,
        embedder_name="test",
        chunk_count=chunk_count,
        document_count=1,
    )


def test_empty_index_has_zero_length() -> None:
    idx = InMemoryVectorIndex(metadata=_metadata())
    assert len(idx) == 0


def test_add_inserts_entries() -> None:
    idx = InMemoryVectorIndex(metadata=_metadata(dimension=4))
    idx.add([_chunk("doc-1#0"), _chunk("doc-1#1")], [[0.0] * 4, [1.0] * 4])
    assert len(idx) == 2


def test_add_rejects_length_mismatch() -> None:
    idx = InMemoryVectorIndex(metadata=_metadata(dimension=4))
    with pytest.raises(ValueError, match="length mismatch"):
        idx.add([_chunk("doc-1#0")], [[0.0] * 4, [1.0] * 4])


def test_add_rejects_dimension_mismatch() -> None:
    idx = InMemoryVectorIndex(metadata=_metadata(dimension=4))
    with pytest.raises(ValueError, match="dimension"):
        idx.add([_chunk("doc-1#0")], [[0.0] * 3])


def test_save_and_load_round_trip(tmp_path: Path) -> None:
    idx = InMemoryVectorIndex(metadata=_metadata(dimension=4, chunk_count=1))
    idx.add([_chunk("doc-1#0")], [[0.5, 0.5, 0.5, 0.5]])
    p = tmp_path / "index.pkl"
    idx.save(p)
    assert p.exists()

    reloaded = InMemoryVectorIndex.load(p)
    assert len(reloaded) == 1
    assert reloaded.metadata.embedder_name == "test"
    assert reloaded.metadata.version == INDEX_VERSION
    assert reloaded.entries[0].chunk.chunk_id == "doc-1#0"
    assert reloaded.entries[0].vector == [0.5, 0.5, 0.5, 0.5]


def test_save_creates_parent_directories(tmp_path: Path) -> None:
    idx = InMemoryVectorIndex(metadata=_metadata(dimension=4))
    p = tmp_path / "deep" / "nested" / "index.pkl"
    idx.save(p)
    assert p.exists()


def test_load_rejects_foreign_object(tmp_path: Path) -> None:
    import pickle

    p = tmp_path / "index.pkl"
    p.write_bytes(b"not a pickle")
    # ``pickle.loads`` raises ``pickle.UnpicklingError`` on
    # malformed input. The loader surfaces any failure that
    # bubbles up; we accept both ``UnpicklingError`` and
    # ``ValueError`` (the loader's own mapping) as valid.
    with pytest.raises((pickle.UnpicklingError, ValueError)):
        InMemoryVectorIndex.load(p)


def test_load_rejects_wrong_version(tmp_path: Path) -> None:
    import pickle

    p = tmp_path / "index.pkl"
    bad = InMemoryVectorIndex(metadata=_metadata(dimension=4))
    bad.metadata = IndexMetadata(
        version=INDEX_VERSION + 999,
        dimension=4,
        embedder_name="test",
        chunk_count=0,
        document_count=0,
    )
    p.write_bytes(pickle.dumps(bad))
    with pytest.raises(ValueError, match="version"):
        InMemoryVectorIndex.load(p)


def test_load_rejects_wrong_type(tmp_path: Path) -> None:
    import pickle

    p = tmp_path / "index.pkl"
    p.write_bytes(pickle.dumps({"not": "an index"}))
    with pytest.raises(ValueError, match="not an InMemoryVectorIndex"):
        InMemoryVectorIndex.load(p)
