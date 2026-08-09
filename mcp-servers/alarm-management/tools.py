"""Alarm Management MCP tools (Stories 3.2.1 – 3.2.4 + 5.2.1).

Five tools, all flat-kwargs shape (per Feature 3.1's
``@register_tool`` design):

* ``search_assets`` — Story 3.2.1 — ``GET /assets/search``
* ``get_alarm`` — Story 3.2.2 — ``GET /alarms/{alarm_id}``
* ``summarize_alarms`` — Story 3.2.3 — ``GET /alarms`` (paginated)
* ``recommend_actions`` — Story 3.2.4 — ``POST /recommendations/operator-actions``
* ``search_similar_tickets`` — Story 5.2.1 — ``GET /tickets/similar``

Why each tool is a thin wrapper, not business logic
--------------------------------------------------

The hard constraint from the brief is that the copilot reaches
the Alarm API exclusively through the MCP server. Keeping each
handler a thin pass-through — validate the input, call the
alarm-api via :class:`AlarmApiClient`, return the parsed JSON —
means a future contributor can't accidentally reimplement
filtering, ranking, or token handling inside the MCP server.

We register the client on the ``MCPServer`` instance at lifespan
startup (see ``__main__.py``); handlers read it via
:func:`get_alarm_api_client` so the dependency is explicit in
tests (``monkeypatch.setattr`` or attribute assignment).

Choosing ``GET /alarms`` over ``POST /alarms/summary``
------------------------------------------------------

Story 3.2.3 says "ranked alarms with priority". ``POST
/alarms/summary`` returns aggregated buckets + KPIs (counts per
group); ``GET /alarms`` returns ranked items with priority. We
map to ``GET /alarms`` for that reason. The summary endpoint
stays reachable from the orchestrator directly via the same
MCP server (Feature 3.5 / advanced ops) without exposing a
second tool here.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import Field

from core.domain import Severity
from core.logging import get_logger

from .alarm_api_client import AlarmApiClient
from .registry import register_tool

log = get_logger(__name__)


# --------------------------------------------------------------------------- #
# Client accessor.
# --------------------------------------------------------------------------- #
#
# The lifespan attaches the live client to the ``MCPServer`` instance at
# ``__aenter__``. Handlers read it via this accessor so tests can
# inject their own client (e.g. one backed by ``httpx.MockTransport``).
def get_alarm_api_client(server: Any) -> AlarmApiClient:
    """Return the :class:`AlarmApiClient` attached to ``server``.

    The accessor is intentionally a function (not a module-level
    singleton) so per-test ``MCPServer`` instances don't share state.
    """
    client = getattr(server, "alarm_api_client", None)
    if client is None:
        raise RuntimeError(
            "AlarmApiClient is not attached to the MCP server; "
            "did the lifespan run? (See __main__.MCPServerLifespan.)"
        )
    return client


def register_tools(server: Any) -> None:
    """Register all five Alarm Management tools on ``server``.

    Called once from ``__main__.py`` at startup. Idempotent only
    in the sense that registering twice will produce duplicate
    tools — the SDK doesn't dedupe by name.
    """

    @register_tool(
        server,
        name="search_assets",
        description=(
            "Search industrial assets by name fragment. Optional site / unit "
            "filters narrow the search. Returns ranked matches."
        ),
    )
    async def search_assets(
        query: str = Field(
            ...,
            min_length=1,
            max_length=200,
            description="Asset name fragment (e.g. 'Boiler').",
        ),
        site: str | None = Field(
            default=None,
            description="Optional site code (e.g. 'EastRefinery').",
        ),
        unit: str | None = Field(
            default=None,
            description="Optional unit code (e.g. 'Cracker-1').",
        ),
        limit: int = Field(
            default=10,
            ge=1,
            le=100,
            description="Maximum number of results to return (1-100).",
        ),
    ) -> dict[str, Any]:
        client = get_alarm_api_client(server)
        params: dict[str, Any] = {"query": query, "limit": limit}
        if site is not None:
            params["site"] = site
        if unit is not None:
            params["unit"] = unit
        return await client.get_json("/assets/search", params=params)

    @register_tool(
        server,
        name="get_alarm",
        description=(
            "Fetch a single alarm by id. Returns the alarm record "
            "(asset_id, severity, message, raised_at, acknowledged). "
            "Returns 'Alarm <id> not found.' if the alarm is unknown."
        ),
    )
    async def get_alarm(
        alarm_id: str = Field(
            ...,
            min_length=1,
            max_length=128,
            description="Alarm identifier returned by search / summarize.",
        ),
    ) -> dict[str, Any]:
        client = get_alarm_api_client(server)
        return await client.get_json(f"/alarms/{alarm_id}")

    @register_tool(
        server,
        name="summarize_alarms",
        description=(
            "List ranked alarms with filters (site / asset / severity / "
            "time range). Returns the most recent top-N (default 25) "
            "ordered by raised_at desc."
        ),
    )
    async def summarize_alarms(
        site: str | None = Field(
            default=None,
            description="Optional site code filter.",
        ),
        asset: str | None = Field(
            default=None,
            description="Optional asset id filter.",
        ),
        severity: Severity | None = Field(
            default=None,
            description="Optional severity filter (low / medium / high / critical).",
        ),
        since: datetime | None = Field(
            default=None,
            description="Optional inclusive lower bound on raised_at (ISO 8601).",
        ),
        until: datetime | None = Field(
            default=None,
            description="Optional inclusive upper bound on raised_at (ISO 8601).",
        ),
        limit: int = Field(
            default=25,
            ge=1,
            le=500,
            description="Page size (1-500); page is pinned to 1.",
        ),
    ) -> dict[str, Any]:
        client = get_alarm_api_client(server)
        params: dict[str, Any] = {
            "page": 1,
            "page_size": limit,
            "sort_by": "raised_at",
            "sort_order": "desc",
        }
        if site is not None:
            params["site"] = site
        if asset is not None:
            params["asset_id"] = asset
        if severity is not None:
            params["severity"] = severity.value
        if since is not None:
            params["start_time"] = since.isoformat()
        if until is not None:
            params["end_time"] = until.isoformat()
        return await client.get_json("/alarms", params=params)

    @register_tool(
        server,
        name="recommend_actions",
        description=(
            "Get recommended operator actions and a priority score for "
            "an alarm. Returns priority_score (0-100), a list of "
            "actions, and the rationale. Includes asset context and "
            "historical pattern when available."
        ),
    )
    async def recommend_actions(
        alarm_id: str = Field(
            ...,
            min_length=1,
            max_length=128,
            description="Alarm identifier to score and recommend against.",
        ),
    ) -> dict[str, Any]:
        client = get_alarm_api_client(server)
        return await client.post_json(
            "/recommendations/operator-actions",
            json={
                "alarm_id": alarm_id,
                "include_related": False,
                "include_asset_context": True,
                "include_historical_pattern": True,
            },
        )

    @register_tool(
        server,
        name="search_similar_tickets",
        description=(
            "Search past tickets that match a free-form query. "
            "Returns a list of ticket summaries with id, title, "
            "status, similarity score, and resolution excerpt. "
            "Optional site and asset_class filters narrow the "
            "search. Used by the orchestrator's chain to ground "
            "the incident draft in prior incident history."
        ),
    )
    async def search_similar_tickets(
        text: str = Field(
            ...,
            min_length=1,
            max_length=500,
            description="Free-form query text (e.g. 'boiler tube leak').",
        ),
        site: str | None = Field(
            default=None,
            description="Optional site code filter.",
        ),
        asset_class: str | None = Field(
            default=None,
            description="Optional asset class filter (e.g. 'boiler').",
        ),
        limit: int = Field(
            default=5,
            ge=1,
            le=20,
            description="Maximum number of tickets to return (1-20).",
        ),
    ) -> dict[str, Any]:
        client = get_alarm_api_client(server)
        params: dict[str, Any] = {"text": text, "limit": limit}
        if site is not None:
            params["site"] = site
        if asset_class is not None:
            params["asset_class"] = asset_class
        return await client.get_json("/tickets/similar", params=params)
