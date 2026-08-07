"""FastAPI app factory for the alarm-api simulator."""
from __future__ import annotations

from fastapi import FastAPI

from core.config import get_settings
from core.logging import bind_context, configure_logging

from .errors import install_handlers
from .routers import alarms, analytics, assets, calculations, health, recommendations
from .store import AlarmStore


def create_app() -> FastAPI:
    """Build a fully wired alarm-api app instance.

    Configuration is loaded once via core.config.get_settings(); the
    bearer token and the log level both come from there. The store
    is attached to app.state so routers can reach it via request.app.
    """
    settings = get_settings()
    configure_logging(settings.log_level)
    bind_context(mcp_server="alarm-api")

    app = FastAPI(title="Alarm Management API", version="0.1.0")
    app.state.store = AlarmStore()

    install_handlers(app)

    app.include_router(health.router)
    app.include_router(assets.router)
    app.include_router(alarms.router)
    app.include_router(recommendations.router)
    app.include_router(calculations.router)
    app.include_router(analytics.router)
    return app
