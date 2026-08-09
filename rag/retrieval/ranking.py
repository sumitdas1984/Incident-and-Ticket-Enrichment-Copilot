"""Vector ranking for the retrieval service.

The retrieval service ranks chunks by cosine similarity against
the query vector. The implementation is deliberately small:

* Pure-Python fallback for unit tests.
* ``numpy`` (already a transitive dep of ``sentence-transformers``)
  for the production path. The corpus is small enough that the
  difference is microscopic, but ``numpy`` is the right tool.

Why cosine
----------

The embedding model is :class:`SentenceTransformerEmbeddingModel`
with ``normalize_embeddings=False`` (see
:file:`rag/ingestion/embedder.py`). Cosine similarity is the
standard retriever for unnormalized sentence-transformer outputs;
the orchestrator's hard constraint #4 (every answer carries
"RAG document refs") rides on the score being comparable across
queries, which cosine gives us for free.
"""
from __future__ import annotations

from collections.abc import Iterable

# Module-level import is fine — ``numpy`` is a transitive dep
# of ``sentence-transformers`` and is listed in the resolved
# environment (verified in Feature 4.1).
import numpy as np

from rag.ingestion import IndexedChunk


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """Return the cosine similarity between two vectors.

    Returns ``0.0`` for zero-length vectors rather than raising
    — the retrieval tests want a graceful "no signal" rather
    than a division-by-zero in the middle of ranking.
    """
    if len(a) != len(b):
        raise ValueError(
            f"cosine_similarity: dimension mismatch "
            f"{len(a)} vs {len(b)}"
        )
    a_arr = np.asarray(a, dtype=np.float64)
    b_arr = np.asarray(b, dtype=np.float64)
    a_norm = float(np.linalg.norm(a_arr))
    b_norm = float(np.linalg.norm(b_arr))
    if a_norm == 0.0 or b_norm == 0.0:
        return 0.0
    return float(np.dot(a_arr, b_arr) / (a_norm * b_norm))


def rank_candidates(
    query_vec: list[float],
    candidates: Iterable[IndexedChunk],
) -> list[tuple[IndexedChunk, float]]:
    """Score every candidate against ``query_vec`` and return
    ``(chunk, score)`` pairs sorted by descending score.

    The result is list-form, not a numpy array — the caller
    slices the top-k and builds :class:`Citation` objects off
    the front. The corpus is small enough that the conversion
    overhead is invisible.
    """
    pairs: list[tuple[IndexedChunk, float]] = []
    for entry in candidates:
        score = cosine_similarity(query_vec, entry.vector)
        pairs.append((entry, score))
    pairs.sort(key=lambda pair: pair[1], reverse=True)
    return pairs


def top_k(
    query_vec: list[float],
    candidates: list[IndexedChunk],
    k: int,
) -> list[tuple[IndexedChunk, float]]:
    """Return the top-``k`` candidates by cosine similarity.

    ``k`` is clamped to the candidate count — passing
    ``k > len(candidates)`` is not an error. Passing
    ``k <= 0`` returns an empty list.
    """
    if k <= 0:
        return []
    ranked = rank_candidates(query_vec, candidates)
    return ranked[:k]


__all__ = ["cosine_similarity", "rank_candidates", "top_k"]
