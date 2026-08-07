"""Placeholder Alarm Management API simulator; real implementation lands in Epic 2."""
import uvicorn
from fastapi import FastAPI

from core.config import get_settings
from core.logging import bind_context, configure_logging, get_logger

settings = get_settings()
configure_logging(settings.log_level)
log = get_logger(__name__)

bind_context(service="alarm-api")

app = FastAPI(title="alarm-api (placeholder)")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "alarm-api"}


if __name__ == "__main__":
    log.info("starting", component="alarm-api", port=settings.alarm_api_port)
    uvicorn.run(app, host="0.0.0.0", port=settings.alarm_api_port)
