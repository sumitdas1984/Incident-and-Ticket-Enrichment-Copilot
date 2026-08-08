"""GET /tickets/search and POST /tickets/draft endpoints."""
from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from ..auth import require_bearer
from ..draft import build_draft
from ..models import (
    Ticket,
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


@router.post("/draft", response_model=TicketDraftResponse)
def draft_endpoint(
    request: Request,
    body: TicketDraftRequest,
) -> TicketDraftResponse:
    """Generate a ticket draft from an incident payload.

    When ``approved=True``, the draft is persisted and the
    response carries the assigned ``ticket_id``. When ``False``,
    the draft is returned in preview mode (no ticket is created).
    Hard constraint #3 from the brief — "ticket / issue creation
    is a write operation; it must require explicit user
    confirmation in the GUI before the MCP server is invoked" —
    is implemented at the orchestrator layer (Feature 6.2). Here
    we just honour the flag the caller passes.
    """
    store = _store(request)
    draft = build_draft(body.incident, approved=body.approved)
    if not body.approved:
        return draft

    # Persist the ticket. The store allocates the id; the draft
    # body is the wire body verbatim.
    ticket_id = store.next_id()
    now = datetime.now(tz=UTC)
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
    return draft.model_copy(update={"ticket_id": ticket_id, "preview": False})


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
