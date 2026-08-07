"""Copilot backend — the orchestration layer.

The :func:`create_app` factory wires the FastAPI app, the
:class:`ChainRunner`, the planner, the conversation store,
and the routes. The :mod:`__main__` module is the
``python -m apps.backend`` entry — it calls ``create_app``
and runs uvicorn.

The backend is the only process that talks to the MCP
server via the Streamable HTTP transport. It is also the
only process that calls the RAG service. The alarm-api
simulator is reached exclusively through the MCP server
(hard constraint #1).
"""
from __future__ import annotations

from fastapi import FastAPI

from core.config import get_settings
from core.logging import bind_context, configure_logging, get_logger

from .routes import router
from .wiring import OrchestratorBundle, build_orchestrator

log = get_logger(__name__)


def create_app(bundle: OrchestratorBundle | None = None) -> FastAPI:
    """Build the FastAPI app, wiring the orchestrator onto ``app.state``.

    Parameters
    ----------
    bundle:
        Optional pre-built bundle. Production lets the function
        build one from settings; tests pass a fixture bundle.
    """
    settings = get_settings()
    configure_logging(settings.log_level)
    bind_context(service="copilot-backend", mcp_server="alarm-management")

    app = FastAPI(title="copilot-backend")

    if bundle is None:
        bundle = build_orchestrator(settings=settings)
    app.state.orchestrator = bundle

    app.include_router(router)

    log.info("copilot-backend.ready", port=settings.backend_port)
    return app


__all__ = ["OrchestratorBundle", "create_app"]
