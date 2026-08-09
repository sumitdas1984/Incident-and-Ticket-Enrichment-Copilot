"""GET /tickets/similar — surface past tickets that match a query.

The endpoint is read-only and returns a small static list seeded
in :file:`connectors/alarm_api/seed.py`. The simulator's
contract is "give back plausible matches" — there is no real
similarity index. The orchestrator (Feature 5.2) calls this
through the MCP server's ``search_similar_tickets`` tool.

Why a static list
-----------------

A real ticket-similarity index requires an embedding model and
a vector store — both already present in the project, but
wiring them up adds latency the demo path does not need. The
seeded list has 5 entries with pre-baked ``similarity`` scores
so the orchestrator's top-N filter is deterministic.

The simulator's response is small enough to read in a glance
when the orchestrator's RAG retriever (also deterministic) is
asked "find related past tickets" — the ``Or`` math is
union-of-keywords, not the spelled-out Python.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query, Request

from ..auth import require_bearer
from ..models import TicketListResponse, TicketSummary
from ..seed import SEED_TICKETS

router = APIRouter(prefix="/tickets", tags=["tickets"], dependencies=[Depends(require_bearer)])


@router.get("/similar", response_model=TicketListResponse)
def similar_tickets(
    request: Request,
    text: str = Query(..., min_length=1, description="Free-form query text"),
    site: str | None = Query(None),
    asset_class: str | None = Query(None),
    limit: int = Query(5, ge=1, le=20),
) -> TicketListResponse:
    """Return past tickets most relevant to ``text``.

    The orchestrator sizes ``limit`` to 5 by default. The
    simulator applies a soft filter on ``site`` and ``asset_class``
    and ranks the survivors by their pre-baked ``similarity``.
    """
    candidates: list[dict[str, Any]] = [dict(item) for item in SEED_TICKETS]
    if site is not None:
        candidates = [c for c in candidates if c.get("site") == site]
    if asset_class is not None:
        candidates = [c for c in candidates if c.get("asset_class") == asset_class]
    candidates.sort(key=lambda c: c.get("similarity", 0.0), reverse=True)
    candidates = candidates[:limit]

    items = [TicketSummary(**c) for c in candidates]
    return TicketListResponse(items=items, total=len(items))
