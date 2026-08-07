"""Integration tests for the alarm-api ``/tickets/similar`` endpoint (Feature 5.2.1)."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from connectors.alarm_api.app import create_app


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("ALARM_API_TOKEN", "test-token")
    from core.config import get_settings

    get_settings.cache_clear()
    app = create_app()
    return TestClient(app, headers={"Authorization": "Bearer test-token"})


def test_tickets_similar_returns_seeded_list_sorted_by_similarity(client: TestClient) -> None:
    r = client.get("/tickets/similar", params={"text": "boiler tube leak"})
    assert r.status_code == 200
    body = r.json()
    items = body["items"]
    assert len(items) >= 1
    # Items are sorted by similarity descending.
    for prev, curr in zip(items, items[1:], strict=False):
        assert prev["similarity"] >= curr["similarity"]


def test_tickets_similar_filter_by_asset_class(client: TestClient) -> None:
    r = client.get(
        "/tickets/similar",
        params={"text": "x", "asset_class": "boiler"},
    )
    assert r.status_code == 200
    items = r.json()["items"]
    assert all(item["asset_class"] == "boiler" for item in items)
    assert len(items) >= 1


def test_tickets_similar_filter_by_site(client: TestClient) -> None:
    r = client.get(
        "/tickets/similar",
        params={"text": "x", "site": "EastRefinery"},
    )
    assert r.status_code == 200
    items = r.json()["items"]
    assert all(item["site"] == "EastRefinery" for item in items)


def test_tickets_similar_respects_limit(client: TestClient) -> None:
    r = client.get("/tickets/similar", params={"text": "x", "limit": 2})
    assert r.status_code == 200
    items = r.json()["items"]
    assert len(items) == 2


def test_tickets_similar_requires_text(client: TestClient) -> None:
    r = client.get("/tickets/similar")
    # FastAPI's query validation returns 422 for missing required query.
    assert r.status_code == 422


def test_tickets_similar_requires_bearer(client: TestClient) -> None:
    """The endpoint is behind the bearer auth dependency."""
    # Build a fresh client without the bearer header.
    from core.config import get_settings

    get_settings.cache_clear()
    app = create_app()
    public = TestClient(app)
    r = public.get("/tickets/similar", params={"text": "x"})
    assert r.status_code == 401


def test_tickets_similar_response_shape_matches_model(client: TestClient) -> None:
    """Every ticket has the expected fields."""
    r = client.get("/tickets/similar", params={"text": "x"})
    assert r.status_code == 200
    for item in r.json()["items"]:
        assert "id" in item
        assert "title" in item
        assert "status" in item
        assert "similarity" in item
        assert "resolution_excerpt" in item
        assert 0.0 <= item["similarity"] <= 1.0
        assert item["status"] in {"open", "in_progress", "resolved", "closed"}
