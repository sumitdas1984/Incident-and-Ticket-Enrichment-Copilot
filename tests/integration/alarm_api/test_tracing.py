"""Trace propagation tests: trace_id round-trips on every response."""
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


@pytest.fixture
def auth_headers() -> dict[str, str]:
    return {"Authorization": "Bearer test-token"}


def test_trace_header_echoed_on_health(client: TestClient) -> None:
    """Even /health (open endpoint) echoes the request's trace_id back."""
    r = client.get("/health", headers={"trace_id": "trace-no-auth"})
    assert r.status_code == 200
    assert r.headers.get("trace_id") == "trace-no-auth"


def test_trace_header_echoed_on_authenticated_get(client: TestClient, auth_headers: dict[str, str]) -> None:
    r = client.get("/alarms/alarm-bfp-101-001", headers={**auth_headers, "trace_id": "trace-get"})
    assert r.status_code == 200
    assert r.headers.get("trace_id") == "trace-get"


def test_trace_header_echoed_on_authenticated_post(client: TestClient, auth_headers: dict[str, str]) -> None:
    r = client.post(
        "/alarms/priority-score",
        json={"alarm_id": "alarm-bfp-101-001"},
        headers={**auth_headers, "trace_id": "trace-post"},
    )
    assert r.status_code == 200
    assert r.headers.get("trace_id") == "trace-post"


def test_trace_header_echoed_on_error_response(client: TestClient, auth_headers: dict[str, str]) -> None:
    r = client.get(
        "/alarms/alarm-bogus",
        headers={**auth_headers, "trace_id": "trace-err"},
    )
    assert r.status_code == 404
    assert r.headers.get("trace_id") == "trace-err"
    body = r.json()
    assert body["code"] == "not_found"
    assert body["trace_id"] == "trace-err"


def test_trace_header_echoed_on_validation_error(client: TestClient, auth_headers: dict[str, str]) -> None:
    r = client.post(
        "/alarms/priority-score",
        json={},  # missing required alarm_id
        headers={**auth_headers, "trace_id": "trace-422"},
    )
    assert r.status_code == 422
    assert r.headers.get("trace_id") == "trace-422"
    body = r.json()
    assert body["code"] == "bad_request"
    assert body["trace_id"] == "trace-422"


def test_trace_header_generated_when_absent(client: TestClient, auth_headers: dict[str, str]) -> None:
    """If the request doesn't supply a trace_id, the server generates one
    and echoes it back so the client can correlate logs."""
    r = client.get("/alarms/alarm-bfp-101-001", headers=auth_headers)
    assert r.status_code == 200
    trace = r.headers.get("trace_id")
    assert trace is not None
    # UUID-shaped (new_id() default).
    import uuid

    uuid.UUID(trace)


def test_trace_header_propagates_through_chain(client: TestClient, auth_headers: dict[str, str]) -> None:
    """The same trace_id is seen on every endpoint in a Postman-style chain."""
    trace = "trace-chain-xyz"
    headers = {**auth_headers, "trace_id": trace}

    r1 = client.get("/assets/search?query=Boiler", headers=headers)
    r2 = client.get("/alarms?asset_id=asset-bfp-101", headers=headers)
    r3 = client.post(
        "/alarms/priority-score",
        json={"alarm_id": "alarm-bfp-101-001"},
        headers=headers,
    )
    assert r1.headers["trace_id"] == trace
    assert r2.headers["trace_id"] == trace
    assert r3.headers["trace_id"] == trace
