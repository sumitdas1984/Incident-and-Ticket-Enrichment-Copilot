"""Placeholder MCP server; real tools land in Epic 3."""
import uvicorn
from fastapi import FastAPI

from core.config import get_settings
from core.logging import bind_context, configure_logging, get_logger

settings = get_settings()
configure_logging(settings.log_level)
log = get_logger(__name__)

bind_context(service="mcp-server", mcp_server="alarm-management")

app = FastAPI(title="alarm-management MCP server (placeholder)")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "alarm-management-mcp"}


if __name__ == "__main__":
    log.info("starting", component="mcp-server-alarm-management", port=settings.mcp_server_port)
    uvicorn.run(app, host="0.0.0.0", port=settings.mcp_server_port)
