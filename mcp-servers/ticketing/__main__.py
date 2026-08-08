"""Ticketing MCP server entry point.

Boots a candidate-developed MCP server that exposes ticket
search and draft-generation tools to the orchestrator over
Streamable HTTP. The MCP protocol is provided by the official
Python SDK. The candidate-developed surface mirrors the
alarm-management MCP server's structure: typed tool
registration, liveness/readiness probes, structured logging,
and a shared HTTP client for the ticket-mock service.

Run via ``python -m mcp_servers.ticketing`` or via the
docker-compose service.
"""
from __future__ import annotations

import asyncio
import os

import uvicorn
from mcp.server.mcpserver import MCPServer
from mcp_servers.alarm_management.lifespan import MCPServerLifespan
from starlette.applications import Starlette

from core.config import get_settings
from core.logging import get_logger

from . import context  # noqa: F401 — configures logging
from .health import register_health_routes
from .ticket_client import TicketClient
from .tools import register_tools

log = get_logger(__name__)

settings = get_settings()


# --------------------------------------------------------------------------- #
# MCP server.
# --------------------------------------------------------------------------- #

mcp_server = MCPServer(
    name="ticketing",
    instructions=(
        "Ticketing MCP server. Provides typed tools for searching "
        "the ticket-mock's in-memory ticket store and generating "
        "deterministic ticket drafts from an Incident payload. "
        "Draft creation is gated by the caller's ``approved`` "
        "flag — this tool does not enforce any policy of its own."
    ),
)

register_health_routes(mcp_server, version=os.environ.get("MCP_SERVER_VERSION", "0.1.0"))
register_tools(mcp_server)


class TicketingLifespan(MCPServerLifespan):
    """Lifespan that attaches the TicketClient."""

    async def __aenter__(self) -> None:  # type: ignore[override]
        client = TicketClient.from_settings(get_settings())
        self._server.ticket_client = client
        log.info(
            "ticket_client.attached",
            base_url=get_settings().ticketing_api_url,
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
            client = getattr(self._server, "ticket_client", None)
            if client is not None:
                await client.aclose()


_starlette_app = mcp_server.streamable_http_app()
app = Starlette(
    debug=False,
    routes=_starlette_app.routes,
    middleware=_starlette_app.user_middleware,  # type: ignore[arg-type]
    lifespan=TicketingLifespan(mcp_server),
)


async def _serve() -> None:
    log.info(
        "starting",
        component="mcp-server-ticketing",
        port=settings.ticketing_mcp_port,
    )
    config = uvicorn.Config(
        app,  # type: ignore[arg-type]
        host="0.0.0.0",
        port=settings.ticketing_mcp_port,
        log_level=settings.log_level.lower(),
    )
    server = uvicorn.Server(config)
    await server.serve()


if __name__ == "__main__":
    asyncio.run(_serve())
