"""Logging setup for the ticketing MCP server."""
from __future__ import annotations

from core.config import get_settings
from core.logging import bind_context, configure_logging, get_logger

settings = get_settings()
configure_logging(settings.log_level)
log = get_logger(__name__)

bind_context(service="mcp-server", mcp_server="ticketing")
