"""Copilot backend entry point.

Run via ``python -m apps.backend`` or via the docker-compose
service. The FastAPI app is built by :func:`apps.backend.create_app`,
which wires the orchestration layer onto ``app.state``.
"""
from __future__ import annotations

import uvicorn

from apps.backend import create_app
from core.config import get_settings
from core.logging import bind_context, configure_logging, get_logger

settings = get_settings()
configure_logging(settings.log_level)
log = get_logger(__name__)

bind_context(service="copilot-backend", mcp_server="alarm-management")

app = create_app()


if __name__ == "__main__":
    # The container port is fixed by docker-compose.yml (the second
    # number in the 'ports:' mapping). settings.backend_port is the
    # HOST port and is for client code that needs to reach this
    # service over the host network.
    container_port = 8000
    log.info("starting", component="copilot-backend", port=container_port)
    uvicorn.run(app, host="0.0.0.0", port=container_port)
