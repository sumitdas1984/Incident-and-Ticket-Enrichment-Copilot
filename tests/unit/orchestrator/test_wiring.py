"""Unit tests for the orchestrator wiring layer.

The wiring layer is the one place that decides which
embedder is plugged into the retrieval service at runtime.
These tests cover the two config switches
(``embedder_backend=deterministic`` vs
``embedder_backend=sentence-transformers``) and the
guard that rejects a runtime embedder that does not match
the persisted index.

Why guard against mismatch
--------------------------

A query embedder that was not the one that built the index
produces cosine similarities that look plausible but mean
nothing. The historic footgun was that the orchestrator
silently retrieved nonsense (see limitation #7 in
``docs/known-limitations.md``). The fix is a single check
in ``_build_rag`` that compares ``embedder.model_name``
against ``IndexMetadata.embedder_name``. These tests pin
both halves of the new contract.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from apps.backend.wiring import _build_rag
from core.config import Settings
from core.exceptions import LLMError
from rag.ingestion import (
    Chunk,
    DeterministicEmbeddingModel,
    IndexMetadata,
    InMemoryVectorIndex,
)


def _persist_index(path: Path, *, embedder_name: str, dimension: int = 64) -> None:
    """Write a tiny in-memory index to ``path`` with the given embedder name."""
    chunk = Chunk(
        chunk_id="doc-1#0",
        doc_id="doc-1",
        chunk_index=0,
        text="hello world",
        section=None,
        source_type="troubleshooting",
        asset_class=None,
        severity=None,
        tags=[],
    )
    embedder = DeterministicEmbeddingModel(dimension=dimension)
    meta = IndexMetadata(
        version=1,
        dimension=dimension,
        embedder_name=embedder_name,
        chunk_count=1,
        document_count=1,
    )
    idx = InMemoryVectorIndex(metadata=meta)
    idx.add([chunk], embedder.embed(["hello world"]))
    path.parent.mkdir(parents=True, exist_ok=True)
    idx.save(path)


def test_build_rag_default_uses_deterministic_embedder(tmp_path: Path) -> None:
    """The default ``embedder_backend=deterministic`` wires the
    deterministic embedder and succeeds when the index was built
    with the same one."""
    index_path = tmp_path / "index.pkl"
    _persist_index(index_path, embedder_name="deterministic:64")

    settings = Settings(embedder_backend="deterministic")
    executor = _build_rag(index_path=index_path, settings=settings)

    # The retrieval service must be using the deterministic model
    # that matches the index.
    assert executor._service._embedder.model_name == "deterministic:64"  # type: ignore[attr-defined]


def test_build_rag_raises_on_index_runtime_mismatch(tmp_path: Path) -> None:
    """If the operator rebuilds the index with the real embedder
    but forgets to flip ``EMBEDDER_BACKEND``, the orchestrator
    must refuse to query — not silently produce nonsense."""
    index_path = tmp_path / "index.pkl"
    # Persist an index that *claims* to be a sentence-transformer
    # index. The runtime is still configured for deterministic, so
    # the guard must trip.
    _persist_index(
        index_path,
        embedder_name="sentence-transformers:all-MiniLM-L6-v2",
        dimension=384,
    )

    settings = Settings(embedder_backend="deterministic")
    with pytest.raises(LLMError) as excinfo:
        _build_rag(index_path=index_path, settings=settings)

    msg = str(excinfo.value)
    assert "Embedder mismatch" in msg
    assert "sentence-transformers:all-MiniLM-L6-v2" in msg
    assert "deterministic:384" in msg


def test_build_rag_raises_when_index_missing(tmp_path: Path) -> None:
    """The helper must raise a clear ``LLMError`` (not a generic
    ``FileNotFoundError``) when the index file is missing so the
    operator is told to run ``make ingest``."""
    settings = Settings(embedder_backend="deterministic")
    with pytest.raises(LLMError) as excinfo:
        _build_rag(index_path=tmp_path / "does-not-exist.pkl", settings=settings)
    assert "make ingest" in str(excinfo.value)
