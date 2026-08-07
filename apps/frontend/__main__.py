"""Placeholder frontend; real GUI lands in Epic 7."""
import uvicorn
from fastapi import FastAPI

from core.config import get_settings
from core.logging import bind_context, configure_logging, get_logger

settings = get_settings()
configure_logging(settings.log_level)
log = get_logger(__name__)

bind_context(service="frontend")

app = FastAPI(title="frontend (placeholder)")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "frontend"}


if __name__ == "__main__":
    log.info("starting", component="frontend", port=settings.frontend_port)
    uvicorn.run(app, host="0.0.0.0", port=settings.frontend_port)
