"""Result type for the retrieval service.

The retrieval service (Story 4.2) returns a :class:`RetrievalResult`
that bundles the ranked citations with the confidence band the
orchestrator needs to drive the next step (render, send to LLM,
or surface a "no confident answer" message).

Why a separate module
---------------------

The dataclasses are shared by the orchestrator glue, the GUI
renderer, and the tests. Keeping them in this one module makes
the public surface obvious and prevents the rank/filter code
from sprawling with view-layer concerns.
"""
from __future__ import annotations

from dataclasses import dataclass

# Confidence bands exposed to the orchestrator. The string
# values are part of the contract — they end up in the MCP
# execution trace and the rendered GUI output.
CONFIDENCE_HIGH = "high"
CONFIDENCE_MEDIUM = "medium"
CONFIDENCE_LOW = "low"
CONFIDENCE_NONE = "none"

CONFIDENCE_BANDS: tuple[str, ...] = (
    CONFIDENCE_HIGH,
    CONFIDENCE_MEDIUM,
    CONFIDENCE_LOW,
    CONFIDENCE_NONE,
)

# Length of the citation excerpt — the first N characters of the
# chunk text. Kept short so the LLM prompt stays compact and the
# GUI can render the citation without scrolling.
CITATION_EXCERPT_CHARS = 200


@dataclass(frozen=True)
class Citation:
    """One chunk's citation metadata.

    The retrieval service emits one :class:`Citation` per
    surviving chunk. The fields are sufficient to render the
    citation in the GUI, the LLM prompt, and the MCP execution
    trace — without re-reading the chunk.

    Attributes
    ----------
    doc_id:
        Source document's ``doc_id`` (also the filename stem).
    chunk_id:
        Citeable unit, ``{doc_id}#{chunk_index}``.
    title:
        Human-readable title inherited from the document.
    section:
        Nearest preceding Markdown header, or ``None``.
    source_type:
        One of ``troubleshooting`` / ``procedure`` /
        ``knowledge_article`` / ``resolution_note`` /
        ``escalation``.
    asset_class:
        Inherited from the document, or ``None``.
    severity:
        Inherited from the document, or ``None``.
    excerpt:
        The first ``CITATION_EXCERPT_CHARS`` characters of the
        chunk text. Trimmed to fit the LLM prompt.
    score:
        Cosine similarity in ``[-1, 1]``. For the bundled
        embedders it is effectively in ``[0, 1]``.
    """

    doc_id: str
    chunk_id: str
    title: str
    section: str | None
    source_type: str
    asset_class: str | None
    severity: str | None
    excerpt: str
    score: float


@dataclass(frozen=True)
class RetrievalResult:
    """The output of one retrieval call.

    An empty ``citations`` list paired with a confidence band is
    a valid result — the orchestrator must surface it as a
    "no confident answer" rather than fabricate one.

    Attributes
    ----------
    citations:
        Top-k citations, sorted by descending ``score``.
    confidence:
        One of ``"high"`` / ``"medium"`` / ``"low"`` / ``"none"``.
        ``"none"`` is set when ``citations`` is empty.
    top_score:
        The highest score in ``citations``, or ``0.0`` when the
        list is empty.
    threshold:
        The ``confidence_threshold`` the service was configured
        with. Surfaces the calibration point to the caller.
    dropped_count:
        Number of chunks dropped by the injection blocklist
        before ranking. Useful for audit / observability.
    """

    citations: list[Citation]
    confidence: str
    top_score: float
    threshold: float
    dropped_count: int


@dataclass(frozen=True)
class RetrievalFilters:
    """Optional metadata filters applied during retrieval.

    All fields are optional and combine with ``AND``. A field
    set to ``None`` is not part of the filter.

    The same set of fields is exposed in the MCP server's
    retrieval tool (Story 5.1.3) so the orchestrator can ask
    e.g. "give me the boiler-related procedure" by setting
    ``asset_class="boiler"`` instead of asking the LLM to
    filter after the fact.
    """

    source_type: str | None = None
    asset_class: str | None = None
    severity: str | None = None


__all__ = [
    "CITATION_EXCERPT_CHARS",
    "CONFIDENCE_BANDS",
    "CONFIDENCE_HIGH",
    "CONFIDENCE_LOW",
    "CONFIDENCE_MEDIUM",
    "CONFIDENCE_NONE",
    "Citation",
    "RetrievalFilters",
    "RetrievalResult",
]
