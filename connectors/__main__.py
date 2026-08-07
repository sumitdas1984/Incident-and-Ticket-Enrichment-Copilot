"""Placeholder ticket mock; real ticketing lands in Epic 6."""
import uvicorn
from fastapi import FastAPI

from core.config import get_settings
from core.logging import bind_context, configure_logging, get_logger

settings = get_settings()
configure_logging(settings.log_level)
log = get_logger(__name__)

bind_context(service="ticket-mock")

app = FastAPI(title="ticket-mock (placeholder)")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "ticket-mock"}


if __name__ == "__main__":
    # The container port is fixed by docker-compose.yml. settings.ticketing_api_port
    # is the HOST port for client code.
    container_port = 8000
    log.info("starting", component="ticket-mock", port=container_port)
    uvicorn.run(app, host="0.0.0.0", port=container_port)
