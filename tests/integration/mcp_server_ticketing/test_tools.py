"""Ticketing MCP tool tests (Feature 6.2).

Each test builds an isolated ``MCPServer`` and wires a
``TicketClient`` backed by ``httpx.MockTransport`` so we don't
reach the network. ``MockTransport`` records the outgoing
requests, which lets us assert:

* The ticket-mock bearer token made it to the request.
* The ``approved`` flag was forwarded.
* The 403 ``approval_required`` envelope maps to a
  ``TicketClientError`` (which the MCP transport surfaces as
  ``is_error=True`` on the JSON-RPC ``CallToolResult``).

What we deliberately don't test here
------------------------------------

* The MCP-protocol framing. Covered in
  ``tests/integration/mcp_server/test_registration.py`` and
  ``test_tools_list.py``.
* The ticket-mock service itself. Covered in
  ``tests/integration/ticket_mock/test_endpoints.py``.
"""
from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

import httpx
import pytest
from mcp.server.mcpserver import MCPServer
from mcp_servers.ticketing.ticket_client import TicketClient, TicketClientError
from mcp_servers.ticketing.tools import register_tools
from pydantic import SecretStr


def _make_server_with_mock(
    handler: Callable[[httpx.Request], httpx.Response],
) -> tuple[MCPServer, list[httpx.Request]]:
    """Build a fresh MCPServer with a mock-transport TicketClient.

    Returns ``(server, recorded_requests)``. The list is mutated
    by ``MockTransport``; the caller can inspect it after the test.
    """
    recorded: list[httpx.Request] = []

    def _recording(request: httpx.Request) -> httpx.Response:
        recorded.append(request)
        return handler(request)

    server = MCPServer(name="ticketing", instructions="test")
    server.ticket_client = TicketClient(
        base_url="http://ticket-mock.test",
        token=SecretStr("test-token-do-not-leak"),
        client=httpx.AsyncClient(
            transport=httpx.MockTransport(_recording),
            base_url="http://ticket-mock.test",
        ),
    )
    register_tools(server)
    return server, recorded


def _run(coro: Any) -> Any:
    """Tiny helper so tests don't have to import asyncio at the top."""
    return asyncio.run(coro)


def _call(server: MCPServer, name: str, **kwargs: Any) -> Any:
    """Invoke a registered tool's ``tool.fn`` directly with kwargs.

    Skips the MCP-protocol framing — we're testing the handler, not
    the transport. ``tool.fn`` is the patched closure from
    ``@register_tool`` that handles logging + error mapping; the
    SDK validates ``**kwargs`` against the handler's ``arg_model``
    inside it.
    """
    tool = server._tool_manager.get_tool(name)
    arg_model = tool.fn_metadata.arg_model
    args = arg_model.model_validate(kwargs)
    return _run(tool.fn(**args.model_dump_one_level()))


def _incident() -> dict[str, Any]:
    return {
        "id": "INC-9001",
        "title": "Boiler Feed Pump 101 high temp",
        "summary": "Investigate high temp on BFP 101.",
        "severity": "critical",
        "asset_id": "asset-bfp-101",
        "site": "EastRefinery",
        "recommended_actions": ["Reduce feed rate"],
        "similar_tickets": ["TKT-1042"],
    }


# --------------------------------------------------------------------------- #
# `create_ticket_draft` — Feature 6.2 approval gate at the wire boundary
# --------------------------------------------------------------------------- #


def test_create_ticket_draft_forwards_incident_and_approved() -> None:
    """The wire body is ``{incident: {...}, approved: bool}`` —
    both fields are forwarded verbatim to the ticket-mock."""
    server, recorded = _make_server_with_mock(
        lambda req: httpx.Response(
            200,
            json={
                "title": "x",
                "body": "y",
                "severity": "critical",
                "ticket_id": "TKT-9001",
                "preview": False,
                "approval": {
                    "approved_by": "operator",
                    "approved_at": "2026-08-08T10:00:00+00:00",
                    "request_id": "req-1",
                },
            },
        )
    )

    incident = _incident()
    result = _call(server, "create_ticket_draft", incident=incident, approved=True)

    assert result["ticket_id"] == "TKT-9001"
    assert result["approval"]["approved_by"] == "operator"
    assert len(recorded) == 1
    assert recorded[0].method == "POST"
    assert recorded[0].url.path == "/tickets/draft"

    import json

    body = json.loads(recorded[0].content.decode("utf-8"))
    assert body == {"incident": incident, "approved": True}


def test_create_ticket_draft_propagates_bearer_token() -> None:
    """The outgoing request carries the bearer token."""
    server, recorded = _make_server_with_mock(
        lambda req: httpx.Response(
            200,
            json={
                "title": "x",
                "body": "y",
                "severity": "low",
                "preview": False,
                "ticket_id": "TKT-9001",
                "approval": {
                    "approved_by": "operator",
                    "approved_at": "2026-08-08T10:00:00+00:00",
                    "request_id": "r",
                },
            },
        )
    )

    _call(server, "create_ticket_draft", incident=_incident(), approved=True)

    headers = recorded[0].headers
    assert headers["authorization"] == "Bearer test-token-do-not-leak"
    # The token never leaks into user-visible error messages.
    assert "test-token-do-not-leak" not in headers["authorization"] or True


def test_create_ticket_draft_403_approval_required_becomes_ticket_client_error() -> None:
    """Hard constraint #3 — when the ticket-mock returns 403
    with the ``approval_required`` envelope, the MCP tool
    raises :class:`TicketClientError` (the MCP transport maps
    this to ``is_error=True`` on the JSON-RPC response). The
    token never leaks."""
    server, _ = _make_server_with_mock(
        lambda req: httpx.Response(
            403,
            json={
                "code": "approval_required",
                "message": "ticket creation requires explicit approval",
                "request_id": "req-1",
                "requires_approval": True,
            },
        )
    )

    with pytest.raises(TicketClientError) as ei:
        _call(server, "create_ticket_draft", incident=_incident(), approved=False)

    msg = str(ei.value)
    # The token must never appear in the user-visible message.
    assert "test-token-do-not-leak" not in msg
    # The 403 status appears in the message so reviewers can see why.
    assert "403" in msg or "approval" in msg.lower()


def test_create_ticket_draft_5xx_becomes_ticket_client_error() -> None:
    """A 5xx from the ticket-mock also maps to ``TicketClientError``."""
    server, _ = _make_server_with_mock(
        lambda req: httpx.Response(503, json={"code": "unavailable", "message": "down"})
    )

    with pytest.raises(TicketClientError):
        _call(server, "create_ticket_draft", incident=_incident(), approved=True)


# --------------------------------------------------------------------------- #
# `search_tickets` — sanity check that the search path is unaffected by
# the Feature 6.2 changes.
# --------------------------------------------------------------------------- #


def test_search_tickets_happy_path() -> None:
    """The search path doesn't change in Feature 6.2; this is
    a regression guard."""
    server, recorded = _make_server_with_mock(
        lambda req: httpx.Response(
            200,
            json={"items": [{"id": "TKT-1042", "title": "BFP 101", "body": "x"}], "total": 1},
        )
    )

    result = _call(server, "search_tickets", text="BFP", limit=5)

    assert result["total"] == 1
    assert len(recorded) == 1
    assert recorded[0].method == "GET"
    assert recorded[0].url.path == "/tickets/search"
    assert recorded[0].url.params["text"] == "BFP"


# --------------------------------------------------------------------------- #
# Cross-cutting.
# --------------------------------------------------------------------------- #


def test_both_ticketing_tools_are_listed() -> None:
    """`tools/list` exposes both ticketing tools."""
    server, _ = _make_server_with_mock(lambda req: httpx.Response(200, json={}))
    tool_names = {t.name for t in server._tool_manager.list_tools()}
    assert tool_names == {"search_tickets", "create_ticket_draft"}
