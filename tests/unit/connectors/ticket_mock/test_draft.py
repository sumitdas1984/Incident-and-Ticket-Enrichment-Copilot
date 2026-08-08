"""Unit tests for the ticket-mock draft generation.

Feature 6.2 adds the approval gate and audit list; the
endpoint-level tests for those paths live in
``tests/integration/ticket_mock/test_endpoints.py``. The unit
tests here cover the Pydantic shapes (request / response /
rejection envelope) and the helper ``build_draft``.
"""
from __future__ import annotations

import pytest

from connectors.ticket_mock.draft import build_draft
from connectors.ticket_mock.models import (
    AuditEntry,
    AuditListResponse,
    TicketApprovalInfo,
    TicketApprovalRequiredError,
    TicketDraftRequest,
    TicketDraftResponse,
)


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


# ---- Feature 6.2 — Pydantic shape tests ----


def test_ticket_draft_request_defaults_approved_false() -> None:
    """Hard constraint #3 — the default is fail-closed. If the
    caller omits ``approved``, the request is invalid for a
    write."""
    body = TicketDraftRequest(incident={"id": "INC-1"})
    assert body.approved is False


def test_ticket_draft_response_approval_defaults_to_none() -> None:
    """The new ``approval`` field defaults to ``None`` so the
    shape stays valid for the (now-rejected) preview path."""
    response = TicketDraftResponse(
        title="x",
        body="y",
        severity="low",
    )
    assert response.approval is None
    assert response.preview is True


def test_ticket_draft_response_carries_approval_block() -> None:
    """Successful writes attach a :class:`TicketApprovalInfo` block."""
    from datetime import UTC, datetime

    now = datetime.now(tz=UTC)
    info = TicketApprovalInfo(
        approved_by="operator",
        approved_at=now,
        request_id="req-1",
    )
    response = TicketDraftResponse(
        title="x",
        body="y",
        severity="low",
        ticket_id="TKT-9001",
        preview=False,
        approval=info,
    )
    assert response.approval is not None
    assert response.approval.approved_by == "operator"
    assert response.approval.request_id == "req-1"


def test_ticket_approval_required_error_shape() -> None:
    """The 403 envelope has a stable shape — ``code`` and
    ``requires_approval`` are literals so consumers can match on
    them."""
    err = TicketApprovalRequiredError(
        message="ticket creation requires explicit approval",
        request_id="req-1",
    )
    dumped = err.model_dump()
    assert dumped["code"] == "approval_required"
    assert dumped["requires_approval"] is True
    assert dumped["message"]
    assert dumped["request_id"] == "req-1"


def test_ticket_approval_required_error_rejects_extra_fields() -> None:
    """The model is ``extra='forbid'``; unknown fields are
    rejected at validation time."""
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        TicketApprovalRequiredError.model_validate(
            {
                "code": "approval_required",
                "message": "x",
                "request_id": "r",
                "requires_approval": True,
                "rogue": "field",  # noqa: S106
            }
        )


def test_audit_entry_default_action_is_create_ticket() -> None:
    """The ``action`` field is a literal; the default is
    ``create_ticket``. Future actions (close, reopen) extend
    the literal set; this test pins the current value."""
    from datetime import UTC, datetime

    entry = AuditEntry(
        id="a" * 32,
        ticket_id="TKT-9001",
        request_id="req-1",
        approved_by="operator",
        approved_at=datetime.now(tz=UTC),
        incident_id="INC-1",
    )
    assert entry.action == "create_ticket"


def test_audit_list_response_carries_total() -> None:
    """The audit list response carries a ``total`` field
    matching ``len(items)`` so the GUI can paginate."""
    response = AuditListResponse(items=[], total=0)
    assert response.total == 0
