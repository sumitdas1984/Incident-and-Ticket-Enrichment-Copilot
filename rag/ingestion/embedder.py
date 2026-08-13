"""Embedding model wrappers for the RAG ingestion pipeline.

The pipeline only depends on the :class:`EmbeddingModel` protocol
— the concrete production model is :class:`SentenceTransformerEmbeddingModel`
and the test-time model is :class:`DeterministicEmbeddingModel`.

Why a Protocol boundary
-----------------------

The pipeline never knows which model is wired in. Story 4.2's
retrieval tests can stand up a fast deterministic model without
pulling a 80 MB file from the hub, while production can use
the real SentenceTransformer model on the same code path.

Why ``all-MiniLM-L6-v2``
------------------------

* 384-dim output, fast on CPU.
* Public MTEB benchmark shows strong baseline performance on
  technical / procedural text.
* Roughly 80 MB on disk; cacheable in CI.
* No external API call, no cloud credentials.

The model is documented in :file:`docs/rag-design.md` so
operators can swap it via a single kwarg.

Why a deterministic test embedder
---------------------------------

``sentence-transformers`` downloads weights on first use. CI
should not depend on that download. The deterministic embedder
hashes the input text and lays the bytes out into a 384-dim
vector — same input, same vector, no model load. It is not
*semantically* meaningful, but it is *deterministic* and
*shape-correct*, which is what tests need.
"""
from __future__ import annotations

import hashlib
from typing import Any, Protocol, runtime_checkable

from .errors import IngestionError

# Default dimensionality. ``all-MiniLM-L6-v2`` outputs 384-dim
# vectors. The deterministic embedder matches this so the same
# index file works regardless of which model is wired in.
DEFAULT_DIMENSION = 384


@runtime_checkable
class EmbeddingModel(Protocol):
    """The interface the pipeline expects.

    Implementations may be remote, local, on-CPU, on-GPU, or
    deterministic. The pipeline only sees this boundary.
    """

    @property
    def model_name(self) -> str:
        """Stable identifier for the embedder.

        Used by :func:`rag.ingestion.pipeline._embedder_name` to
        stamp :class:`IndexMetadata` at ingestion time, and by
        the orchestrator wiring to detect index-vs-runtime
        mismatches before retrieval starts producing nonsense.
        """
        ...

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Return one ``dimension``-long vector per input string.

        Raises
        ------
        IngestionError
            If the embedder fails to produce numerical output.
        """
        ...


class SentenceTransformerEmbeddingModel:
    """Production embedder wrapping ``sentence-transformers``.

    Parameters
    ----------
    model_name:
        HuggingFace model identifier. Defaults to
        ``all-MiniLM-L6-v2``. Swappable via constructor.
    device:
        Device to run the model on. ``"cpu"`` is the safe
        default; ``"cuda"`` is fine in GPU-equipped CI.
    dimension:
        Optional sanity check. If provided, the model is
        loaded once at init and the dimension is verified
        against the model's actual output dimensionality.
    """

    def __init__(
        self,
        *,
        model_name: str = "all-MiniLM-L6-v2",
        device: str = "cpu",
        dimension: int | None = DEFAULT_DIMENSION,
    ) -> None:
        try:
            from sentence_transformers import SentenceTransformer  # type: ignore[import-not-found]
        except ImportError as exc:  # pragma: no cover - import error path
            raise IngestionError(
                "sentence-transformers is not installed. "
                "Install with `uv add sentence-transformers`."
            ) from exc
        self._model_name = model_name
        self._model = SentenceTransformer(model_name, device=device)
        if dimension is not None:
            # ``get_sentence_embedding_dimension`` is deprecated in
            # sentence-transformers >= 5.0; ``get_embedding_dimension``
            # is the new name. Fall back to the old method for older
            # versions.
            actual: int | None = None
            getter: Any = getattr(self._model, "get_embedding_dimension", None)
            if callable(getter):
                actual = getter()
            else:
                getter = getattr(self._model, "get_sentence_embedding_dimension", None)
                if callable(getter):
                    actual = getter()
            if actual is not None and actual != dimension:
                raise IngestionError(
                    f"Embedding model {model_name!r} produces "
                    f"{actual}-dim vectors, expected {dimension}"
                )

    @property
    def model_name(self) -> str:
        """Stable identifier; mirrors
        ``rag.ingestion.pipeline._embedder_name`` so the
        orchestrator's index-vs-runtime guard compares apples
        to apples (``sentence-transformers:all-MiniLM-L6-v2``
        on both sides, not the bare model name on one side).
        """
        return f"sentence-transformers:{self._model_name}"

    def embed(self, texts: list[str]) -> list[list[float]]:
        vectors = self._model.encode(
            texts,
            convert_to_numpy=True,
            show_progress_bar=False,
            normalize_embeddings=False,
        )
        return [v.tolist() for v in vectors]


class DeterministicEmbeddingModel:
    """Test embedder that hashes text into a fixed-dim vector.

    The implementation is not semantically meaningful. It is
    intentionally simple and dependency-free so tests stay
    fast and the suite does not need to download the real
    model on every CI run.

    The vector is built by repeatedly hashing the text with
    SHA-256 and laying the bytes into 4-byte little-endian
    floats, until the target dimension is filled. The same
    input always produces the same vector.
    """

    def __init__(self, *, dimension: int = DEFAULT_DIMENSION) -> None:
        if dimension < 1:
            raise ValueError(f"dimension must be >= 1, got {dimension}")
        self._dimension = dimension

    @property
    def dimension(self) -> int:
        return self._dimension

    @property
    def model_name(self) -> str:
        # Mirrors the format produced by
        # ``rag.ingestion.pipeline._embedder_name`` so the
        # orchestrator's index-vs-runtime guard sees a stable
        # identifier for the deterministic embedder.
        return f"deterministic:{self._dimension}"

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [_hash_to_vector(t, self._dimension) for t in texts]


def _hash_to_vector(text: str, dimension: int) -> list[float]:
    """Deterministically map ``text`` to a ``dimension``-long vector.

    SHA-256 produces 32 bytes per round. We iterate the hash
    with an incrementing counter as the salt; each round
    yields 32 bytes = 8 floats. Enough rounds cover
    ``dimension`` floats.
    """
    need_bytes = dimension * 4
    buf = bytearray()
    counter = 0
    while len(buf) < need_bytes:
        h = hashlib.sha256(f"{counter}::{text}".encode()).digest()
        buf.extend(h)
        counter += 1

    # Slice to the requested byte length and interpret as
    # little-endian unsigned ints; map to [0, 1] floats so
    # the vector is well-conditioned for cosine similarity.
    raw = bytes(buf[:need_bytes])
    out: list[float] = []
    for i in range(dimension):
        chunk = raw[i * 4 : (i + 1) * 4]
        n = int.from_bytes(chunk, "little", signed=False)
        out.append((n / 0xFFFFFFFF) * 2.0 - 1.0)
    return out

