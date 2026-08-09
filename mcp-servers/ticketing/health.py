"""Liveness and readiness probes for the ticketing MCP server."""
from __future__ import annotations

from typing import TYPE_CHECKING

import httpx
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from core.config import get_settings
from core.logging import get_logger

if TYPE_CHECKING:
    from mcp.server.mcpserver import MCPServer

log = get_logger(__name__)

_READINESS_TIMEOUT_SECONDS = 0.5


def register_health_routes(server: MCPServer, *, version: str) -> None:
    """Attach ``/health`` and ``/ready`` to the given MCP server."""

    @server.custom_route("/health", methods=["GET"])
    async def health(_request: Request) -> Response:
        """Liveness probe. Always 200 if the process is up."""
        return JSONResponse(
            {
                "status": "ok",
                "service": "ticketing-mcp",
                "version": version,
            }
        )

    @server.custom_route("/ready", methods=["GET"])
    async def ready(_request: Request) -> Response:
        """Readiness probe. 200 only if the ticket-mock service responds."""
        cfg = get_settings()
        try:
            r = httpx.get(
                f"{cfg.ticketing_api_base_url}/health",
                headers={
                    "Authorization": f"Bearer {cfg.ticketing_api_token.get_secret_value()}",
                },
                timeout=_READINESS_TIMEOUT_SECONDS,
            )
        except httpx.HTTPError as exc:
            log.warning("ready.probe_failed", error_type=type(exc).__name__)
            return JSONResponse(
                {"status": "not_ready", "ticket_mock": "unreachable"},
                status_code=503,
            )
        if r.status_code != 200:
            return JSONResponse(
                {"status": "not_ready", "ticket_mock": f"status_{r.status_code}"},
                status_code=503,
            )
        return JSONResponse({"status": "ready", "ticket_mock": "reachable"})
