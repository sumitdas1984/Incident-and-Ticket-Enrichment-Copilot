"""`@register_tool` registration tests.

These run in-process: no uvicorn, no docker. Each test builds its
own `MCPServer` so registration side-effects stay isolated. The
assertions cover what Feature 3.1 promises:

* a `@register_tool`-decorated function appears in `tools/list`
  with the correct typed `inputSchema`,
* the handler is invoked when `call_tool` runs,
* `httpx.HTTPError` raised inside a handler is mapped to a
  sanitised MCP error envelope (no alarm-api token leaks),
* missing or wrong-shape handlers raise `TypeError` at decoration
  time so misuses fail fast.
"""
from __future__ import annotations

from typing import Any

import httpx
import pytest
from mcp_servers.alarm_management import ToolInvocationError, register_tool
from mcp_servers.alarm_management.registry import _validate_handler_signature
from pydantic import BaseModel, Field


def _make_server() -> Any:
    """Build an isolated `MCPServer` for the test."""
    from mcp.server.mcpserver import MCPServer

    return MCPServer(name="test-server")


# ---- Schema registration -------------------------------------------------- #


class SearchAssetsInput(BaseModel):
    """Top-level Pydantic input used by the single-input shape test."""

    query: str = Field(..., description="Asset name fragment to search for.")
    site: str | None = Field(default=None, description="Optional site filter.")


class OtherInput(BaseModel):
    """Second top-level Pydantic input used by the multi-input rejection test."""

    x: int = Field(..., description="A number.")


def test_register_tool_appears_in_tools_list() -> None:
    """A decorated handler is reachable via `list_tools`."""

    server = _make_server()

    @register_tool(server, name="search_assets", description="Search assets.")
    async def search_assets(inp: SearchAssetsInput) -> dict[str, object]:
        return {"query": inp.query, "site": inp.site}

    tools = server._tool_manager.list_tools()
    assert len(tools) == 1
    tool = tools[0]
    assert tool.name == "search_assets"
    assert tool.description == "Search assets."
    # The SDK builds an `inputSchema` from the Pydantic model.
    schema = tool.fn_metadata.arg_model.model_json_schema(by_alias=True)
    assert "inp" in schema["properties"]
    assert "$defs" in schema
    assert "SearchAssetsInput" in schema["$defs"]


def test_register_tool_flat_kwargs_shape_builds_flat_schema() -> None:
    """A handler with primitive kwargs produces a flat top-level schema.

    No `$defs`, no `inp` wrapper; each parameter is a top-level field.
    """

    server = _make_server()

    @register_tool(server, name="search_assets", description="Search assets.")
    async def search_assets(query: str, site: str | None = None) -> dict[str, object]:
        return {"query": query, "site": site}

    schema = server._tool_manager.list_tools()[0].fn_metadata.arg_model.model_json_schema(
        by_alias=True
    )
    assert "query" in schema["properties"]
    assert "site" in schema["properties"]
    assert "$defs" not in schema
    assert "inp" not in schema["properties"]


# ---- Invocation ---------------------------------------------------------- #


def test_register_tool_handler_is_invoked() -> None:
    """`tool.fn` is the patched closure that delegates to the handler."""

    server = _make_server()
    called_with: list[object] = []

    @register_tool(server, name="echo", description="Echo the input.")
    async def echo(inp: SearchAssetsInput) -> dict[str, object]:
        called_with.append(inp)
        return {"query": inp.query, "site": inp.site}

    tool = server._tool_manager.get_tool("echo")
    # `tool.fn` is now the patched closure — call it directly with a
    # validated Pydantic instance.

    arg_model = tool.fn_metadata.arg_model
    args = arg_model.model_validate({"inp": {"query": "Boiler", "site": "EastRefinery"}})
    kwargs = args.model_dump_one_level()
    result = asyncio_run(tool.fn(**kwargs))
    assert result == {"query": "Boiler", "site": "EastRefinery"}
    assert len(called_with) == 1
    assert called_with[0].query == "Boiler"


def test_register_tool_maps_httpx_error_to_sanitised_envelope() -> None:
    """`httpx.HTTPError` becomes `ToolInvocationError`; no token leaks."""

    server = _make_server()

    @register_tool(server, name="boom", description="Always fails.")
    async def boom(inp: SearchAssetsInput) -> dict[str, object]:
        raise httpx.ConnectError("connection failed: bearer demo-token-leak")

    tool = server._tool_manager.get_tool("boom")
    arg_model = tool.fn_metadata.arg_model
    args = arg_model.model_validate({"inp": {"query": "x"}})
    kwargs = args.model_dump_one_level()

    with pytest.raises(ToolInvocationError) as ei:
        asyncio_run(tool.fn(**kwargs))

    # The user-visible message must not contain the leaked token.
    assert "demo-token-leak" not in str(ei.value)
    assert "Upstream" in str(ei.value)


def test_register_tool_propagates_non_http_errors() -> None:
    """Non-HTTP exceptions propagate untouched (no swallowing)."""

    server = _make_server()

    @register_tool(server, name="boom", description="Always fails.")
    async def boom(inp: SearchAssetsInput) -> dict[str, object]:
        raise ValueError("domain error")

    tool = server._tool_manager.get_tool("boom")
    arg_model = tool.fn_metadata.arg_model
    args = arg_model.model_validate({"inp": {"query": "x"}})
    kwargs = args.model_dump_one_level()

    with pytest.raises(ValueError, match="domain error"):
        asyncio_run(tool.fn(**kwargs))


# ---- Signature validation ------------------------------------------------ #


def test_register_tool_rejects_handler_with_no_args() -> None:
    """A handler without arguments is invalid; decoration fails fast."""

    server = _make_server()

    with pytest.raises(TypeError, match="at least one"):

        @register_tool(server, name="bad", description=".")
        async def bad() -> None:
            return None


def test_register_tool_rejects_mixed_shape() -> None:
    """A handler mixing a Pydantic input with primitive kwargs is rejected."""

    server = _make_server()

    with pytest.raises(TypeError, match="mixes"):

        @register_tool(server, name="bad", description=".")
        async def bad(inp: SearchAssetsInput, extra: str = "x") -> dict[str, object]:
            return {}


def test_register_tool_rejects_flat_kwargs_with_basemodel_param() -> None:
    """A handler with multiple Pydantic params is rejected."""

    server = _make_server()

    with pytest.raises(TypeError, match="multiple Pydantic"):

        @register_tool(server, name="bad", description=".")
        async def bad(a: SearchAssetsInput, b: OtherInput) -> dict[str, object]:
            return {}


def test_register_tool_rejects_untyped_flat_param() -> None:
    """Every flat-kwargs parameter must be annotated."""

    server = _make_server()

    with pytest.raises(TypeError, match="missing an annotation"):

        @register_tool(server, name="bad", description=".")
        async def bad(query) -> dict[str, object]:  # type: ignore[no-untyped-def]
            return {}


# ---- Trace binding (observability) --------------------------------------- #


def test_register_tool_binds_trace_to_structlog_context(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Every call emits `tool.called` / `tool.returned` with `tool=...`.

    structlog's `PrintLoggerFactory` writes to stdout, which pytest
    captures via `capsys` rather than `caplog`.
    """
    from core.logging import configure_logging

    configure_logging("INFO")

    server = _make_server()

    @register_tool(server, name="search_assets", description="Search assets.")
    async def search_assets(query: str) -> dict[str, str]:
        return {"query": query}

    tool = server._tool_manager.get_tool("search_assets")
    asyncio_run(tool.fn(query="Boiler"))

    captured = capsys.readouterr().out
    assert '"event": "tool.called"' in captured
    assert '"event": "tool.returned"' in captured
    assert '"tool": "search_assets"' in captured


# ---- Helpers ------------------------------------------------------------- #


def asyncio_run(coro: object) -> object:
    """Tiny helper so tests don't have to import asyncio at the top."""
    import asyncio

    return asyncio.run(coro)  # type: ignore[arg-type]


def test_validate_handler_signature_pure_helper() -> None:
    """`_validate_handler_signature` is callable without a server."""
    # Direct call: no decorator side-effects.
    async def good(inp: SearchAssetsInput) -> dict[str, object]:
        return {}

    # Should not raise.
    _validate_handler_signature(good, name="good")

    async def untyped(query) -> dict[str, object]:  # type: ignore[no-untyped-def]
        return {}

    with pytest.raises(TypeError):
        _validate_handler_signature(untyped, name="untyped")
