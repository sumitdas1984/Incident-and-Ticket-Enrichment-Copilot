"""Pydantic request / response models for the ticket-mock service.

The shapes are intentionally aligned with the orchestrator's
``core.domain.TicketDraft`` so the wire format never has to
widen. The service adds a ``ticket_id`` field on the response
when the caller's request carries ``approved=True``.
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
    its id; when ``False``, the response carries the draft but
    no ``ticket_id``.
    """

    model_config = ConfigDict(extra="forbid")

    incident: dict[str, Any]
    approved: bool = False


class TicketDraftResponse(BaseModel):
    """The wire format for ``POST /tickets/draft``."""

    model_config = ConfigDict(extra="forbid")

    title: str
    body: str
    severity: TicketSeverity
    assignee: str | None = None
    labels: list[str] = Field(default_factory=list)
    ticket_id: str | None = None
    preview: bool = True


class HealthResponse(BaseModel):
    """The wire format for ``GET /health``."""

    model_config = ConfigDict(extra="forbid")

    status: str
    service: str = "ticket-mock"
    version: str = "0.1.0"


__all__ = [
    "HealthResponse",
    "Ticket",
    "TicketDraftRequest",
    "TicketDraftResponse",
    "TicketListResponse",
    "TicketSeverity",
    "TicketStatus",
]
