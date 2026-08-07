"""Unit tests for the full ingestion pipeline."""
from __future__ import annotations

from pathlib import Path

import pytest

from rag.ingestion import (
    DEFAULT_DIMENSION,
    Chunk,
    DeterministicEmbeddingModel,
    InMemoryVectorIndex,
    run_ingestion,
)
from rag.ingestion.errors import IngestionError

REPO_ROOT = Path(__file__).resolve().parents[3]
CORPUS_DIR = REPO_ROOT / "rag" / "documents"


def _make_minimal_corpus(tmp_path: Path, *, doc_id: str = "doc-1") -> Path:
    """Write a small but valid corpus to ``tmp_path``.

    Two documents so the loader has at least two items to walk;
    the second one is short enough to fit in a single chunk.
    """
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / "a.md").write_text(
        "---\n"
        f"doc_id: {doc_id}-a\n"
        "title: A\n"
        "source_type: troubleshooting\n"
        "version: 1.0\n"
        "last_updated: 2026-01-01\n"
        "---\n"
        "# Heading\n"
        "\n"
        "Body of A. " * 20
        + "\n",
        encoding="utf-8",
    )
    (tmp_path / "b.md").write_text(
        "---\n"
        f"doc_id: {doc_id}-b\n"
        "title: B\n"
        "source_type: procedure\n"
        "version: 1.0\n"
        "last_updated: 2026-01-01\n"
        "---\n"
        "Body of B.\n",
        encoding="utf-8",
    )
    return tmp_path


def test_run_ingestion_produces_report_and_index(tmp_path: Path) -> None:
    corpus = _make_minimal_corpus(tmp_path / "corpus")
    index_path = tmp_path / "index.pkl"
    embedder = DeterministicEmbeddingModel(dimension=DEFAULT_DIMENSION)

    report = run_ingestion(
        corpus_dir=corpus,
        index_path=index_path,
        embedder=embedder,
    )

    assert report.documents == 2
    assert report.chunks >= 1
    assert report.duration_s >= 0.0
    assert report.index_path == index_path
    assert "deterministic" in report.embedder_name

    assert index_path.exists()
    idx = InMemoryVectorIndex.load(index_path)
    assert len(idx) == report.chunks


def test_run_ingestion_is_deterministic_across_rebuilds(tmp_path: Path) -> None:
    corpus = _make_minimal_corpus(tmp_path / "corpus")
    embedder = DeterministicEmbeddingModel(dimension=DEFAULT_DIMENSION)

    a_path = tmp_path / "a.pkl"
    b_path = tmp_path / "b.pkl"

    run_ingestion(corpus_dir=corpus, index_path=a_path, embedder=embedder)
    run_ingestion(corpus_dir=corpus, index_path=b_path, embedder=embedder)

    assert a_path.read_bytes() == b_path.read_bytes()


def test_run_ingestion_against_real_corpus(tmp_path: Path) -> None:
    """Smoke test against the committed corpus at ``rag/documents``.

    Skipped if the corpus directory is empty (e.g. fresh checkout
    before the docs have been committed).
    """
    if not CORPUS_DIR.exists() or not any(CORPUS_DIR.glob("*.md")):
        pytest.skip("committed corpus not present")

    index_path = tmp_path / "v1.pkl"
    embedder = DeterministicEmbeddingModel(dimension=DEFAULT_DIMENSION)
    report = run_ingestion(corpus_dir=CORPUS_DIR, index_path=index_path, embedder=embedder)
    assert report.documents >= 6
    assert report.chunks >= 1
    idx = InMemoryVectorIndex.load(index_path)
    assert len(idx) == report.chunks


def test_run_ingestion_propagates_ingestion_errors(tmp_path: Path) -> None:
    corpus = tmp_path / "broken"
    corpus.mkdir()
    (corpus / "broken.md").write_text("# No front-matter\n", encoding="utf-8")
    with pytest.raises(IngestionError):
        run_ingestion(corpus_dir=corpus, index_path=tmp_path / "i.pkl")


def test_run_ingestion_rejects_empty_corpus(tmp_path: Path) -> None:
    corpus = tmp_path / "empty"
    corpus.mkdir()
    embedder = DeterministicEmbeddingModel(dimension=DEFAULT_DIMENSION)
    report = run_ingestion(corpus_dir=corpus, index_path=tmp_path / "i.pkl", embedder=embedder)
    assert report.documents == 0
    assert report.chunks == 0


def test_persisted_index_carries_chunks_with_metadata(tmp_path: Path) -> None:
    corpus = _make_minimal_corpus(tmp_path / "corpus")
    embedder = DeterministicEmbeddingModel(dimension=DEFAULT_DIMENSION)
    index_path = tmp_path / "i.pkl"
    run_ingestion(corpus_dir=corpus, index_path=index_path, embedder=embedder)

    idx = InMemoryVectorIndex.load(index_path)
    # Every entry should carry a Chunk with chunk_id and metadata.
    for entry in idx.entries:
        assert isinstance(entry.chunk, Chunk)
        assert entry.chunk.chunk_id
        assert entry.chunk.doc_id
        assert entry.chunk.source_type
        assert entry.vector
        assert len(entry.vector) == DEFAULT_DIMENSION
