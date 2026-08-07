"""`tools/list` discovery tests for the alarm-management MCP server.

Exercises the SDK's full JSON-RPC plumbing (initialize +
tools/list) against a real uvicorn process. We bind an ephemeral
port via `socket` so the tests are safe under parallel pytest and
on machines that already have something listening on 9000.

The MCP client SDK opens its own `httpx` connection, so we can't
short-circuit via Starlette's `TestClient` (which only patches
`httpx` for its own requests). Standing up uvicorn is the
faithful composition: what ships is what tests against.
"""
from __future__ import annotations

import asyncio
import socket
import threading
import time

import pytest
import uvicorn
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from mcp.server.mcpserver import MCPServer
from mcp_servers.alarm_management.health import register_health_routes
from mcp_servers.alarm_management.lifespan import make_asgi_app


def _free_port() -> int:
    """Bind a socket to port 0 to discover an unused port, then release."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def mcp_url(monkeypatch: pytest.MonkeyPatch) -> str:
    """Stand up a uvicorn MCP server on a free port for the test."""
    monkeypatch.setenv("ALARM_API_BASE_URL", "http://127.0.0.1:1")
    monkeypatch.setenv("ALARM_API_TOKEN", "test-token")
    from core.config import get_settings

    get_settings.cache_clear()

    server = MCPServer(name="alarm-management", instructions="Alarm Management MCP server.")
    register_health_routes(server, version="test")
    app = make_asgi_app(server)

    port = _free_port()
    config = uvicorn.Config(
        app,  # type: ignore[arg-type]
        host="127.0.0.1",
        port=port,
        log_level="warning",
    )
    uv = uvicorn.Server(config)

    thread = threading.Thread(target=lambda: asyncio.run(uv.serve()), daemon=True)
    thread.start()

    # Wait for the server to bind.
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.1):
                break
        except OSError:
            time.sleep(0.05)
    else:
        raise RuntimeError(f"uvicorn did not bind on port {port} in 5s")

    yield f"http://127.0.0.1:{port}"

    uv.should_exit = True
    thread.join(timeout=5.0)
    get_settings.cache_clear()


def _list_tools_via_mcp(base_url: str) -> list[dict[str, object]]:
    """Run a full JSON-RPC `tools/list` against the MCP server."""

    async def runner() -> list[dict[str, object]]:
        async with streamable_http_client(f"{base_url}/mcp") as streams:
            read, write = streams[0], streams[1]
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.list_tools()
                return [t.model_dump(mode="json") for t in result.tools]

    return asyncio.run(runner())


def test_tools_list_is_well_formed_when_empty(mcp_url: str) -> None:
    """Feature 3.1 ships zero tools; `tools/list` is a valid empty list.

    The contract requires typed schemas in `tools/list`. An empty
    list is a valid typed schema — it's `[]`, not malformed. This
    test guards against a regression where the SDK composition or
    the Streamable HTTP transport fails on a no-tools server.
    """
    tools = _list_tools_via_mcp(mcp_url)
    assert tools == []


def test_mcp_initialize_reports_correct_server_info(mcp_url: str) -> None:
    """`initialize` surfaces the MCP server's name and instructions."""

    async def runner() -> tuple[str, str | None]:
        async with streamable_http_client(f"{mcp_url}/mcp") as streams:
            read, write = streams[0], streams[1]
            async with ClientSession(read, write) as session:
                init = await session.initialize()
                return (
                    init.server_info.name,
                    init.instructions if hasattr(init, "instructions") else None,
                )

    name, instructions = asyncio.run(runner())
    assert name == "alarm-management"
    assert instructions is not None
    assert "Alarm" in instructions
