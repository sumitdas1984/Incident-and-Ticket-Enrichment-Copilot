"""GET /tickets/search, POST /tickets/draft, and GET /tickets/audit.

Hard constraint #3 from the brief — "ticket / issue creation is
a write operation; it must require explicit user confirmation
in the GUI before the MCP server is invoked" — is enforced at
``POST /tickets/draft``: when ``approved=False`` the endpoint
returns a structured 403 envelope (no draft, no write, no
audit row). Successful writes append an :class:`AuditEntry` to
the in-memory store and surface :class:`TicketApprovalInfo` on
the response so the GUI can render "approved by … at …".
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from core.config import get_settings

from ..auth import require_bearer
from ..draft import build_draft
from ..models import (
    AuditListResponse,
    Ticket,
    TicketApprovalInfo,
    TicketApprovalRequiredError,
    TicketDraftRequest,
    TicketDraftResponse,
    TicketListResponse,
    TicketStatus,
)
from ..search import search_tickets
from ..store import TicketStore

router = APIRouter(prefix="/tickets", tags=["tickets"], dependencies=[Depends(require_bearer)])


def _store(request: Request) -> TicketStore:
    """Return the ticket store attached to ``app.state``."""
    store = getattr(request.app.state, "ticket_store", None)
    if store is None:
        raise RuntimeError("TicketStore is not attached to app.state")
    return store


@router.get("/search", response_model=TicketListResponse)
def search_endpoint(
    request: Request,
    text: str | None = Query(None, min_length=1),
    asset_id: str | None = Query(None),
    site: str | None = Query(None),
    status: TicketStatus | None = Query(None),
    limit: int = Query(5, ge=1, le=20),
) -> TicketListResponse:
    """Search the in-memory ticket store.

    The ``text`` parameter is a free-form substring matched
    against the ticket's title and body. ``asset_id`` and
    ``site`` are exact-match filters. ``status`` filters by
    ticket status (``open`` / ``in_progress`` / ``resolved`` /
    ``closed``).
    """
    store = _store(request)
    items = search_tickets(
        store.list_all(),
        text=text,
        asset_id=asset_id,
        site=site,
        status=status,
        limit=limit,
    )
    return TicketListResponse(items=items, total=len(items))


@router.get("/audit", response_model=AuditListResponse)
def audit_endpoint(
    request: Request,
    limit: int = Query(50, ge=1, le=200),
) -> AuditListResponse:
    """Return the in-memory audit log (Feature 6.2).

    Bounded by ``limit`` (1..200, default 50). The list is a
    snapshot — callers should treat it as read-only. The audit
    log lives in memory; restart of the service clears it. This
    is documented as a known limitation.
    """
    store = _store(request)
    items = store.list_audit()
    return AuditListResponse(items=items[:limit], total=len(items))


@router.post("/draft", response_model=TicketDraftResponse)
def draft_endpoint(
    request: Request,
    body: TicketDraftRequest,
) -> TicketDraftResponse:
    """Generate (and optionally persist) a ticket draft.

    Hard constraint #3 — ticket creation is a write operation and
    requires explicit user confirmation in the GUI before the MCP
    server is invoked. When ``approved=False`` the endpoint returns
    a structured 403 envelope with ``code="approval_required"``;
    no draft is built, no ticket is persisted, no audit row is
    appended. When ``approved=True`` the ticket is persisted, the
    audit row is appended, and the response carries the assigned
    ``ticket_id`` plus a :class:`TicketApprovalInfo` block.
    """
    store = _store(request)

    # Feature 6.2 — fail closed if approval is missing.
    if not body.approved:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=TicketApprovalRequiredError(
                message="ticket creation requires explicit approval",
                request_id=uuid.uuid4().hex,
            ).model_dump(),
        )

    settings = get_settings()
    draft = build_draft(body.incident, approved=True)

    # Persist the ticket. The store allocates the id; the draft
    # body is the wire body verbatim.
    ticket_id = store.next_id()
    now = datetime.now(tz=UTC)
    request_id = uuid.uuid4().hex
    persisted = Ticket(
        id=ticket_id,
        title=draft.title,
        body=draft.body,
        status="open",
        severity=draft.severity,
        asset_id=body.incident.get("asset_id"),
        site=body.incident.get("site"),
        incident_id=body.incident.get("id"),
        created_at=now,
    )
    store.create(persisted)

    # Append the audit row. ``append_audit`` allocates the entry
    # id and is thread-safe via the store's lock.
    store.append_audit(
        ticket_id=ticket_id,
        request_id=request_id,
        approved_by=settings.approval_user,
        approved_at=now,
        incident_id=body.incident.get("id"),
    )

    approval = TicketApprovalInfo(
        approved_by=settings.approval_user,
        approved_at=now,
        request_id=request_id,
    )
    return draft.model_copy(
        update={
            "ticket_id": ticket_id,
            "preview": False,
            "approval": approval,
        }
    )


@router.get("/{ticket_id}", response_model=Ticket)
def get_ticket(request: Request, ticket_id: str) -> Ticket:
    """Return a single ticket by id."""
    store = _store(request)
    ticket = store.get(ticket_id)
    if ticket is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "not_found", "message": f"Ticket {ticket_id} not found"},
        )
    return ticket


# Re-export the type for the public surface; the router file is the
# canonical importer for these Pydantic shapes from the search/audit
# path (the orchestrator uses them via ``TicketDraftResponse``).
__all__ = ["router"]
