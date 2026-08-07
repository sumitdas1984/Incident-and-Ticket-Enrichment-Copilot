"""Health and readiness tests for the alarm-management MCP server.

Each test builds its own `MCPServer` (with its own
`StreamableHTTPSessionManager`) and wraps it with the production
`MCPServerLifespan`, so a fresh session manager is available per
test. Sharing one across tests trips the SDK's one-shot guard on
`session_manager.run()`.
"""
from __future__ import annotations

import pytest
from mcp_servers.alarm_management.health import register_health_routes
from mcp_servers.alarm_management.lifespan import make_asgi_app
from starlette.testclient import TestClient


def _build_app() -> TestClient:
    """Build a fresh MCP server + ASGI app + test client."""
    from mcp.server.mcpserver import MCPServer

    server = MCPServer(name="test-server", instructions="Alarm Management MCP server.")
    register_health_routes(server, version="test")
    return TestClient(make_asgi_app(server))


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    """Yield a Starlette TestClient pointed at an unreachable alarm-api.

    The MCP app's readiness probe talks to the alarm-api; we point
    it at an unreachable host so the probe deterministically
    reports ``not_ready`` without flaking on whatever happens to
    be on the network.
    """
    monkeypatch.setenv("ALARM_API_BASE_URL", "http://127.0.0.1:1")
    monkeypatch.setenv("ALARM_API_TOKEN", "test-token")
    from core.config import get_settings

    get_settings.cache_clear()
    try:
        return _build_app()
    finally:
        get_settings.cache_clear()


def test_health_is_unauthenticated_200(monkeypatch: pytest.MonkeyPatch) -> None:
    """Liveness is a free 200. Docker-compose polls this."""
    monkeypatch.setenv("ALARM_API_BASE_URL", "http://127.0.0.1:1")
    monkeypatch.setenv("ALARM_API_TOKEN", "test-token")
    from core.config import get_settings

    get_settings.cache_clear()
    try:
        with _build_app() as c:
            r = c.get("/health")
            assert r.status_code == 200
            body = r.json()
            assert body["status"] == "ok"
            assert body["service"] == "alarm-management-mcp"
            assert "version" in body
    finally:
        get_settings.cache_clear()


def test_ready_returns_503_when_alarm_api_unreachable(monkeypatch: pytest.MonkeyPatch) -> None:
    """Readiness flips to 503 when the alarm-api dependency is down."""
    monkeypatch.setenv("ALARM_API_BASE_URL", "http://127.0.0.1:1")
    monkeypatch.setenv("ALARM_API_TOKEN", "test-token")
    from core.config import get_settings

    get_settings.cache_clear()
    try:
        with _build_app() as c:
            r = c.get("/ready")
            assert r.status_code == 503
            body = r.json()
            assert body["status"] == "not_ready"
            assert body["alarm_api"] == "unreachable"
    finally:
        get_settings.cache_clear()


def test_ready_returns_200_when_alarm_api_reachable(monkeypatch: pytest.MonkeyPatch) -> None:
    """Readiness returns 200 when the alarm-api `/health` is reachable.

    Patches `httpx.get` so we don't need a real alarm-api process.
    """
    monkeypatch.setenv("ALARM_API_BASE_URL", "http://alarm-api-test")
    monkeypatch.setenv("ALARM_API_TOKEN", "test-token")
    from core.config import get_settings

    get_settings.cache_clear()

    class FakeResponse:
        status_code = 200

    def fake_get(*_args: object, **_kwargs: object) -> FakeResponse:
        return FakeResponse()

    monkeypatch.setattr("mcp_servers.alarm_management.health.httpx.get", fake_get)

    try:
        with _build_app() as c:
            r = c.get("/ready")
            assert r.status_code == 200
            body = r.json()
            assert body == {"status": "ready", "alarm_api": "reachable"}
    finally:
        get_settings.cache_clear()


def test_health_and_ready_never_leak_secrets(monkeypatch: pytest.MonkeyPatch) -> None:
    """Neither probe surfaces the alarm-api token in the response body."""
    monkeypatch.setenv("ALARM_API_BASE_URL", "http://127.0.0.1:1")
    monkeypatch.setenv("ALARM_API_TOKEN", "test-token")
    from core.config import get_settings

    get_settings.cache_clear()
    try:
        with _build_app() as c:
            health = c.get("/health").json()
            ready = c.get("/ready").json()
            for body in (health, ready):
                assert "test-token" not in str(body)
                assert "Bearer" not in str(body)
    finally:
        get_settings.cache_clear()
