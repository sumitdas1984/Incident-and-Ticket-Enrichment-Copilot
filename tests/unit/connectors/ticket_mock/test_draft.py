"""Unit tests for the ticket-mock draft generation."""
from __future__ import annotations

from connectors.ticket_mock.draft import build_draft


def test_build_draft_preview_returns_title_and_body() -> None:
    draft = build_draft(
        incident={
            "id": "INC-1",
            "title": "Boiler Feed Pump 101 high temp",
            "summary": "Investigate high temp on BFP 101.",
            "severity": "critical",
            "recommended_actions": ["Reduce feed rate", "Notify supervisor"],
            "similar_tickets": ["TKT-1042"],
        },
        approved=False,
    )
    assert draft.title == "Boiler Feed Pump 101 high temp"
    assert draft.body.startswith("Investigate high temp on BFP 101.")
    assert "1. Reduce feed rate" in draft.body
    assert "2. Notify supervisor" in draft.body
    assert draft.severity == "critical"
    assert draft.preview is True
    assert draft.ticket_id is None


def test_build_draft_preview_returns_labels_with_severity_and_related() -> None:
    draft = build_draft(
        incident={
            "id": "INC-1",
            "title": "X",
            "summary": "y",
            "severity": "high",
            "recommended_actions": [],
            "similar_tickets": ["TKT-1042", "TKT-1108"],
        },
        approved=False,
    )
    assert "severity:high" in draft.labels
    assert "related:TKT-1042" in draft.labels
    assert "related:TKT-1108" in draft.labels


def test_build_draft_approved_sets_preview_false() -> None:
    draft = build_draft(
        incident={
            "id": "INC-1",
            "title": "x",
            "summary": "y",
            "severity": "low",
            "recommended_actions": [],
            "similar_tickets": [],
        },
        approved=True,
    )
    assert draft.preview is False


def test_build_draft_missing_severity_defaults_to_medium() -> None:
    draft = build_draft(
        incident={"id": "INC-1", "title": "x", "summary": "y", "recommended_actions": []},
        approved=False,
    )
    assert draft.severity == "medium"


def test_build_draft_invalid_severity_defaults_to_medium() -> None:
    draft = build_draft(
        incident={"id": "INC-1", "title": "x", "summary": "y", "severity": "bogus"},
        approved=False,
    )
    assert draft.severity == "medium"


def test_build_draft_no_actions_omits_actions_block() -> None:
    draft = build_draft(
        incident={"id": "INC-1", "title": "x", "summary": "Body only", "severity": "high"},
        approved=False,
    )
    assert "Recommended actions" not in draft.body
    assert draft.body == "Body only"
