"""Pydantic request / response models for the ticket-mock service.

The shapes are intentionally aligned with the orchestrator's
``core.domain.TicketDraft`` so the wire format never has to
widen. The service adds a ``ticket_id`` field on the response
when the caller's request carries ``approved=True``.

Feature 6.2 adds the approval gate (hard constraint #3):

* ``POST /tickets/draft`` returns a 403 with
  :class:`TicketApprovalRequiredError` when ``approved=False``.
* On success the response carries :class:`TicketApprovalInfo`
  so the GUI can render "approved by … at …" alongside the
  ticket id.
* Every successful creation appends an :class:`AuditEntry`
  to the in-memory audit list, exposed via ``GET /tickets/audit``.
"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

# Severity band for ticket status. Mirrors the orchestrator's
# ``core.domain.Severity`` so the two layers can pass values
# through without conversion.
TicketSeverity = Literal["low", "medium", "high", "critical"]
TicketStatus = Literal["open", "in_progress", "resolved", "closed"]


class Ticket(BaseModel):
    """A single ticket record stored in the in-memory store."""

    model_config = ConfigDict(extra="forbid")

    id: str
    title: str
    body: str
    status: TicketStatus = "open"
    severity: TicketSeverity = "medium"
    asset_id: str | None = None
    site: str | None = None
    incident_id: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(tz=UTC))
    closed_at: datetime | None = None


class TicketListResponse(BaseModel):
    """The wire format for ``GET /tickets/search``."""

    model_config = ConfigDict(extra="forbid")

    items: list[Ticket]
    total: int


class TicketDraftRequest(BaseModel):
    """The wire format for ``POST /tickets/draft``.

    ``incident`` is the structured ``Incident`` payload built by
    the orchestrator (Feature 5.2). ``approved`` is the
    explicit-user-confirmation flag (hard constraint #3). When
    ``approved=True``, the service persists a ticket and returns
    its id; when ``False``, the request is rejected with a 403
    ``approval_required`` envelope.
    """

    model_config = ConfigDict(extra="forbid")

    incident: dict[str, Any]
    approved: bool = False


class TicketApprovalInfo(BaseModel):
    """Audit fields attached to a successful ticket creation.

    The orchestrator (and GUI) surface these alongside the
    assigned ``ticket_id`` so the reviewer can prove the write
    was sanctioned — "approved by … at …, request id …".
    """

    model_config = ConfigDict(extra="forbid")

    approved_by: str
    approved_at: datetime
    request_id: str


class TicketDraftResponse(BaseModel):
    """The wire format for ``POST /tickets/draft``.

    The ``approval`` block is populated on every persisted
    ticket. It is ``None`` for the (now-rejected) preview
    path; the orchestrator never invokes that path in
    production.
    """

    model_config = ConfigDict(extra="forbid")

    title: str
    body: str
    severity: TicketSeverity
    assignee: str | None = None
    labels: list[str] = Field(default_factory=list)
    ticket_id: str | None = None
    preview: bool = True
    approval: TicketApprovalInfo | None = None


class TicketApprovalRequiredError(BaseModel):
    """The wire shape of an approval-gate rejection (HTTP 403).

    Surfaced verbatim from the ticket-mock to the MCP tool's
    ``is_error=True`` payload and then to the orchestrator's
    trace step ``error`` field. The ``code`` is the stable
    contract — the orchestrator can match on it to drive a
    specific UI flow.
    """

    model_config = ConfigDict(extra="forbid")

    code: Literal["approval_required"] = "approval_required"
    message: str
    request_id: str
    requires_approval: Literal[True] = True


class AuditEntry(BaseModel):
    """One row in the in-memory audit log.

    The audit list is bounded by the store's lifetime — see
    ``docs/known-limitations.md``. Every successful ticket
    creation appends one row. The ``id`` is a uuid4 hex
    allocated by the store; ``request_id`` is the per-request
    correlation id echoed in the rejection envelope.
    """

    model_config = ConfigDict(extra="forbid")

    id: str
    ticket_id: str
    request_id: str
    approved_by: str
    approved_at: datetime
    incident_id: str | None = None
    action: Literal["create_ticket"] = "create_ticket"


class AuditListResponse(BaseModel):
    """The wire format for ``GET /tickets/audit``."""

    model_config = ConfigDict(extra="forbid")

    items: list[AuditEntry]
    total: int


class HealthResponse(BaseModel):
    """The wire format for ``GET /health``."""

    model_config = ConfigDict(extra="forbid")

    status: str
    service: str = "ticket-mock"
    version: str = "0.1.0"


__all__ = [
    "AuditEntry",
    "AuditListResponse",
    "HealthResponse",
    "Ticket",
    "TicketApprovalInfo",
    "TicketApprovalRequiredError",
    "TicketDraftRequest",
    "TicketDraftResponse",
    "TicketListResponse",
    "TicketSeverity",
    "TicketStatus",
]
