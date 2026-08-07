"""MCP client — facade over the Streamable HTTP transport.

The orchestrator uses the official MCP Python SDK to talk to
the alarm-management server. The protocol is Streamable HTTP
at ``{base_url}/mcp`` (no auth on the wire; the server is
internal). The client opens one short-lived session per
:class:`MCPClient.call` invocation — ``ClientSession`` is *not*
safe to share across concurrent ``call_tool`` calls.

Why a facade, not the raw SDK
-----------------------------

The orchestrator's call site is ::

    output, trace_step = await mcp.call(tool="search_assets", args={"query": "boiler"})

Returning ``(output, TraceStep)`` keeps the chain runner simple
— it threads the trace step into the response envelope without
needing to know about the MCP SDK or the TraceStep construction.
"""
from __future__ import annotations

import time
from typing import Any

from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from core.config import get_settings
from core.domain import TraceStep
from core.exceptions import MCPError
from core.logging import bind_context, get_logger

from .request import ToolCatalogEntry

log = get_logger(__name__)


class MCPClient:
    """Thin facade over the MCP Streamable HTTP transport.

    One session per ``call`` invocation — sessions are cheap
    and explicit lifetime keeps log state clean.
    """

    def __init__(self, *, base_url: str | None = None, server_name: str = "alarm-management") -> None:
        if base_url is None:
            base_url = get_settings().mcp_server_url
        self._base_url = base_url.rstrip("/")
        self._endpoint = f"{self._base_url}/mcp"
        self._server_name = server_name

    async def list_tools(self) -> list[ToolCatalogEntry]:
        """Return the catalog of tools the server exposes."""
        async with streamable_http_client(self._endpoint) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.list_tools()
                return [
                    ToolCatalogEntry(
                        name=t.name,
                        description=t.description or "",
                    )
                    for t in result.tools
                ]

    async def call(self, *, tool: str, args: dict[str, Any]) -> tuple[Any, TraceStep]:
        """Invoke ``tool`` with ``args`` and return ``(output, trace_step)``.

        Raises :class:`MCPError` if the server returns ``is_error``
        or the transport fails. The trace step is built even on
        failure so the orchestrator can surface the attempted
        call in the response envelope.
        """
        started = time.perf_counter()
        bind_context(tool=tool, mcp_server=self._server_name)
        try:
            async with streamable_http_client(self._endpoint) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    result = await session.call_tool(name=tool, arguments=args)
        except MCPError:
            raise
        except Exception as exc:
            duration_ms = int((time.perf_counter() - started) * 1000)
            log.warning(
                "mcp.transport_error",
                tool=tool,
                error_type=type(exc).__name__,
                exc_info=True,
            )
            trace = TraceStep(
                server=self._server_name,
                tool=tool,
                args=args,
                output=None,
                duration_ms=duration_ms,
                outcome="error",
                error=str(exc),
            )
            raise MCPError(f"MCP transport error on {tool!r}: {exc}") from exc

        duration_ms = int((time.perf_counter() - started) * 1000)
        if result.is_error:
            message = ""
            try:
                if result.content:
                    first = result.content[0]
                    message = getattr(first, "text", "") or str(first)
            except (IndexError, AttributeError):
                message = ""
            trace = TraceStep(
                server=self._server_name,
                tool=tool,
                args=args,
                output=None,
                duration_ms=duration_ms,
                outcome="error",
                error=message or "tool returned is_error",
            )
            raise MCPError(f"tool {tool!r} returned is_error: {message}")

        output = result.structured_content
        trace = TraceStep(
            server=self._server_name,
            tool=tool,
            args=args,
            output=output,
            duration_ms=duration_ms,
            outcome="success",
        )
        return output, trace

    async def initialize(self) -> dict[str, Any]:
        """Return the server's ``initialize`` envelope.

        Used by the orchestrator at startup to surface the
        server's name and instructions in the planner's prompt.
        """
        async with streamable_http_client(self._endpoint) as (read, write):
            async with ClientSession(read, write) as session:
                init = await session.initialize()
                return {
                    "name": init.server_info.name,
                    "instructions": getattr(init, "instructions", None),
                }


__all__ = ["MCPClient", "ToolCatalogEntry"]
