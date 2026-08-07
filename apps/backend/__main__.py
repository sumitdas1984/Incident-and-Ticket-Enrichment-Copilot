"""Placeholder backend; real implementation lands in Epic 5.

Smoke-tests the core/ package: settings load, logger configures,
JSON line emitted at startup.
"""
import uvicorn
from fastapi import FastAPI

from core.config import get_settings
from core.logging import bind_context, configure_logging, get_logger

settings = get_settings()
configure_logging(settings.log_level)
log = get_logger(__name__)

bind_context(service="copilot-backend", mcp_server="alarm-management")

app = FastAPI(title="copilot-backend (placeholder)")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "copilot-backend"}


if __name__ == "__main__":
    log.info("starting", component="copilot-backend", port=settings.backend_port)
    uvicorn.run(app, host="0.0.0.0", port=settings.backend_port)
