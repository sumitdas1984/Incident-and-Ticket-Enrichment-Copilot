"""Integration tests for ``POST /tickets/preview``.

Feature 7.2 (PR 1) — the GUI's confirmation modal pre-populates the
editable draft form by calling this endpoint before the operator
clicks Approve. No ticket is persisted on this path.

We mount the orchestrator's router on a minimal FastAPI app so
the test exercises the real route handler without booting the
orchestrator's MCP / RAG wiring (which needs the persisted RAG
index). That keeps the test hermetic and fast.
"""
from __future__ import annotations

from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from apps.backend.routes import router as orchestrator_router


@pytest.fixture
def preview_client() -> TestClient:
    """A minimal FastAPI app with only the orchestrator's router
    mounted — no orchestrator bundle, no MCP clients, no RAG
    index. The ``/tickets/preview`` route does not depend on any
    of those, so this exercises the route handler in isolation.

    ``raise_server_exceptions=False`` so the regression test on
    ``/tickets/draft`` (which raises an ``AttributeError`` because
    the orchestrator bundle isn't wired here) sees a 500 instead
    of the raw exception bubbling out.
    """
    app = FastAPI(title="preview-test-app")
    app.include_router(orchestrator_router)
    return TestClient(app, raise_server_exceptions=False)


def _incident_payload(**overrides: Any) -> dict[str, Any]:
    """A representative incident payload. Mirrors the shape the
    GUI receives in ``ChatResponse.incident``."""
    base: dict[str, Any] = {
        "id": "INC-9001",
        "title": "Boiler B-101 tube leak suspect",
        "summary": "Recurring high-temp alarms; inspect tube sheet.",
        "severity": "critical",
        "likely_cause": "Tube sheet leak",
        "recommended_actions": [
            "Reduce feed rate to 80%",
            "Inspect lower tube sheet",
            "Open ticket with maintenance",
        ],
        "similar_tickets": ["TKT-1042", "TKT-1107"],
        "asset_id": "asset-boiler-b-101",
        "site": "EastRefinery",
    }
    base.update(overrides)
    return base


def test_preview_returns_200_with_draft_envelope(preview_client: TestClient) -> None:
    """Happy path: a representative incident returns a 200 with
    the projected draft."""
    response = preview_client.post(
        "/tickets/preview",
        json={"incident": _incident_payload()},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["title"] == "Boiler B-101 tube leak suspect"
    assert "Recurring high-temp alarms" in body["body"]
    assert body["severity"] == "critical"
    assert body["assignee"] is None
    # Labels include severity + related ids.
    assert "severity:critical" in body["labels"]
    assert "related:TKT-1042" in body["labels"]
    assert "related:TKT-1107" in body["labels"]
    assert body["incident_id"] == "INC-9001"


def test_preview_body_includes_recommended_actions(preview_client: TestClient) -> None:
    """The body is summary + a numbered list of recommended actions
    (matches ``connectors.ticket_mock.draft.build_draft()``)."""
    response = preview_client.post(
        "/tickets/preview",
        json={"incident": _incident_payload()},
    )
    body = response.json()["body"]
    # Actions appear numbered, in order.
    assert "1. Reduce feed rate to 80%" in body
    assert "2. Inspect lower tube sheet" in body
    assert "3. Open ticket with maintenance" in body
    # The summary comes first.
    assert body.startswith("Recurring high-temp alarms")


def test_preview_severity_falls_back_to_medium_when_missing(
    preview_client: TestClient,
) -> None:
    """An incident with no severity yields ``severity='medium'`` —
    matches ``build_draft()``'s coercion default."""
    incident = _incident_payload()
    incident.pop("severity")
    response = preview_client.post("/tickets/preview", json={"incident": incident})
    assert response.status_code == 200
    assert response.json()["severity"] == "medium"


def test_preview_severity_invalid_falls_back_to_medium(
    preview_client: TestClient,
) -> None:
    """An incident with an unknown severity string falls back to
    ``medium`` rather than 400-ing — drafts should be forgiving."""
    response = preview_client.post(
        "/tickets/preview",
        json={"incident": _incident_payload(severity="urgent-RED")},
    )
    assert response.status_code == 200
    assert response.json()["severity"] == "medium"


def test_preview_no_recommended_actions_omits_numbered_list(
    preview_client: TestClient,
) -> None:
    """An incident without ``recommended_actions`` yields a body
    that is just the summary, no numbered list."""
    incident = _incident_payload()
    incident.pop("recommended_actions")
    response = preview_client.post("/tickets/preview", json={"incident": incident})
    body = response.json()["body"]
    assert body == "Recurring high-temp alarms; inspect tube sheet."


def test_preview_no_similar_tickets_omits_related_labels(
    preview_client: TestClient,
) -> None:
    """Without ``similar_tickets`` the labels carry only the
    severity band."""
    incident = _incident_payload()
    incident.pop("similar_tickets")
    response = preview_client.post("/tickets/preview", json={"incident": incident})
    labels = response.json()["labels"]
    assert labels == ["severity:critical"]


def test_preview_no_incident_id_returns_null(preview_client: TestClient) -> None:
    """``incident_id`` echoes ``incident['id']``; absent ids
    surface as ``None`` (not an error)."""
    incident = _incident_payload()
    incident.pop("id")
    response = preview_client.post("/tickets/preview", json={"incident": incident})
    assert response.status_code == 200
    assert response.json()["incident_id"] is None


def test_preview_rejects_extra_keys(preview_client: TestClient) -> None:
    """``extra='forbid'`` on the request envelope means an unknown
    field 422s the request — same posture as ``TicketDraftRequest``."""
    response = preview_client.post(
        "/tickets/preview",
        json={"incident": _incident_payload(), "approved": True},  # approved doesn't belong on preview
    )
    assert response.status_code == 422


def test_preview_rejects_missing_incident(preview_client: TestClient) -> None:
    """An empty body fails Pydantic validation, not silently
    return an empty draft."""
    response = preview_client.post("/tickets/preview", json={})
    assert response.status_code == 422


def test_preview_does_not_call_mcp(preview_client: TestClient) -> None:
    """The preview path is a pure projection — no MCP, no chain.
    We assert this indirectly: a successful response is returned
    with no orchestrator bundle attached to ``app.state``. (The
    orchestrator's ``/chat`` and ``/tickets/draft`` routes both
    read ``app.state.orchestrator``; if the preview route did the
    same, it would 500 on this minimal app.)"""
    response = preview_client.post(
        "/tickets/preview",
        json={"incident": _incident_payload()},
    )
    assert response.status_code == 200, response.text


def test_draft_endpoint_is_unchanged(preview_client: TestClient) -> None:
    """Regression: the existing ``/tickets/draft`` endpoint
    signature is unchanged. Without an orchestrator bundle it
    raises an ``AttributeError`` on ``request.app.state.orchestrator``,
    which FastAPI surfaces as a 500. We assert the route is
    registered but its behaviour is the pre-Feature-7.2 path."""
    response = preview_client.post(
        "/tickets/draft",
        json={"incident": _incident_payload(), "approved": False},
    )
    # 500 because the orchestrator bundle isn't wired in this
    # minimal app; the point is the route exists and doesn't
    # accidentally hit the preview path.
    assert response.status_code == 500
