"""FastAPI app factory for the ticket-mock service."""
from __future__ import annotations

from fastapi import FastAPI

from core.config import get_settings
from core.logging import bind_context, configure_logging

from .routers import health, tickets
from .store import build_default_store


def create_app() -> FastAPI:
    """Build a fully wired ticket-mock app instance."""
    settings = get_settings()
    configure_logging(settings.log_level)
    bind_context(service="ticket-mock")

    app = FastAPI(title="Ticket Mock Service", version="0.1.0")
    app.state.ticket_store = build_default_store()

    app.include_router(health.router)
    app.include_router(tickets.router)
    return app
