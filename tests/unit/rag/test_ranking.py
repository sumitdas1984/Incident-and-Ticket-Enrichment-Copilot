"""Unit tests for the retrieval ranking helpers."""
from __future__ import annotations

import pytest

from rag.ingestion import Chunk, IndexedChunk, IndexMetadata, InMemoryVectorIndex
from rag.retrieval import cosine_similarity, rank_candidates, top_k


def _chunk(cid: str, text: str) -> Chunk:
    doc_id, _, idx = cid.partition("#")
    return Chunk(
        chunk_id=cid,
        doc_id=doc_id,
        chunk_index=int(idx),
        text=text,
        section=None,
        source_type="troubleshooting",
        asset_class=None,
        severity=None,
        tags=[],
    )


def _indexed(cid: str, vec: list[float]) -> IndexedChunk:
    capacity = max(len(vec), 1)
    meta = IndexMetadata(
        version=1,
        dimension=capacity,
        embedder_name="test",
        chunk_count=1,
        document_count=1,
    )
    idx = InMemoryVectorIndex(metadata=meta)
    idx.add([_chunk(cid, "placeholder")], [vec])
    return idx.entries[0]


def test_cosine_similarity_identical_vectors_is_one() -> None:
    a = [1.0, 0.0, 0.0]
    assert cosine_similarity(a, a) == pytest.approx(1.0)


def test_cosine_similarity_orthogonal_vectors_is_zero() -> None:
    assert cosine_similarity([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)


def test_cosine_similarity_opposite_vectors_is_minus_one() -> None:
    assert cosine_similarity([1.0, 0.0], [-1.0, 0.0]) == pytest.approx(-1.0)


def test_cosine_similarity_rejects_dimension_mismatch() -> None:
    with pytest.raises(ValueError, match="dimension mismatch"):
        cosine_similarity([1.0, 0.0], [0.0, 1.0, 0.0])


def test_cosine_similarity_returns_zero_for_zero_vector() -> None:
    assert cosine_similarity([0.0, 0.0], [1.0, 0.0]) == 0.0


def test_top_k_returns_top_scoring_chunks_descending() -> None:
    chunks = [
        _indexed("a#0", [1.0, 0.0]),
        _indexed("b#0", [0.7, 0.7]),
        _indexed("c#0", [0.0, 1.0]),
        _indexed("d#0", [-1.0, 0.0]),
    ]
    out = top_k([1.0, 0.0], chunks, k=2)
    assert [c.chunk.chunk_id for c, _ in out] == ["a#0", "b#0"]
    assert [round(s, 3) for _, s in out] == [pytest.approx(1.0), pytest.approx(0.707, rel=1e-3)]


def test_top_k_returns_empty_when_k_is_zero() -> None:
    chunks = [_indexed("a#0", [1.0, 0.0])]
    assert top_k([1.0, 0.0], chunks, k=0) == []


def test_top_k_returns_empty_when_k_is_negative() -> None:
    chunks = [_indexed("a#0", [1.0, 0.0])]
    assert top_k([1.0, 0.0], chunks, k=-1) == []


def test_top_k_clamps_to_candidate_count() -> None:
    chunks = [_indexed("a#0", [1.0, 0.0]), _indexed("b#0", [0.0, 1.0])]
    out = top_k([1.0, 0.0], chunks, k=10)
    assert len(out) == 2


def test_top_k_is_stable_on_ties() -> None:
    # Both vectors are unit-length along the same axis, so they
    # tie on cosine similarity. Sort order is implementation-
    # defined; we assert the output is sorted by descending score
    # and that both survivors are present.
    chunks = [
        _indexed("a#0", [1.0, 0.0]),
        _indexed("b#0", [1.0, 0.0]),
    ]
    out = top_k([1.0, 0.0], chunks, k=2)
    assert [c.chunk.chunk_id for c, _ in out] == ["a#0", "b#0"]
    assert all(round(s, 6) == pytest.approx(1.0) for _, s in out)


def test_rank_candidates_returns_all_pairs_sorted() -> None:
    chunks = [
        _indexed("a#0", [1.0, 0.0]),
        _indexed("b#0", [0.0, 1.0]),
    ]
    out = rank_candidates([1.0, 0.0], chunks)
    assert len(out) == 2
    assert out[0][0].chunk.chunk_id == "a#0"
    assert out[1][0].chunk.chunk_id == "b#0"
    assert out[0][1] > out[1][1]
