"""Ticketing MCP tools (Feature 6.1).

Two tools, both flat-kwargs shape:

* ``search_tickets`` — wraps the ticket-mock's
  ``GET /tickets/search`` endpoint.
* ``create_ticket_draft`` — wraps the ``POST /tickets/draft``
  endpoint. The MCP layer does not enforce the approval flag —
  that's the orchestrator's job (Feature 6.2). The flag is
  passed through verbatim from the orchestrator's chain payload.
"""
from __future__ import annotations

from typing import Any

from mcp_servers.alarm_management.registry import register_tool
from pydantic import Field

from core.logging import get_logger

from .ticket_client import TicketClient

log = get_logger(__name__)


# Module-level accessor for the live client (set by the
# lifespan in __main__.py). The pattern mirrors the alarm-management
# server's `get_alarm_api_client` accessor.
def get_ticket_client(server: Any) -> TicketClient:
    """Return the :class:`TicketClient` attached to ``server``."""
    client = getattr(server, "ticket_client", None)
    if client is None:
        raise RuntimeError(
            "TicketClient is not attached to the MCP server; "
            "did the lifespan run? (See __main__.py.)"
        )
    return client


def register_tools(server: Any) -> None:
    """Register both ticketing tools on ``server``.

    Called once from ``__main__.py`` after the client is
    attached at lifespan startup.
    """

    @register_tool(
        server,
        name="search_tickets",
        description=(
            "Search the ticket-mock's in-memory ticket store by "
            "free-form text. Optional asset_id and site filters "
            "narrow the search. Returns a list of ticket summaries "
            "with id, title, status, severity, and excerpt."
        ),
    )
    async def search_tickets(
        text: str | None = Field(
            default=None,
            min_length=1,
            max_length=500,
            description="Free-form substring matched against ticket title and body.",
        ),
        asset_id: str | None = Field(
            default=None,
            description="Optional exact-match asset id filter.",
        ),
        site: str | None = Field(
            default=None,
            description="Optional exact-match site filter.",
        ),
        status: str | None = Field(
            default=None,
            description="Optional ticket status filter (open / in_progress / resolved / closed).",
        ),
        limit: int = Field(
            default=5,
            ge=1,
            le=20,
            description="Maximum number of tickets to return (1-20).",
        ),
    ) -> dict[str, Any]:
        client = get_ticket_client(server)
        params: dict[str, Any] = {"limit": limit}
        if text is not None:
            params["text"] = text
        if asset_id is not None:
            params["asset_id"] = asset_id
        if site is not None:
            params["site"] = site
        if status is not None:
            params["status"] = status
        return await client.get_json("/tickets/search", params=params)

    @register_tool(
        server,
        name="create_ticket_draft",
        description=(
            "Generate a deterministic ticket draft from an "
            "Incident-shaped payload. When ``approved=True``, the "
            "draft is persisted on the ticket-mock and the "
            "response carries the assigned ``ticket_id``. When "
            "``False``, the draft is returned in preview mode with "
            "``preview=true`` and no ``ticket_id``. The approval "
            "flag is the orchestrator's contract — this tool does "
            "not enforce any policy of its own."
        ),
    )
    async def create_ticket_draft(
        incident: dict[str, Any] = Field(
            ...,
            description="The structured Incident payload (the orchestrator's core.domain.Incident).",
        ),
        approved: bool = Field(
            default=False,
            description="True to persist the ticket; False returns a preview draft.",
        ),
    ) -> dict[str, Any]:
        client = get_ticket_client(server)
        return await client.post_json(
            "/tickets/draft",
            json={"incident": incident, "approved": approved},
        )
