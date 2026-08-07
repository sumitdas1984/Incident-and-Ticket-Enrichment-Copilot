"""Prompt-injection defence for the retrieval service.

The corpus contains two deliberate injection seeds (see
:file:`tests/unit/rag/test_corpus.py::test_prompt_injection_seeds_are_present_for_story_4_2`).
This module is the *first* line of defence — a configurable
regex blocklist.

Why a regex blocklist
---------------------

* **Cheap.** No extra model call per chunk; the entire corpus
  is filtered in milliseconds.
* **Deterministic.** Tests can pin the exact patterns and
  assert specific drops.
* **Auditable.** Every drop is logged with the chunk ID and
  the matched pattern.
* **Operationally extensible.** New patterns can be added
  without code changes — the orchestrator can pass a
  richer blocklist at startup.

What this is not
----------------

This is not a complete defence. The full defence (per
``docs/rag-design.md`` § 6) is layered:

1. Regex blocklist (this module).
2. Strict citation sandwich — the LLM only sees the excerpt,
   not the raw chunk text.
3. Tool-output isolation — chunks are passed as data, not
   instructions.
4. LLM-based detection (a future hardening pass).

The blocklist's job is to short-circuit the obvious cases
so the LLM never sees them.

Why regex and not a sequence of ``str.contains`` checks
-------------------------------------------------------

Regex composes naturally with the corpus's case sensitivity
and the spammy variation ("IGNORE previous instructions",
"ignore PREVIOUS instructions", "Ignoring previous…" — the
regex can normalise case). The cost is identical to a
``str.contains`` call.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from rag.ingestion import IndexedChunk

# Default blocklist. Targets the two seeds committed to the
# corpus plus the canonical "ignore / override / disregard"
# vocabulary. Operators can extend this by passing a richer
# list to :class:`RetrievalService` at construction.
DEFAULT_INJECTION_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"ignore\s+(?:all\s+)?(?:previous|prior)\s+instructions", re.IGNORECASE),
    re.compile(r"override\s+mode", re.IGNORECASE),
    re.compile(r"disregard\s+(?:all\s+)?(?:previous|prior)\s+instructions", re.IGNORECASE),
    re.compile(r"system\s*:\s*\[\s*override\s*\]", re.IGNORECASE),
)


@dataclass(frozen=True)
class InjectionDrop:
    """One chunk dropped by the blocklist.

    The retrieval service returns the dropped count in the
    :class:`RetrievalResult` and emits a log entry per drop.
    The :class:`InjectionDrop` dataclass is the structured
    form of that log entry; it is exposed for tests and
    future observability work.
    """

    chunk_id: str
    doc_id: str
    matched_pattern: str  # the regex pattern string


def find_injections(
    chunk: IndexedChunk,
    patterns: tuple[re.Pattern[str], ...] = DEFAULT_INJECTION_PATTERNS,
) -> str | None:
    """Return the regex pattern string that matched ``chunk``'s text,
    or ``None`` if no pattern matched.

    Only the first match is returned. The blocklist is short by
    design — there is no benefit to listing every match for an
    audit log.
    """
    for pattern in patterns:
        if pattern.search(chunk.chunk.text):
            return pattern.pattern
    return None


def filter_injections(
    chunks: list[IndexedChunk],
    patterns: tuple[re.Pattern[str], ...] = DEFAULT_INJECTION_PATTERNS,
) -> tuple[list[IndexedChunk], tuple[InjectionDrop, ...]]:
    """Drop every chunk whose text matches a pattern.

    Returns the surviving chunks (in their original order) plus
    the tuple of drops. The tuple is immutable so callers can
    log it without worrying about downstream mutation.
    """
    survivors: list[IndexedChunk] = []
    drops: list[InjectionDrop] = []
    for chunk in chunks:
        match = find_injections(chunk, patterns)
        if match is None:
            survivors.append(chunk)
        else:
            drops.append(
                InjectionDrop(
                    chunk_id=chunk.chunk.chunk_id,
                    doc_id=chunk.chunk.doc_id,
                    matched_pattern=match,
                )
            )
    return survivors, tuple(drops)


__all__ = [
    "DEFAULT_INJECTION_PATTERNS",
    "InjectionDrop",
    "filter_injections",
    "find_injections",
]
