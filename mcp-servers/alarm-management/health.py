"""Liveness and readiness probes for the MCP server.

Two routes attached to the `MCPServer` via its ``custom_route``
decorator:

* ``GET /health`` is unauthenticated, returns 200 unconditionally.
  Used by docker-compose as the liveness signal. The MCP server is
  considered alive as long as uvicorn can serve the route.

* ``GET /ready`` probes the alarm-api dependency. Returns 200 if
  the alarm-api is reachable within 500 ms; 503 otherwise. Used by
  any downstream consumer that wants to wait before sending real
  traffic. docker-compose doesn't poll this directly today, but the
  orchestrator (apps/backend) may.

Both responses are JSON and **never** include the alarm-api token or
any other secret.
"""
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
    """Attach ``/health`` and ``/ready`` to the given MCP server.

    Imported as a function (not at module import) so unit tests can
    build an isolated `MCPServer` and exercise the routes without
    booting the alarm-api dependency.
    """

    @server.custom_route("/health", methods=["GET"])
    async def health(_request: Request) -> Response:  # noqa: ARG001 — Starlette contract
        """Liveness probe. Always 200 if the process is up."""
        return JSONResponse(
            {
                "status": "ok",
                "service": "alarm-management-mcp",
                "version": version,
            }
        )

    @server.custom_route("/ready", methods=["GET"])
    async def ready(_request: Request) -> Response:
        """Readiness probe. 200 only if the alarm-api dependency responds.

        Returns ``{"status":"ready","alarm_api":"reachable"}`` on success
        or ``{"status":"not_ready","alarm_api":"<reason>"}`` with status
        503 on failure. The failure reason is sanitised — no token, no
        full URL with credentials.
        """
        cfg = get_settings()
        try:
            r = httpx.get(
                f"{cfg.alarm_api_base_url}/health",
                headers={
                    "Authorization": f"Bearer {cfg.alarm_api_token.get_secret_value()}",
                },
                timeout=_READINESS_TIMEOUT_SECONDS,
            )
        except httpx.HTTPError as exc:
            log.warning("ready.probe_failed", error_type=type(exc).__name__)
            return JSONResponse(
                {"status": "not_ready", "alarm_api": "unreachable"},
                status_code=503,
            )
        if r.status_code != 200:
            log.warning("ready.probe_non_200", status_code=r.status_code)
            return JSONResponse(
                {"status": "not_ready", "alarm_api": f"status_{r.status_code}"},
                status_code=503,
            )
        return JSONResponse({"status": "ready", "alarm_api": "reachable"})
