"""Unit tests for the RAG embedder wrappers."""
from __future__ import annotations

import pytest

from rag.ingestion import DeterministicEmbeddingModel


def test_deterministic_embedder_returns_one_vector_per_input() -> None:
    model = DeterministicEmbeddingModel(dimension=64)
    vectors = model.embed(["alpha", "beta", "gamma"])
    assert len(vectors) == 3
    for v in vectors:
        assert len(v) == 64


def test_deterministic_embedder_is_deterministic() -> None:
    model = DeterministicEmbeddingModel(dimension=64)
    a = model.embed(["hello", "world"])
    b = model.embed(["hello", "world"])
    assert a == b


def test_deterministic_embedder_distinguishes_inputs() -> None:
    # Two distinct inputs should produce two distinct vectors
    # (probability of collision in 64 dimensions is negligible).
    model = DeterministicEmbeddingModel(dimension=64)
    a, b = model.embed(["alpha", "beta"])
    assert a != b


def test_deterministic_embedder_handles_empty_input() -> None:
    model = DeterministicEmbeddingModel(dimension=64)
    assert model.embed([]) == []


def test_deterministic_embedder_handles_unicode() -> None:
    model = DeterministicEmbeddingModel(dimension=64)
    v = model.embed(["⌘ 中文 🚀"])[0]
    assert len(v) == 64
    # Determinism: re-embed and check equality.
    assert v == model.embed(["⌘ 中文 🚀"])[0]


def test_deterministic_embedder_rejects_zero_dimension() -> None:
    with pytest.raises(ValueError, match="dimension"):
        DeterministicEmbeddingModel(dimension=0)


def test_deterministic_embedder_handles_higher_dimensions() -> None:
    model = DeterministicEmbeddingModel(dimension=768)
    v = model.embed(["text"])[0]
    assert len(v) == 768


@pytest.mark.slow_embeddings
def test_sentence_transformer_embedder_shape() -> None:
    # CI excludes this marker (see ``.github/workflows/ci.yml``)
    # because the test downloads
    # ``sentence-transformers/all-MiniLM-L6-v2`` from Hugging Face
    # Hub on first run and the CI runner gets rate-limited (HTTP
    # 429). Run locally with ``uv run pytest -m slow_embeddings``
    # against a cached model. The ``pytest.importorskip`` makes
    # the test a clean skip on environments without the dep,
    # even when the marker is enabled.
    pytest.importorskip("sentence_transformers")
    from rag.ingestion import SentenceTransformerEmbeddingModel

    embedder = SentenceTransformerEmbeddingModel(model_name="all-MiniLM-L6-v2")
    vectors = embedder.embed(["hello", "world"])
    assert len(vectors) == 2
    assert all(len(v) == 384 for v in vectors)
