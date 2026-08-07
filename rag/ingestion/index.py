"""Pluggable vector index for the RAG corpus.

The pipeline only depends on the :class:`VectorIndex` protocol.
The default implementation is :class:`InMemoryVectorIndex`, which
holds vectors in RAM and pickles the index to disk.

Why in-memory + pickle
----------------------

* **No new infra dep.** Pickle is stdlib. The pipeline runs in
  a clean container without a database or a vector store.
* **Deterministic rebuild.** Same corpus + same embedder
  produces a byte-identical persisted index. Verified by a
  test in :file:`test_pipeline.py`.
* **Good enough for the corpus size.** Six documents, ~25-40
  chunks. Retrieval latency is irrelevant.

Why a Protocol boundary
-----------------------

Story 4.2 (retrieval) might want a FAISS-backed index for
latency. The protocol lets us swap implementations later
without touching the pipeline. We mark the boundary
explicitly so that the future FAISS index can land as a
follow-up without changing the pipeline's contract.
"""
from __future__ import annotations

import pickle
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from .chunker import Chunk

INDEX_VERSION = 1


@dataclass(frozen=True)
class IndexedChunk:
    """A chunk with its embedding vector.

    The :class:`VectorIndex` stores one of these per chunk;
    the retrieval service (Story 4.2) reads them back.
    """

    chunk: Chunk
    vector: list[float]


@dataclass(frozen=True)
class IndexMetadata:
    """Bookkeeping written alongside the chunk store.

    Lets a future operator answer: how many chunks, when
    was the index last produced, which embedder built it.
    """

    version: int
    dimension: int
    embedder_name: str
    chunk_count: int
    document_count: int


@dataclass()
class InMemoryVectorIndex:
    """Default vector index. Pickles to disk.

    Notes
    -----
    The class is not frozen — it builds state incrementally
    via :meth:`add`. The persisted representation is what
    callers actually hold across the wire.
    """

    metadata: IndexMetadata
    entries: list[IndexedChunk] = field(default_factory=list)

    def add(self, chunks: list[Chunk], vectors: list[list[float]]) -> None:
        """Append ``chunks`` and their ``vectors`` to the index.

        Raises
        ------
        ValueError
            If ``len(chunks) != len(vectors)`` or any vector's
            dimension does not match ``metadata.dimension``.
        """
        if len(chunks) != len(vectors):
            raise ValueError(
                f"chunks and vectors length mismatch: "
                f"{len(chunks)} vs {len(vectors)}"
            )
        for chunk, vector in zip(chunks, vectors, strict=True):
            if len(vector) != self.metadata.dimension:
                raise ValueError(
                    f"Vector dimension {len(vector)} does not match "
                    f"index metadata dimension {self.metadata.dimension} "
                    f"for chunk {chunk.chunk_id}"
                )
            self.entries.append(IndexedChunk(chunk=chunk, vector=list(vector)))

    def __len__(self) -> int:
        return len(self.entries)

    def save(self, path: Path) -> None:
        """Pickle the index to ``path``. Creates parent dirs."""
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(pickle.dumps(self, protocol=pickle.HIGHEST_PROTOCOL))

    @classmethod
    def load(cls, path: Path) -> InMemoryVectorIndex:
        """Load a pickled index from ``path``."""
        data = path.read_bytes()
        loaded = pickle.loads(data)  # noqa: S301 — trusted internal artefacts
        if not isinstance(loaded, InMemoryVectorIndex):
            raise ValueError(
                f"Pickled object at {path} is not an InMemoryVectorIndex: "
                f"got {type(loaded).__name__}"
            )
        if loaded.metadata.version != INDEX_VERSION:
            raise ValueError(
                f"Index at {path} has version {loaded.metadata.version}, "
                f"expected {INDEX_VERSION}"
            )
        return loaded


class VectorIndex(Protocol):
    """The interface the pipeline expects.

    Story 4.2's retrieval service consumes whichever
    implementation is supplied. The current implementation
    is :class:`InMemoryVectorIndex`; a future optional
    ``FaissVectorIndex`` would satisfy the same protocol.
    """

    def add(self, chunks: list[Chunk], vectors: list[list[float]]) -> None: ...
    def __len__(self) -> int: ...
    def save(self, path: Path) -> None: ...
    @classmethod
    def load(cls, path: Path) -> VectorIndex: ...


__all__ = [
    "INDEX_VERSION",
    "IndexMetadata",
    "IndexedChunk",
    "InMemoryVectorIndex",
    "VectorIndex",
]
