"""Integration tests for the ticket-mock endpoints (Feature 6.2).

These run in-process via FastAPI's TestClient — no Docker,
no Newman. They exercise:

* ``POST /tickets/draft`` — the approval gate (403 when
  ``approved=False``) and the success path (200 + audit row).
* ``GET /tickets/audit`` — the audit list endpoint.

The MCP-server-level tests for the ``create_ticket_draft``
tool's ``is_error`` mapping live in
``tests/integration/mcp_server_ticketing/test_tools.py``.
The orchestrator-level end-to-end tests live in
``tests/integration/test_orchestrator_ticket_e2e.py``.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from connectors.ticket_mock.app import create_app
from core.config import get_settings


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("TICKETING_API_TOKEN", "test-token")
    monkeypatch.setenv("APPROVAL_USER", "operator")
    get_settings.cache_clear()
    return TestClient(create_app())


@pytest.fixture
def auth_headers() -> dict[str, str]:
    return {"Authorization": "Bearer test-token"}


@pytest.fixture
def incident_payload() -> dict[str, object]:
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


# ---- POST /tickets/draft — Feature 6.2 approval gate ----


def _wrap(incident: dict, *, approved: bool) -> dict:
    """Build the wire body for ``POST /tickets/draft`` — the
    schema is ``{incident: {...}, approved: bool}``."""
    return {"incident": incident, "approved": approved}


def test_draft_without_approval_returns_403(client: TestClient, auth_headers: dict[str, str], incident_payload: dict) -> None:
    """Hard constraint #3 — without explicit user confirmation,
    the service rejects the write with a 403 ``approval_required``
    envelope. No ticket is persisted; no audit row is appended."""
    r = client.post("/tickets/draft", json=_wrap(incident_payload, approved=False), headers=auth_headers)
    assert r.status_code == 403
    body = r.json()["detail"]
    assert body["code"] == "approval_required"
    assert body["requires_approval"] is True
    assert body["message"]
    assert body["request_id"]


def test_draft_without_approval_field_also_returns_403(client: TestClient, auth_headers: dict[str, str], incident_payload: dict) -> None:
    """Omitting the ``approved`` field defaults to ``False``;
    the service still rejects with the 403 envelope."""
    r = client.post("/tickets/draft", json={"incident": incident_payload}, headers=auth_headers)
    assert r.status_code == 403
    body = r.json()["detail"]
    assert body["code"] == "approval_required"


def test_draft_with_approval_returns_200_and_audit_row(
    client: TestClient,
    auth_headers: dict[str, str],
    incident_payload: dict,
) -> None:
    """The happy path: with ``approved=True`` the service
    persists the ticket, appends an audit row, and returns
    the assigned ``ticket_id`` plus the ``approval`` block."""
    r = client.post(
        "/tickets/draft",
        json=_wrap(incident_payload, approved=True),
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["preview"] is False
    assert body["ticket_id"] is not None
    assert body["ticket_id"].startswith("TKT-")
    assert body["approval"] is not None
    assert body["approval"]["approved_by"] == "operator"
    assert body["approval"]["approved_at"]
    assert body["approval"]["request_id"]

    # The audit row is visible via GET /tickets/audit.
    audit = client.get("/tickets/audit", headers=auth_headers)
    assert audit.status_code == 200
    audit_body = audit.json()
    assert audit_body["total"] == 1
    assert audit_body["items"][0]["ticket_id"] == body["ticket_id"]
    assert audit_body["items"][0]["approved_by"] == "operator"
    assert audit_body["items"][0]["request_id"] == body["approval"]["request_id"]
    assert audit_body["items"][0]["incident_id"] == "INC-9001"
    assert audit_body["items"][0]["action"] == "create_ticket"


def test_draft_with_approval_uses_settings_approval_user(
    client: TestClient,
    auth_headers: dict[str, str],
    incident_payload: dict,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The ``approved_by`` audit field honours the
    ``APPROVAL_USER`` env var (Feature 6.2 audit-trail
    attribution)."""
    monkeypatch.setenv("APPROVAL_USER", "supervisor-7")
    get_settings.cache_clear()
    r = client.post(
        "/tickets/draft",
        json=_wrap(incident_payload, approved=True),
        headers=auth_headers,
    )
    assert r.status_code == 200
    body = r.json()
    assert body["approval"]["approved_by"] == "supervisor-7"


def test_draft_without_approval_does_not_persist_ticket(
    client: TestClient,
    auth_headers: dict[str, str],
    incident_payload: dict,
) -> None:
    """The 403 path is fail-closed — no ticket is persisted,
    no audit row is appended."""
    r = client.post("/tickets/draft", json=_wrap(incident_payload, approved=False), headers=auth_headers)
    assert r.status_code == 403
    # The audit list is empty.
    audit = client.get("/tickets/audit", headers=auth_headers)
    assert audit.json()["total"] == 0


def test_draft_with_approval_increments_audit_list(
    client: TestClient,
    auth_headers: dict[str, str],
    incident_payload: dict,
) -> None:
    """Two approved writes produce two audit rows in insertion
    order. The audit list is FIFO; the limit param bounds the
    returned window."""
    r1 = client.post(
        "/tickets/draft",
        json=_wrap({**incident_payload, "id": "INC-A"}, approved=True),
        headers=auth_headers,
    )
    r2 = client.post(
        "/tickets/draft",
        json=_wrap({**incident_payload, "id": "INC-B"}, approved=True),
        headers=auth_headers,
    )
    assert r1.status_code == 200
    assert r2.status_code == 200
    assert r1.json()["ticket_id"] != r2.json()["ticket_id"]

    audit = client.get("/tickets/audit", headers=auth_headers)
    body = audit.json()
    assert body["total"] == 2
    assert body["items"][0]["incident_id"] == "INC-A"
    assert body["items"][1]["incident_id"] == "INC-B"


# ---- GET /tickets/audit ----


def test_audit_requires_auth(client: TestClient) -> None:
    """The audit endpoint inherits the router's bearer-token
    dependency; no token → 401."""
    r = client.get("/tickets/audit")
    assert r.status_code == 401


def test_audit_with_token_returns_empty_when_no_writes(
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    """A freshly booted service has an empty audit list."""
    r = client.get("/tickets/audit", headers=auth_headers)
    assert r.status_code == 200
    body = r.json()
    assert body == {"items": [], "total": 0}


def test_audit_limit_bounds_returned_window(
    client: TestClient,
    auth_headers: dict[str, str],
    incident_payload: dict,
) -> None:
    """The ``limit`` query parameter bounds the returned
    audit rows. ``total`` still reflects the full count."""
    for i in range(5):
        client.post(
            "/tickets/draft",
            json=_wrap({**incident_payload, "id": f"INC-{i}"}, approved=True),
            headers=auth_headers,
        )
    audit = client.get("/tickets/audit?limit=2", headers=auth_headers)
    body = audit.json()
    assert body["total"] == 5
    assert len(body["items"]) == 2


def test_audit_limit_rejects_zero(
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    """``limit`` has a ``ge=1`` constraint; 0 is rejected."""
    r = client.get("/tickets/audit?limit=0", headers=auth_headers)
    assert r.status_code == 422


def test_audit_limit_rejects_above_max(
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    """``limit`` has a ``le=200`` constraint; 201 is rejected."""
    r = client.get("/tickets/audit?limit=201", headers=auth_headers)
    assert r.status_code == 422
