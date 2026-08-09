"""Ticket-mock service.

The copilot uses this as a stand-in for a real ticket-management
system (Jira / Azure DevOps / ServiceNow / GitHub Issues). The
service:

* stores tickets in-memory, seeded with a few deterministic
  entries,
* exposes ``GET /tickets/search`` and ``POST /tickets/draft``
  endpoints,
* generates a deterministic ticket draft from an ``Incident``-
  shaped payload,
* persists a ticket when the caller's request carries
  ``approved=True``.

The MCP server (mcp-servers/ticketing/) reaches this service via
HTTP. The orchestrator reaches the MCP server via Streamable
HTTP. The ticket-draft endpoint is the only path that writes.
"""
from . import app, models, search, store  # noqa: F401
from .app import create_app
from .store import TicketStore, build_default_store

__all__ = [
    "TicketStore",
    "app",
    "build_default_store",
    "create_app",
    "models",
    "search",
    "store",
]
