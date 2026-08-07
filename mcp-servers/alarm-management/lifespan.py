"""Starlette lifespan that drives the MCP session manager.

The MCP SDK's `MCPServer` registers tools but doesn't initialise
its `StreamableHTTPSessionManager`'s task group — that's done
inside `run_streamable_http_async()`. To use the SDK inside a
generic ASGI host (uvicorn, FastAPI mount, Starlette `TestClient`)
we need a Starlette-compatible lifespan that calls
`session_manager.run()` for the duration of the app's life.

Starlette's `Router` expects `lifespan` to be **callable**: it
invokes `lifespan(app)`, which must return an async context
manager. We expose a callable class that does exactly that.
"""
from __future__ import annotations

from types import TracebackType
from typing import Any


class MCPServerLifespan:
    """Starlette-compatible lifespan that drives an MCP server.

    Starlette calls ``lifespan(app)`` on startup; the returned
    object must support ``async with``. This class does both.

    Usage::

        app = Starlette(routes=..., lifespan=MCPServerLifespan(server))

    Where ``server`` is an `MCPServer` instance.
    """

    def __init__(self, server: Any) -> None:
        self._server = server

    def __call__(self, app: object) -> MCPServerLifespan:
        # Starlette passes the Starlette app here; we don't need it
        # because the MCP session manager doesn't depend on the
        # ASGI scope. Return self so the caller can `async with`
        # the same instance.
        return self

    async def __aenter__(self) -> None:
        session_manager = getattr(self._server, "session_manager", None)
        if session_manager is None:
            return
        # Enter the session manager's task group. Stash the
        # underlying context manager so __aexit__ can leave it.
        self._cm = session_manager.run()
        await self._cm.__aenter__()

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        cm = getattr(self, "_cm", None)
        if cm is None:
            return
        await cm.__aexit__(exc_type, exc_val, exc_tb)


def make_asgi_app(server: Any) -> Any:
    """Build a Starlette app for `server` with the MCP lifespan wired.

    Wraps `server.streamable_http_app()` so the session manager is
    active throughout the app's lifetime. Mounts health/ready routes
    on the same Starlette app via `custom_route` (already done by
    `register_health_routes` on the `MCPServer` instance).
    """
    from starlette.applications import Starlette

    starlette_app = server.streamable_http_app()
    lifespan = MCPServerLifespan(server)
    return Starlette(
        debug=False,
        routes=starlette_app.routes,
        middleware=starlette_app.user_middleware,  # type: ignore[arg-type]
        lifespan=lifespan,
    )
