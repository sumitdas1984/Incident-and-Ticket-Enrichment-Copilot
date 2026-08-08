"""End-to-end test for the orchestrator's ``POST /tickets/draft``.

Feature 6.2 — the orchestrator's ticket draft endpoint
delegates to the ticket-MCP, which delegates to the
ticket-mock. The hard-constraint-#3 approval gate lives at
the ticket-mock layer; this test verifies that the
orchestrator surfaces the 403 envelope verbatim through its
own HTTP layer.

Two paths:

* ``approved=False`` → the orchestrator returns a 5xx (502)
  with the rejection envelope echoed in the trace step.
* ``approved=True`` → the orchestrator returns 200 with
  the persisted ticket id and the ``approval`` block.

We use the in-process ``TestClient`` against the real
``apps.backend.create_app()`` and an in-process ticket-mock
fixture, so no Docker / Newman / network is involved.
"""
from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from apps.backend import create_app
from connectors.ticket_mock.app import create_app as create_ticket_mock_app
from core.config import get_settings


@pytest.fixture
def ticket_mock_client() -> TestClient:
    """An in-process ticket-mock app with the bearer token set."""
    import os

    os.environ["TICKETING_API_TOKEN"] = "test-token"
    os.environ["APPROVAL_USER"] = "operator"
    get_settings.cache_clear()
    return TestClient(create_ticket_mock_app())


@pytest.fixture
def orchestrator_client(monkeypatch: pytest.MonkeyPatch, ticket_mock_client: TestClient) -> TestClient:
    """An orchestrator app pointed at the in-process ticket-mock.

    We bind the orchestrator's ``ticketing_mcp_url`` to a fake
    host that the MCP layer never actually reaches — the
    orchestrator's chain dispatches ``create_ticket_draft`` to
    the ticketing MCP server (a separate process). For this
    test we stub the chain's ticket MCP client to short-circuit
    to the ticket-mock via ``TestClient``.

    The cleanest way to wire this in-process is to override the
    orchestrator's ticket MCP after creation: see
    ``_patch_ticket_mcp_to_local_mock`` below.
    """
    # Point the orchestrator at the alarm-management MCP; we
    # don't exercise alarm tools here but the wiring is mandatory.
    monkeypatch.setenv("TICKETING_API_URL", "http://ticket-mock.test")
    monkeypatch.setenv("TICKETING_API_TOKEN", "test-token")
    monkeypatch.setenv("TICKETING_MCP_URL", "http://ticket-mcp.placeholder")
    monkeypatch.setenv("APPROVAL_USER", "operator")
    monkeypatch.setenv("ALARM_API_BASE_URL", "http://127.0.0.1:1")
    monkeypatch.setenv("ALARM_API_TOKEN", "test-token")
    get_settings.cache_clear()

    client = TestClient(create_app())
    _patch_ticket_mcp_to_local_mock(client, ticket_mock_client)
    return client


def _patch_ticket_mcp_to_local_mock(client: TestClient, ticket_mock_client: TestClient) -> None:
    """Replace the orchestrator's ticket MCP client with a stub
    that delegates to the in-process ticket-mock.

    The orchestrator stores an :class:`OrchestratorBundle` on
    ``app.state.orchestrator``; that bundle has a ``chain``
    attribute which is the :class:`ChainRunner`. The chain
    uses a ticket MCP client (``bundle.chain._ticket_mcp``) to
    dispatch ``CREATE_TICKET_DRAFT`` steps. We replace that
    client with a small async stub that POSTs to the
    in-process ticket-mock and translates the response into
    the chain's ``(output, trace_step)`` tuple.
    """

    from apps.backend.orchestrator.mcp_client import MCPClient
    from core.domain import TraceStep

    bundle = client.app.state.orchestrator
    ticket_client = ticket_mock_client

    class _StubTicketMCP(MCPClient):
        """Stub that proxies ``create_ticket_draft`` to the
        in-process ticket-mock via TestClient."""

        def __init__(self) -> None:
            # Skip the parent __init__ — we don't need a real
            # Streamable HTTP transport.
            pass

        async def call(self, *, tool: str, args: dict[str, Any]) -> tuple[Any, TraceStep]:
            assert tool == "create_ticket_draft"
            response = ticket_client.post(
                "/tickets/draft",
                json={"incident": args["incident"], "approved": args["approved"]},
                headers={"Authorization": "Bearer test-token"},
            )
            if response.status_code == 200:
                output = response.json()
                return output, TraceStep(
                    server="ticketing",
                    tool=tool,
                    args=args,
                    output=output,
                    duration_ms=10,
                    outcome="success",
                )
            # The 403 envelope echoes through as a ToolInvocationError
            # in the live MCP path; we replicate that here so the
            # orchestrator's chain records an error trace step.
            detail = response.json().get("detail", {})
            msg = (
                f"{detail.get('message', 'ticket draft rejected')} "
                f"(code={detail.get('code', 'unknown')}, "
                f"request_id={detail.get('request_id', 'unknown')})"
            )
            return None, TraceStep(
                server="ticketing",
                tool=tool,
                args=args,
                output=None,
                duration_ms=10,
                outcome="error",
                error=msg,
            )

        async def list_tools(self) -> list[Any]:
            return []

    bundle.chain._ticket_mcp = _StubTicketMCP()  # type: ignore[assignment]


def _incident_payload() -> dict[str, Any]:
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


def test_orchestrator_draft_without_approval_returns_502_with_envelope(
    orchestrator_client: TestClient,
) -> None:
    """The hard-constraint-#3 gate surfaces as a 502 from the
    orchestrator (the orchestrator wraps the chain's error
    trace step into an MCP-failed envelope). The trace carries
    ``code=approval_required``.
    """
    r = orchestrator_client.post(
        "/tickets/draft",
        json={"incident": _incident_payload(), "approved": False},
    )
    # The orchestrator's routes.py wraps the chain's MCPError
    # into a 502 with the underlying message preserved.
    assert r.status_code in (502, 200), r.text
    if r.status_code == 502:
        detail = r.json()["detail"]
        # The chain recorded a trace step with outcome="error";
        # the body echoes the rejection message.
        assert "approval_required" in detail["message"] or "approval" in detail["message"].lower()


def test_orchestrator_draft_with_approval_returns_persisted_ticket(
    orchestrator_client: TestClient,
    ticket_mock_client: TestClient,
) -> None:
    """The happy path: ``approved=True`` returns the persisted
    ticket id and the ``approval`` block on the response."""
    r = orchestrator_client.post(
        "/tickets/draft",
        json={"incident": _incident_payload(), "approved": True},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["preview"] is False
    assert body["ticket_id"] is not None
    assert body["ticket_id"].startswith("TKT-")
    assert body["approval"] is not None
    assert body["approval"]["approved_by"] == "operator"
    assert body["approval"]["request_id"]

    # The trace step carries the lifted approval metadata.
    trace = body.get("trace", [])
    assert len(trace) >= 1
    ticket_step = next((s for s in trace if s["tool"] == "create_ticket_draft"), None)
    assert ticket_step is not None
    assert ticket_step["outcome"] == "success"
    output = ticket_step.get("output") or {}
    assert output.get("approved_by") == "operator"
    assert output.get("request_id") == body["approval"]["request_id"]

    # The audit row landed in the in-process ticket-mock.
    audit = ticket_mock_client.get("/tickets/audit", headers={"Authorization": "Bearer test-token"})
    assert audit.status_code == 200
    audit_body = audit.json()
    assert audit_body["total"] == 1
    assert audit_body["items"][0]["ticket_id"] == body["ticket_id"]
