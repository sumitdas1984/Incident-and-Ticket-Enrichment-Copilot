"""End-to-end tests for every alarm-api endpoint via FastAPI TestClient.

These run against the in-process app (no Docker, no Newman) and
exercise auth, trace propagation, and the documented JSON shape
for every endpoint defined in the Postman collection.
"""
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


# ---- /health ----


def test_health_no_auth(client: TestClient) -> None:
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["service"] == "alarm-api"


# ---- /assets/search ----


def test_search_assets_requires_auth(client: TestClient) -> None:
    assert client.get("/assets/search?query=Boiler").status_code == 401


def test_search_assets_with_token(client: TestClient, auth_headers: dict[str, str]) -> None:
    r = client.get("/assets/search?query=Boiler", headers=auth_headers)
    assert r.status_code == 200
    body = r.json()
    assert body["total"] >= 1
    ids = [a["asset_id"] for a in body["results"]]
    assert "asset-bfp-101" in ids


def test_search_assets_empty_query_400(client: TestClient, auth_headers: dict[str, str]) -> None:
    r = client.get("/assets/search", headers=auth_headers)
    assert r.status_code == 422


# ---- /assets/{id}/metadata ----


def test_asset_metadata_found(client: TestClient, auth_headers: dict[str, str]) -> None:
    r = client.get("/assets/asset-bfp-101/metadata", headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["asset"]["asset_id"] == "asset-bfp-101"


def test_asset_metadata_not_found(client: TestClient, auth_headers: dict[str, str]) -> None:
    r = client.get("/assets/asset-bogus/metadata", headers=auth_headers)
    assert r.status_code == 404
    body = r.json()
    assert body["code"] == "not_found"
    assert body["details"]["asset_id"] == "asset-bogus"
    assert "trace_id" in body


# ---- /alarms ----


def test_list_alarms_with_paging(client: TestClient, auth_headers: dict[str, str]) -> None:
    r = client.get("/alarms?page=1&page_size=10&sort_by=raised_at&sort_order=desc", headers=auth_headers)
    assert r.status_code == 200
    body = r.json()
    assert body["page"] == 1
    assert body["page_size"] == 10
    assert body["total"] >= 1
    assert len(body["data"]) >= 1


def test_list_alarms_filter_by_asset(client: TestClient, auth_headers: dict[str, str]) -> None:
    r = client.get("/alarms?asset_id=asset-bfp-101", headers=auth_headers)
    assert r.status_code == 200
    rows = r.json()["data"]
    assert all(a["asset_id"] == "asset-bfp-101" for a in rows)
    assert len(rows) >= 1


def test_list_alarms_filter_by_status_active(client: TestClient, auth_headers: dict[str, str]) -> None:
    r = client.get("/alarms?status=active", headers=auth_headers)
    assert r.status_code == 200
    rows = r.json()["data"]
    assert all(a["acknowledged"] is False for a in rows)


# ---- /alarms/{id} ----


def test_get_alarm_by_id(client: TestClient, auth_headers: dict[str, str]) -> None:
    r = client.get("/alarms/alarm-bfp-101-001", headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["alarm_id"] == "alarm-bfp-101-001"


def test_get_alarm_404_envelope(client: TestClient, auth_headers: dict[str, str]) -> None:
    r = client.get("/alarms/alarm-bogus", headers=auth_headers)
    assert r.status_code == 404
    body = r.json()
    assert body["code"] == "not_found"
    assert body["details"]["alarm_id"] == "alarm-bogus"


def test_get_alarm_trace_echoed(client: TestClient, auth_headers: dict[str, str]) -> None:
    r = client.get(
        "/alarms/alarm-bfp-101-001",
        headers={**auth_headers, "trace_id": "trace-test-123"},
    )
    assert r.status_code == 200
    # Trace echoed in response header (errors.py envelope reads it).
    assert r.headers.get("trace_id") == "trace-test-123"


# ---- /alarms/summary ----


def test_alarm_summary_uses_seed_data(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    r = client.post(
        "/alarms/summary",
        json={
            "asset_ids": ["asset-bfp-101"],
            "time_range": {
                "start_time": "2026-05-01T00:00:00Z",
                "end_time": "2026-07-01T00:00:00Z",
            },
            "kpis": ["alarm_count"],
        },
        headers=auth_headers,
    )
    assert r.status_code == 200
    body = r.json()
    assert "groups" in body
    assert body["total"] >= 1


# ---- /alarms/trends ----


def test_alarm_trends_daily_buckets(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    r = client.post(
        "/alarms/trends",
        json={
            "time_range": {
                "start_time": "2026-05-01T00:00:00Z",
                "end_time": "2026-07-01T00:00:00Z",
            },
            "bucket": "daily",
            "metrics": ["alarm_count"],
        },
        headers=auth_headers,
    )
    assert r.status_code == 200
    assert "buckets" in r.json()


# ---- /alarms/correlation ----


def test_alarm_correlation_returns_pairs(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    r = client.post(
        "/alarms/correlation",
        json={
            "asset_ids": ["asset-bfp-101", "asset-bfp-201"],
            "time_range": {
                "start_time": "2026-05-01T00:00:00Z",
                "end_time": "2026-07-01T00:00:00Z",
            },
            "correlation_method": "cooccurrence",
            "min_support": 1,
        },
        headers=auth_headers,
    )
    assert r.status_code == 200
    body = r.json()
    assert "pairs" in body
    assert body["method"] == "cooccurrence"


# ---- /alarms/flood-analysis ----


def test_flood_analysis_unit(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    r = client.post(
        "/alarms/flood-analysis",
        json={
            "unit": "Unit 1",
            "time_range": {
                "start_time": "2026-05-01T00:00:00Z",
                "end_time": "2026-07-01T00:00:00Z",
            },
            "threshold_count": 1,
            "rolling_window_minutes": 10,
        },
        headers=auth_headers,
    )
    assert r.status_code == 200
    body = r.json()
    assert body["unit"] == "Unit 1"
    assert "flood_windows" in body


# ---- /alarms/rationalization-candidates ----


def test_rationalization_candidates(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    r = client.post(
        "/alarms/rationalization-candidates",
        json={
            "asset_ids": ["asset-bfp-101"],
            "time_range": {
                "start_time": "2026-05-01T00:00:00Z",
                "end_time": "2026-07-01T00:00:00Z",
            },
            "recurrence_threshold": 1,
            "stale_minutes_threshold": 180,
        },
        headers=auth_headers,
    )
    assert r.status_code == 200
    assert "candidates" in r.json()


# ---- /alarms/priority-score ----


def test_priority_score_known_alarm(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    r = client.post(
        "/alarms/priority-score",
        json={"alarm_id": "alarm-bfp-101-001"},
        headers=auth_headers,
    )
    assert r.status_code == 200
    body = r.json()
    assert body["alarm_id"] == "alarm-bfp-101-001"
    assert body["priority_score"] == 100  # CRITICAL


def test_priority_score_unknown_alarm_404(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    r = client.post(
        "/alarms/priority-score",
        json={"alarm_id": "alarm-bogus"},
        headers=auth_headers,
    )
    assert r.status_code == 404
    assert r.json()["code"] == "not_found"


# ---- /recommendations/operator-actions ----


def test_recommendation_for_critical(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    r = client.post(
        "/recommendations/operator-actions",
        json={"alarm_id": "alarm-bfp-101-001"},
        headers=auth_headers,
    )
    assert r.status_code == 200
    body = r.json()
    assert body["alarm_id"] == "alarm-bfp-101-001"
    assert body["priority_score"] == 100
    assert len(body["actions"]) >= 1


# ---- /calculation-code ----


def test_calculation_generate_then_execute(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    gen = client.post(
        "/calculation-code/generate",
        json={
            "calculation_type": "alarm_flood_index",
            "filters": {"unit": "Unit 1"},
        },
        headers=auth_headers,
    )
    assert gen.status_code == 200
    cid = gen.json()["calculation_id"]

    exe = client.post(
        "/calculation-code/execute",
        json={"calculation_id": cid, "filters": {"unit": "Unit 1"}},
        headers=auth_headers,
    )
    assert exe.status_code == 200
    body = exe.json()
    assert body["calculation_id"] == cid
    assert "result" in body


def test_calculation_execute_unknown_404(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    r = client.post(
        "/calculation-code/execute",
        json={"calculation_id": "calc-bogus", "filters": {}},
        headers=auth_headers,
    )
    assert r.status_code == 404
    assert r.json()["code"] == "not_found"


# ---- /analytics/kpi-definitions ----


def test_kpi_definitions(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    r = client.get("/analytics/kpi-definitions", headers=auth_headers)
    assert r.status_code == 200
    body = r.json()
    assert "kpis" in body
    kpi_names = {k["kpi"] for k in body["kpis"]}
    assert "alarm_count" in kpi_names
