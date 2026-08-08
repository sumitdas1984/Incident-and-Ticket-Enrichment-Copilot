"""Ticket-mock service entry point.

Run via ``python -m connectors.ticket_mock`` or via the
docker-compose service.
"""
from __future__ import annotations

import uvicorn

from core.config import get_settings
from core.logging import configure_logging, get_logger

from .app import create_app

settings = get_settings()
configure_logging(settings.log_level)
log = get_logger(__name__)

app = create_app()


if __name__ == "__main__":
    container_port = 8000
    log.info("starting", component="ticket-mock", port=container_port)
    uvicorn.run(app, host="0.0.0.0", port=container_port)
