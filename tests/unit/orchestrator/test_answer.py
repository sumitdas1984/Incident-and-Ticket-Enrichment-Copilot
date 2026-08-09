"""Unit tests for the final-answer composer."""
from __future__ import annotations

from apps.backend.orchestrator.answer import compose_answer
from core.domain import Citation


def test_compose_includes_intent() -> None:
    out = compose_answer(
        intent="investigate",
        prior_outputs={"s1": "ok"},
        citations=[],
        rag_confidence="none",
        dropped_count=0,
        trace_size=1,
    )
    assert "investigate" in out


def test_compose_includes_citations() -> None:
    citations = [
        Citation(
            doc_id="doc-1",
            section="1. Immediate actions",
            page=None,
            score=0.42,
            excerpt="x",
        ),
    ]
    out = compose_answer(
        intent="",
        prior_outputs={"s1": "x"},
        citations=citations,
        rag_confidence="low",
        dropped_count=0,
        trace_size=1,
    )
    assert "doc-1" in out
    assert "1. Immediate actions" in out
    assert "score=0.42" in out


def test_compose_includes_dropped_count_warning() -> None:
    out = compose_answer(
        intent="",
        prior_outputs={"s1": "x"},
        citations=[],
        rag_confidence="low",
        dropped_count=2,
        trace_size=1,
    )
    assert "dropped" in out.lower()
    assert "2" in out


def test_compose_summarizes_dict_with_items() -> None:
    out = compose_answer(
        intent="",
        prior_outputs={"s1": {"items": [{"id": 1}, {"id": 2}]}},
        citations=[],
        rag_confidence="none",
        dropped_count=0,
        trace_size=1,
    )
    assert "2 item" in out


def test_compose_handles_empty_outputs() -> None:
    out = compose_answer(
        intent="",
        prior_outputs={},
        citations=[],
        rag_confidence="none",
        dropped_count=0,
        trace_size=0,
    )
    assert "Confidence: none" in out
