"""Alarm Management MCP server.

Boots a candidate-developed MCP server that exposes Alarm Management
API capabilities to the copilot orchestrator over Streamable HTTP.
The MCP protocol is provided by the official Python SDK; we add:

* typed tool registration with auto-populated `ToolContext`
  (see `registry.py`),
* liveness (``/health``) and readiness (``/ready``) probes that
  don't go through MCP,
* structured logging via `core.logging`.

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

Concrete Alarm tools (``search_assets``, ``get_alarm``,
``summarize_alarms``, ``recommend_actions``) land in Feature 3.2.
"""
from __future__ import annotations

import asyncio
import os

import uvicorn
from mcp.server.mcpserver import MCPServer
from mcp_servers.alarm_management.health import register_health_routes
from mcp_servers.alarm_management.lifespan import make_asgi_app

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


# ASGI app with the session-manager lifespan. Exposed at module
# scope so the in-process test fixtures can import it.
app = make_asgi_app(mcp_server)


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
