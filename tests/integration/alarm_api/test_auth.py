"""Auth tests: /health is open, every other endpoint requires a valid bearer."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from connectors.alarm_api.app import create_app
from core.config import get_settings


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("ALARM_API_TOKEN", "test-token")
    get_settings.cache_clear()
    return TestClient(create_app())


# Endpoints we know about; the only open one is /health. Anything else
# must 401.
ALL_ENDPOINTS = [
    ("GET",  "/assets/search"),
    ("GET",  "/assets/asset-bfp-101/metadata"),
    ("GET",  "/alarms"),
    ("GET",  "/alarms/alarm-bfp-101-001"),
    ("GET",  "/analytics/kpi-definitions"),
    ("POST", "/alarms/summary"),
    ("POST", "/alarms/trends"),
    ("POST", "/alarms/correlation"),
    ("POST", "/alarms/flood-analysis"),
    ("POST", "/alarms/rationalization-candidates"),
    ("POST", "/alarms/priority-score"),
    ("POST", "/recommendations/operator-actions"),
    ("POST", "/calculation-code/generate"),
    ("POST", "/calculation-code/execute"),
]


def test_health_no_auth(client: TestClient) -> None:
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


@pytest.mark.parametrize("method,path", ALL_ENDPOINTS)
def test_endpoint_without_auth_returns_401(client: TestClient, method: str, path: str) -> None:
    if method == "GET":
        r = client.get(path)
    else:
        r = client.post(path, json={})
    assert r.status_code == 401, f"{method} {path} should 401 without auth"
    body = r.json()
    assert body["detail"]["code"] == "unauthorized"
    assert "trace_id" in body["detail"] or "trace_id" in r.headers


@pytest.mark.parametrize("method,path", [
    ("GET",  "/assets/search"),
    ("GET",  "/alarms"),
])
def test_endpoint_with_wrong_token_returns_401(client: TestClient, method: str, path: str) -> None:
    headers = {"Authorization": "Bearer wrong-token"}
    if method == "GET":
        r = client.get(path, headers=headers)
    else:
        r = client.post(path, json={}, headers=headers)
    assert r.status_code == 401


@pytest.mark.parametrize("method,path", [
    ("GET",  "/assets/search"),
    ("GET",  "/alarms"),
])
def test_endpoint_with_malformed_auth_header_returns_401(
    client: TestClient, method: str, path: str
) -> None:
    headers = {"Authorization": "NotBearer xyz"}
    if method == "GET":
        r = client.get(path, headers=headers)
    else:
        r = client.post(path, json={}, headers=headers)
    assert r.status_code == 401


def test_health_endpoint_with_auth_header_still_works(client: TestClient) -> None:
    r = client.get("/health", headers={"Authorization": "Bearer test-token"})
    assert r.status_code == 200
