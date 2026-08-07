"""Regression tests for the alarm-api seed data.

These tests guard the Postman chaining collection's data expectations,
specifically CHAIN-08 (Motor Correlation), which calls
`/assets/search?query=motor&unit=Unit%205` and asserts `r.length > 0`.

If a future developer trims SEED_ASSETS without checking the chaining
collection, these tests catch it.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from connectors.alarm_api.app import create_app
from connectors.alarm_api.seed import SEED_ASSETS
from core.config import get_settings


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("ALARM_API_TOKEN", "test-token")
    get_settings.cache_clear()
    return TestClient(create_app())


@pytest.fixture
def auth_headers() -> dict[str, str]:
    return {"Authorization": "Bearer test-token"}


def test_seed_has_three_motors_in_unit_5() -> None:
    """CHAIN-08 chains through three motor asset_ids. The seed must
    provide at least three motors in Unit 5 so that
    `pm.collectionVariables.set('asset_id_3', ...)` resolves a real id.
    """
    motors_in_unit_5 = [
        a
        for a in SEED_ASSETS
        if a.asset_class == "motor" and a.unit == "Unit 5"
    ]
    assert len(motors_in_unit_5) >= 3, (
        f"Expected >=3 motors in Unit 5 for CHAIN-08, got {len(motors_in_unit_5)}: "
        f"{[a.id for a in motors_in_unit_5]}"
    )


def test_seed_metadata_matches_top_level_unit() -> None:
    """The store's search_assets() filter reads `asset.metadata['unit']`,
    not `asset.unit`. If they drift apart the unit-filtered search
    silently returns 0 results. Keep them in lockstep.
    """
    for asset in SEED_ASSETS:
        if asset.unit is not None:
            assert asset.metadata.get("unit") == asset.unit, (
                f"Asset {asset.id} has unit={asset.unit!r} but "
                f"metadata['unit']={asset.metadata.get('unit')!r}"
            )


def test_search_motors_in_unit_5_returns_three(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    """End-to-end check that mirrors the Postman CHAIN-08 assertion."""
    r = client.get(
        "/assets/search",
        params={"query": "motor", "unit": "Unit 5", "limit": 5},
        headers=auth_headers,
    )
    assert r.status_code == 200
    body = r.json()
    assert len(body["results"]) == 3, (
        f"Expected 3 motor assets in Unit 5, got {len(body['results'])}: "
        f"{body['results']}"
    )
    for result in body["results"]:
        assert "motor" in result["name"].lower()
        assert result["unit"] == "Unit 5"
