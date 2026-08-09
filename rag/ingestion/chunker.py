"""Sliding-window chunker for the RAG corpus.

Splits a :class:`LoadedDocument` into overlapping chunks of
near-fixed character length, while inheriting the nearest
preceding Markdown header as the chunk's section. Each chunk
carries the metadata Story 4.2 needs for retrieval filtering
and citations.

Why character-based, not token-based
------------------------------------

Character-based chunking is deterministic, model-agnostic, and
simple to reason about. Token boundaries get fuzzy across
encoders (BPE / WordPiece / SentencePiece split on different
characters) and the chunk text we'd embed would still be
re-tokenised by the embedding model. Character-based gives
Story 4.2 a stable ``chunk_id`` regardless of the embedder in
use.

Why a 800 / 100 split
---------------------

* ``chunk_size=800`` chars is roughly 200 tokens for typical
  English prose — well within the 256-token effective context
  of ``all-MiniLM-L6-v2`` once we account for embedding-model
  truncation.
* ``overlap=100`` (12.5 %) preserves enough context across the
  boundary to keep sentence-level meaning intact without
  doubling the index.

Why section inheritance
-----------------------

The corpus uses Markdown headers heavily (``# Symptom``,
``## Immediate actions``). The nearest preceding header
captures the document's narrative structure and gives the
retrieval service a cheap filter (``--section="Immediate
actions"``). It also makes citations more readable: a chunk
cites its doc, section, and chunk index.

Algorithm
---------

1. If the body fits in one window, return a single chunk.
2. Otherwise, slice the body into ``chunk_size`` windows
   starting at offsets ``0, chunk_size - overlap, 2 *
   (chunk_size - overlap), …``.
3. For each window, snap the end position to the previous
   newline so we don't slice a word. If there is no
   preceding newline (a very long line), the cut stays at
   ``chunk_size``.
4. Tags each chunk with the nearest preceding header.
5. Trailing fragments shorter than 50 chars are merged into
   the previous chunk.

Short-document behaviour
------------------------

If the entire body is shorter than ``chunk_size`` (e.g. a
short SOP), the document is emitted as a single chunk,
regardless of character count. The 50-char minimum filters
*fragments* (accidental whitespace splits, lone header lines)
that the sliding window would otherwise produce at the tail
of a longer document — it does not gate swallowing a doc.

Non-goals
---------

* **No sentence-boundary alignment.** A chunk may end mid-word
  in the worst case. ``all-MiniLM-L6-v2`` is robust to this;
  the gain in deterministic chunk IDs is worth it.
* **No semantic chunking.** Embedding-based or topic-based
  chunking is a future Story 4.2 question.
* **No token-length override.** The pipeline exposes
  ``chunk_size`` / ``overlap`` as kwargs so a future caller
  can experiment.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .loader import LoadedDocument

# Minimum chunk length for fragments produced by the sliding
# window. Anything shorter is merged into the previous chunk
# so we don't pollute the index with tiny fragments (e.g.
# trailing punctuation, single header lines).
_MIN_CHUNK_CHARS = 50

# Markdown header regex. Matches ``#``, ``##``, ``###`` headers
# at the start of a line. ``#+`` then a space then the title.
_HEADER_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$", re.MULTILINE)


@dataclass(frozen=True)
class Chunk:
    """A windowed slice of a document, ready for embedding.

    Attributes
    ----------
    chunk_id:
        ``{doc_id}#{chunk_index}`` — the citeable unit.
    doc_id:
        The source document's ``doc_id``.
    chunk_index:
        Zero-based index of the chunk within the document.
    text:
        The chunk text. Front-matter is not included.
    section:
        Nearest preceding Markdown header, or ``None`` if the
        chunk sits before the first header.
    source_type:
        Inherited from the source document.
    asset_class:
        Inherited from the source document, or ``None``.
    severity:
        Inherited from the source document, or ``None``.
    tags:
        Inherited from the source document.
    """

    chunk_id: str
    doc_id: str
    chunk_index: int
    text: str
    section: str | None
    source_type: str
    asset_class: str | None
    severity: str | None
    tags: list[str] = field(default_factory=list)


def chunk_document(
    doc: LoadedDocument,
    *,
    chunk_size: int = 800,
    overlap: int = 100,
) -> list[Chunk]:
    """Split a :class:`LoadedDocument` into overlapping :class:`Chunk` s.

    Parameters
    ----------
    doc:
        The source document.
    chunk_size:
        Window size in characters. Must be >= 1.
    overlap:
        Window overlap in characters. Must be >= 0 and
        < ``chunk_size``.

    Returns
    -------
    list[Chunk]
        Chunks in document order. ``chunk_index`` is the
        zero-based position in this list.
    """
    if chunk_size < 1:
        raise ValueError(f"chunk_size must be >= 1, got {chunk_size}")
    if overlap < 0 or overlap >= chunk_size:
        raise ValueError(
            f"overlap must be in [0, chunk_size), got overlap={overlap}, "
            f"chunk_size={chunk_size}"
        )

    body = doc.body
    if not body.strip():
        return []

    header_positions = _header_positions(body)

    # Short-document path: the entire body fits in one
    # window. Emit a single chunk regardless of length — the
    # 50-char filter is for *fragments* produced by the
    # sliding window, not for swallowing whole documents.
    if len(body) <= chunk_size:
        text = body.strip()
        if not text:
            return []
        section = _active_section(header_positions, 0)
        return [_make_chunk(doc, 0, text, section)]

    # Long-document path: sliding window.
    chunks: list[Chunk] = []
    chunk_index = 0
    pos = 0
    n = len(body)

    while pos < n:
        end_excl = min(pos + chunk_size, n)
        # Snap the cut to the previous newline so we don't
        # slice a word. If there is no preceding newline
        # within the window, take the full window.
        prev_nl = body.rfind("\n", pos, end_excl)
        if prev_nl > pos:
            cut = prev_nl + 1  # keep the newline in the chunk
        else:
            cut = end_excl

        text = body[pos:cut].strip()
        if not text:
            # Whitespace-only window — advance to the next
            # non-whitespace character and continue.
            next_pos = pos + 1
            while next_pos < n and body[next_pos].isspace():
                next_pos += 1
            pos = next_pos
            continue

        if len(text) < _MIN_CHUNK_CHARS and chunks:
            # Tiny fragment — merge with the previous chunk.
            prev = chunks[-1]
            chunks[-1] = _merge_text(prev, text)
        else:
            section = _active_section(header_positions, pos)
            chunks.append(_make_chunk(doc, chunk_index, text, section))
            chunk_index += 1

        # Advance to the next window. The next chunk should
        # start at ``cut - overlap`` so the overlap is
        # preserved after the snap. With ``overlap=0`` this
        # is just ``cut``.
        next_pos = cut - overlap
        if next_pos <= pos:
            next_pos = pos + 1
        if next_pos >= n:
            break
        pos = next_pos

    return chunks


def _header_positions(body: str) -> list[tuple[int, str]]:
    """Return a list of ``(char_offset, header_text)`` for every header.

    Offsets are computed against the original body, so they
    can be compared to slice positions.
    """
    return [(m.start(), m.group(2).strip()) for m in _HEADER_RE.finditer(body)]


def _active_section(headers: list[tuple[int, str]], pos: int) -> str | None:
    """Return the header that is active at character offset ``pos``."""
    active: str | None = None
    for offset, header in headers:
        if offset > pos:
            break
        active = header
    return active


def _make_chunk(
    doc: LoadedDocument,
    chunk_index: int,
    text: str,
    section: str | None,
) -> Chunk:
    return Chunk(
        chunk_id=f"{doc.doc_id}#{chunk_index}",
        doc_id=doc.doc_id,
        chunk_index=chunk_index,
        text=text,
        section=section,
        source_type=doc.source_type,
        asset_class=doc.asset_class,
        severity=doc.severity,
        tags=list(doc.tags),
    )


def _merge_text(prev: Chunk, text: str) -> Chunk:
    """Return a new ``Chunk`` with ``text`` appended to ``prev``."""
    return Chunk(
        chunk_id=prev.chunk_id,
        doc_id=prev.doc_id,
        chunk_index=prev.chunk_index,
        text=prev.text + "\n" + text,
        section=prev.section,
        source_type=prev.source_type,
        asset_class=prev.asset_class,
        severity=prev.severity,
        tags=prev.tags,
    )
