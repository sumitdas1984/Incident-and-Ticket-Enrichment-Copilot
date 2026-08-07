"""Entry point: run the alarm-api simulator via uvicorn.

Real implementation for Feature 2.1. Wires core.config + core.logging
through the FastAPI app and binds the container port directly
(settings.alarm_api_port is the host port, not the container port).
"""
import uvicorn

from core.config import get_settings
from core.logging import configure_logging, get_logger

from .app import create_app

settings = get_settings()
configure_logging(settings.log_level)
log = get_logger(__name__)

app = create_app()


if __name__ == "__main__":
    # The container port is fixed by docker-compose.yml (the second
    # number in the 'ports:' mapping). settings.alarm_api_port is the
    # HOST port and is for client code that needs to reach this
    # service over the host network.
    container_port = 8000
    log.info("starting", component="alarm-api", port=container_port)
    uvicorn.run(app, host="0.0.0.0", port=container_port)
