"""Tool-handler tests for the four Alarm Management MCP tools.

Each test builds an isolated ``MCPServer`` (the SDK's
``StreamableHTTPSessionManager.run()`` is one-shot per instance)
and wires an ``AlarmApiClient`` backed by ``httpx.MockTransport``
so we don't reach the network. ``MockTransport`` records the
outgoing requests, which lets us assert that:

* the alarm-api bearer token made it to the request,
* the ``X-Trace-Id`` header was propagated,
* the ``GET`` / ``POST`` path and query string match the handler
  contract,
* the 4xx / 5xx envelope maps to ``AlarmNotFoundError`` /
  ``ToolInvocationError`` without leaking the token.

What we deliberately don't test here
------------------------------------

* The MCP-protocol framing (``initialize``, ``tools/list``,
  ``tools/call`` over Streamable HTTP). That's covered in
  ``test_tools_list.py`` and ``test_registration.py``.
* Retries / circuit breakers. Feature 3.3.
* Real alarm-api behaviour. The simulator has its own test
  suite under ``tests/integration/alarm_api/``.
"""
from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
from mcp.server.mcpserver import MCPServer
from mcp_servers.alarm_management import (
    AlarmApiClient,
    AlarmNotFoundError,
    ToolInvocationError,
    get_alarm_api_client,
    register_tools,
)
from pydantic import SecretStr

# --------------------------------------------------------------------------- #
# Fixtures.
# --------------------------------------------------------------------------- #


def _make_server_with_mock(
    handler: Callable[[httpx.Request], httpx.Response],
) -> tuple[MCPServer, list[httpx.Request]]:
    """Build a fresh MCPServer with a mock-transport AlarmApiClient.

    Returns ``(server, recorded_requests)``. The list is mutated
    by ``MockTransport``; the caller can inspect it after the test.
    """
    recorded: list[httpx.Request] = []

    def _recording(request: httpx.Request) -> httpx.Response:
        recorded.append(request)
        return handler(request)

    server = MCPServer(name="alarm-management", instructions="test")
    server.alarm_api_client = AlarmApiClient(
        base_url="http://alarm-api.test",
        token=SecretStr("test-token-do-not-leak"),
        client=httpx.AsyncClient(
            transport=httpx.MockTransport(_recording),
            base_url="http://alarm-api.test",
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


# --------------------------------------------------------------------------- #
# `search_assets` — Story 3.2.1
# --------------------------------------------------------------------------- #


def test_search_assets_happy_path() -> None:
    server, recorded = _make_server_with_mock(
        lambda req: httpx.Response(
            200,
            json={
                "results": [
                    {
                        "asset_id": "A-1",
                        "name": "Boiler 1",
                        "site": "EastRefinery",
                        "unit": "Cracker-1",
                        "asset_class": "boiler",
                        "metadata": {},
                    }
                ],
                "total": 1,
                "query": "Boiler",
            },
        )
    )

    result = _call(server, "search_assets", query="Boiler")

    assert result["total"] == 1
    assert result["results"][0]["name"] == "Boiler 1"
    assert len(recorded) == 1
    assert recorded[0].method == "GET"
    assert recorded[0].url.path == "/assets/search"
    # query string
    assert recorded[0].url.params["query"] == "Boiler"
    assert recorded[0].url.params["limit"] == "10"


def test_search_assets_forwards_site_unit_and_limit() -> None:
    server, recorded = _make_server_with_mock(
        lambda req: httpx.Response(200, json={"results": [], "total": 0, "query": req.url.params["query"]})
    )

    _call(server, "search_assets", query="Pump", site="WestSite", unit="Unit-3", limit=5)

    params = recorded[0].url.params
    assert params["site"] == "WestSite"
    assert params["unit"] == "Unit-3"
    assert params["limit"] == "5"


def test_search_assets_propagates_bearer_token_and_trace() -> None:
    server, recorded = _make_server_with_mock(
        lambda req: httpx.Response(200, json={"results": [], "total": 0, "query": "x"})
    )

    _call(server, "search_assets", query="x")

    headers = recorded[0].headers
    assert headers["authorization"] == "Bearer test-token-do-not-leak"
    # trace_id is bound by @register_tool via structlog contextvars;
    # in unit tests the closure's fallback ("mcp-no-trace") applies.
    assert "x-trace-id" in headers


def test_search_assets_rejects_empty_query() -> None:
    server, _ = _make_server_with_mock(lambda req: httpx.Response(200, json={}))

    # Pydantic raises ValidationError before the handler runs.
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        _call(server, "search_assets", query="")


def test_search_assets_clamps_limit() -> None:
    server, _ = _make_server_with_mock(lambda req: httpx.Response(200, json={}))

    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        _call(server, "search_assets", query="x", limit=0)
    with pytest.raises(ValidationError):
        _call(server, "search_assets", query="x", limit=10_000)


# --------------------------------------------------------------------------- #
# `get_alarm` — Story 3.2.2
# --------------------------------------------------------------------------- #


def test_get_alarm_happy_path() -> None:
    server, recorded = _make_server_with_mock(
        lambda req: httpx.Response(
            200,
            json={
                "alarm_id": "AL-100",
                "asset_id": "A-1",
                "severity": "high",
                "message": "Temperature high",
                "raised_at": "2026-08-01T12:00:00Z",
                "acknowledged": False,
            },
        )
    )

    result = _call(server, "get_alarm", alarm_id="AL-100")

    assert result["alarm_id"] == "AL-100"
    assert result["severity"] == "high"
    assert recorded[0].method == "GET"
    assert recorded[0].url.path == "/alarms/AL-100"


def test_get_alarm_404_becomes_alarm_not_found_error() -> None:
    server, _ = _make_server_with_mock(
        lambda req: httpx.Response(404, json={"code": "not_found", "message": "Alarm AL-999 not found"})
    )

    with pytest.raises(AlarmNotFoundError) as ei:
        _call(server, "get_alarm", alarm_id="AL-999")

    assert "AL-999" in str(ei.value)
    # The alarm-api token must never appear in the user-visible message.
    assert "test-token-do-not-leak" not in str(ei.value)


def test_get_alarm_5xx_becomes_tool_invocation_error() -> None:
    server, _ = _make_server_with_mock(
        lambda req: httpx.Response(503, json={"code": "unavailable", "message": "down"})
    )

    with pytest.raises(ToolInvocationError) as ei:
        _call(server, "get_alarm", alarm_id="AL-100")

    assert "503" in str(ei.value)
    assert "test-token-do-not-leak" not in str(ei.value)


def test_get_alarm_connect_error_maps_to_sanitised_envelope() -> None:
    """A transport-level failure surfaces a sanitised message."""
    server = MCPServer(name="alarm-management", instructions="test")
    server.alarm_api_client = AlarmApiClient(
        base_url="http://alarm-api.test",
        token=SecretStr("test-token-do-not-leak"),
        client=httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda req: (_ for _ in ()).throw(httpx.ConnectError("boom"))
            ),
            base_url="http://alarm-api.test",
        ),
    )
    register_tools(server)

    with pytest.raises(ToolInvocationError) as ei:
        _call(server, "get_alarm", alarm_id="AL-100")

    assert "Upstream" in str(ei.value)
    assert "test-token-do-not-leak" not in str(ei.value)


# --------------------------------------------------------------------------- #
# `summarize_alarms` — Story 3.2.3
# --------------------------------------------------------------------------- #


def test_summarize_alarms_happy_path_with_filters() -> None:
    server, recorded = _make_server_with_mock(
        lambda req: httpx.Response(
            200,
            json={
                "data": [
                    {
                        "alarm_id": "AL-100",
                        "asset_id": "A-1",
                        "severity": "high",
                        "message": "x",
                        "raised_at": "2026-08-01T12:00:00Z",
                        "acknowledged": False,
                    }
                ],
                "page": 1,
                "page_size": 25,
                "total": 1,
            },
        )
    )

    since = datetime(2026, 7, 1, tzinfo=UTC)
    until = datetime(2026, 8, 1, tzinfo=UTC)
    result = _call(
        server,
        "summarize_alarms",
        site="EastRefinery",
        asset="A-1",
        severity="high",
        since=since,
        until=until,
        limit=25,
    )

    assert result["total"] == 1
    params = recorded[0].url.params
    assert params["page"] == "1"
    assert params["page_size"] == "25"
    assert params["sort_by"] == "raised_at"
    assert params["sort_order"] == "desc"
    assert params["site"] == "EastRefinery"
    assert params["asset_id"] == "A-1"
    assert params["severity"] == "high"
    assert params["start_time"] == since.isoformat()
    assert params["end_time"] == until.isoformat()


def test_summarize_alarms_omits_unset_filters() -> None:
    server, recorded = _make_server_with_mock(
        lambda req: httpx.Response(200, json={"data": [], "page": 1, "page_size": 25, "total": 0})
    )

    _call(server, "summarize_alarms")

    params = recorded[0].url.params
    # Required defaults are present...
    assert params["page"] == "1"
    assert params["page_size"] == "25"
    # ...but optional filters are not.
    assert "site" not in params
    assert "asset_id" not in params
    assert "severity" not in params
    assert "start_time" not in params
    assert "end_time" not in params


def test_summarize_alarms_rejects_invalid_severity() -> None:
    server, _ = _make_server_with_mock(lambda req: httpx.Response(200, json={}))

    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        _call(server, "summarize_alarms", severity="bogus")


# --------------------------------------------------------------------------- #
# `recommend_actions` — Story 3.2.4
# --------------------------------------------------------------------------- #


def test_recommend_actions_happy_path() -> None:
    server, recorded = _make_server_with_mock(
        lambda req: httpx.Response(
            200,
            json={
                "alarm_id": "AL-100",
                "priority_score": 87,
                "actions": ["Reduce load by 10%", "Inspect sensor"],
                "rationale": "Asset class boiler has high recurrence.",
                "include_related": False,
                "include_asset_context": True,
                "include_historical_pattern": True,
            },
        )
    )

    result = _call(server, "recommend_actions", alarm_id="AL-100")

    assert result["priority_score"] == 87
    assert result["actions"][0] == "Reduce load by 10%"
    assert recorded[0].method == "POST"
    assert recorded[0].url.path == "/recommendations/operator-actions"
    body = json.loads(recorded[0].content.decode("utf-8"))
    assert body == {
        "alarm_id": "AL-100",
        "include_related": False,
        "include_asset_context": True,
        "include_historical_pattern": True,
    }


def test_recommend_actions_404_becomes_alarm_not_found_error() -> None:
    server, _ = _make_server_with_mock(
        lambda req: httpx.Response(404, json={"code": "not_found", "message": "x"})
    )

    with pytest.raises(AlarmNotFoundError):
        _call(server, "recommend_actions", alarm_id="AL-999")


# --------------------------------------------------------------------------- #
# Cross-cutting.
# --------------------------------------------------------------------------- #


def test_all_four_tools_are_listed() -> None:
    """`tools/list` (via the SDK's tool_manager) contains every Alarm tool."""

    def _ok(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={})

    server, _ = _make_server_with_mock(_ok)
    tool_names = {t.name for t in server._tool_manager.list_tools()}
    assert tool_names == {"search_assets", "get_alarm", "summarize_alarms", "recommend_actions"}


def test_get_alarm_api_client_raises_when_lifespan_not_run() -> None:
    """Without an attached client, the accessor raises a clear error."""

    server = MCPServer(name="alarm-management", instructions="test")
    # No `server.alarm_api_client = ...` set.
    with pytest.raises(RuntimeError, match="lifespan"):
        get_alarm_api_client(server)


def test_each_tool_propagates_trace_id_header() -> None:
    """Every tool's outgoing alarm-api request carries an X-Trace-Id."""

    def _ok(req: httpx.Request) -> httpx.Response:
        # Echo the path so we can verify which handler ran.
        return httpx.Response(200, json={"echo": req.url.path})

    server, recorded = _make_server_with_mock(_ok)
    _call(server, "search_assets", query="x")
    _call(server, "get_alarm", alarm_id="AL-1")
    _call(server, "summarize_alarms")
    _call(server, "recommend_actions", alarm_id="AL-1")

    assert len(recorded) == 4
    for req in recorded:
        # `httpx` normalises header keys to lowercase.
        assert "x-trace-id" in req.headers, f"missing X-Trace-Id on {req.method} {req.url}"
