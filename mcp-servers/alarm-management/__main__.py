"""Alarm Management MCP server.

Boots a candidate-developed MCP server that exposes Alarm Management
API capabilities to the copilot orchestrator over Streamable HTTP.
The MCP protocol is provided by the official Python SDK; we add:

* typed tool registration with auto-populated `ToolContext`
  (see `registry.py`),
* liveness (``/health``) and readiness (``/ready``) probes that
  don't go through MCP,
* structured logging via `core.logging`,
* a shared :class:`AlarmApiClient` that every tool handler
  reaches through (Feature 3.2).

This module is the entry point. The MCP SDK's `MCPServer` registers
tools but doesn't own the Streamable HTTP session manager's task
group; we wrap its Starlette app in a Starlette lifespan
(`mcpserver_lifespan`) that calls `session_manager.run()` for the
app's lifetime, then hand the resulting app to uvicorn. The same
composition is used by `tests/integration/mcp_server/`, so what
ships is what tests against.

Probes are attached via the SDK's ``custom_route`` decorator so they
share the same Starlette app and port, but are not part of the MCP
protocol — they are unauthenticated, return JSON, and never include
secrets.

Tool registration (Feature 3.2)
-------------------------------

``MCPServerLifespan.__aenter__`` builds and attaches an
:class:`AlarmApiClient` to the server, then calls
:func:`tools.register_tools` so the four Alarm Management tools
become discoverable via ``tools/list``. The client is closed on
shutdown; tool handlers read it from the server instance.
"""
from __future__ import annotations

import asyncio
import os

import uvicorn
from mcp.server.mcpserver import MCPServer
from mcp_servers.alarm_management.alarm_api_client import AlarmApiClient
from mcp_servers.alarm_management.health import register_health_routes
from mcp_servers.alarm_management.tools import register_tools

from core.config import get_settings
from core.logging import bind_context, configure_logging, get_logger

# --------------------------------------------------------------------------- #
# Logging — wire once at module import so uvicorn's stdout shows our format.
# --------------------------------------------------------------------------- #

settings = get_settings()
configure_logging(settings.log_level)
log = get_logger(__name__)
bind_context(service="mcp-server", mcp_server="alarm-management")


# --------------------------------------------------------------------------- #
# MCP server.
# --------------------------------------------------------------------------- #
#
# `instructions` is what an MCP client surfaces when it calls
# `initialize`; the orchestrator uses this to ground its planning
# prompt. Kept short and operator-focused on purpose.
mcp_server = MCPServer(
    name="alarm-management",
    instructions=(
        "Alarm Management MCP server. Provides typed tools for asset search, "
        "alarm retrieval, alarm summary, and operator-recommendation lookups "
        "against the Alarm Management API."
    ),
)

register_health_routes(mcp_server, version=os.environ.get("MCP_SERVER_VERSION", "0.1.0"))
register_tools(mcp_server)


# Override the default lifespan so the AlarmApiClient is built /
# closed alongside the MCP session manager. We subclass the base
# lifespan (which itself drives the MCP session manager) rather
# than parameterising ``make_asgi_app`` so the existing test
# fixtures stay untouched.
from mcp_servers.alarm_management.lifespan import MCPServerLifespan  # noqa: E402
from starlette.applications import Starlette  # noqa: E402


class AlarmManagementLifespan(MCPServerLifespan):
    """Lifespan that also attaches the AlarmApiClient.

    On ``__aenter__``: build the client, attach it to the server,
    then enter the MCP session manager (inherited behaviour).

    On ``__aexit__``: leave the MCP session manager (inherited),
    then close the client. Order matters — closing the client
    before the session manager tears down means in-flight tool
    calls could try to use a closed client.
    """

    async def __aenter__(self) -> None:  # type: ignore[override]
        client = AlarmApiClient.from_settings(get_settings())
        self._server.alarm_api_client = client
        log.info(
            "alarm_api_client.attached",
            base_url=get_settings().alarm_api_base_url,
        )
        await super().__aenter__()

    async def __aexit__(  # type: ignore[override]
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: object | None,
    ) -> None:
        try:
            await super().__aexit__(exc_type, exc_val, exc_tb)
        finally:
            client = getattr(self._server, "alarm_api_client", None)
            if client is not None:
                await client.aclose()


# Rebuild the module-level app with the enhanced lifespan. We do
# this here (not in ``make_asgi_app``) so the helper stays generic
# and reusable by the test fixtures.
_starlette_app = mcp_server.streamable_http_app()
app = Starlette(
    debug=False,
    routes=_starlette_app.routes,
    middleware=_starlette_app.user_middleware,  # type: ignore[arg-type]
    lifespan=AlarmManagementLifespan(mcp_server),
)


async def _serve() -> None:
    log.info(
        "starting",
        component="mcp-server-alarm-management",
        port=settings.mcp_server_port,
    )
    config = uvicorn.Config(
        app,  # type: ignore[arg-type]
        host="0.0.0.0",
        port=settings.mcp_server_port,
        log_level=settings.log_level.lower(),
    )
    server = uvicorn.Server(config)
    await server.serve()


if __name__ == "__main__":
    asyncio.run(_serve())
