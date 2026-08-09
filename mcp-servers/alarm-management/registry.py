"""Tool registration on top of the MCP SDK's `MCPServer`.

We wrap `MCPServer.tool()` so the call / return lifecycle is logged
uniformly and `httpx.HTTPError` is mapped to a sanitised MCP
``isError`` envelope.

The wrapper does three things on top of the SDK:

1. **Validate the handler signature.** The handler must take
   either one Pydantic `BaseModel` parameter (single-input shape)
   or several primitive-typed parameters (flat-kwargs shape). The
   shapes are documented in `_validate_handler_signature`. We
   reject anything else at decoration time so mis-decorated tools
   fail fast (and locally) rather than on the first MCP request.

2. **Uniform structured logging.** Every call emits
   ``log.info("tool.called", tool=..., trace_id=...)`` and
   ``log.info("tool.returned", tool=..., duration_ms=...)``. The
   trace_id is bound to the structlog context so any nested log
   call inside the handler inherits it.

3. **Sanitised error envelope.** `httpx.HTTPError` raised inside the
   handler is caught and re-raised as `ToolInvocationError`. The MCP
   transport turns that into an ``isError`` JSON-RPC response whose
   message does not contain the alarm-api token. Other exceptions
   propagate untouched.

Why we don't wrap the handler itself: the SDK's `func_metadata`
introspects the registered callable's signature to build an
arg_model. If we wrap with a generic `BaseModel` annotation,
pydantic v2 fails validation against the protocol payload
(``'BaseModel' object has no attribute '__private_attributes__'``).
So we register the user's handler unchanged and patch the SDK's
internal `Tool.fn` reference with a logging-and-error-mapping
closure.

Handler signatures
------------------
Two shapes are supported; both place typed inputs at the top of
the tool's `inputSchema`:

* Single Pydantic input:
  ``async def handler(inp: MyInput) -> Any``
* Flat typed kwargs (preferred for ≤ ~4 simple fields):
  ``async def handler(query: str, site: str | None = None) -> Any``

Handlers do **not** receive a context parameter. Trace identifiers
flow via `core.logging.bind_context` (structlog's contextvars) so
any nested log call inherits them. This matches MCP's design intent:
the SDK's `Context` is a transport-level concern, not a tool
contract concern, and a tool should not have to know about it.
"""
from __future__ import annotations

import inspect
import time
from collections.abc import Callable
from typing import Any, TypeVar

import httpx
from pydantic import BaseModel

from core.logging import bind_context, clear_context, get_logger

log = get_logger(__name__)


class ToolInvocationError(RuntimeError):
    """Raised when an MCP tool handler can't reach its upstream system.

    Distinct from arbitrary RuntimeError so the transport can map it
    to an ``isError`` JSON-RPC response without exposing internal
    details to the client. The message is sanitised; no secret ever
    appears on the wire.
    """

    def __init__(self, message: str, *, hint: str | None = None) -> None:
        super().__init__(message)
        self.hint = hint


_HandlerT = TypeVar("_HandlerT", bound=Callable[..., Any])


def register_tool(
    server: Any,
    *,
    name: str,
    description: str,
) -> Callable[[_HandlerT], _HandlerT]:
    """Decorator that registers a coroutine as an MCP tool on `server`.

    Parameters
    ----------
    server:
        The `MCPServer` instance tools are attached to. Passing it in
        explicitly (rather than reading a global) keeps tests honest:
        each test can build its own server and registration stays
        trivially side-effect-free.
    name:
        Public tool name surfaced in `tools/list`. Must be unique
        within the server.
    description:
        Human-readable description surfaced in `tools/list`.

    Handler signature
    -----------------
    ``async def handler(inp: PydanticModel) -> Any``

    The handler must take exactly one positional argument that is a
    top-level Pydantic `BaseModel` subclass — its JSON Schema
    becomes the tool's `inputSchema`.
    """

    def decorator(fn: _HandlerT) -> _HandlerT:
        _validate_handler_signature(fn, name=name)

        # Register the user's handler unchanged so the SDK's
        # `func_metadata` builds the arg_model from its real
        # annotations. `structured_output=True` opts into the MCP
        # `structuredContent` envelope so the orchestrator can pull
        # typed results without parsing JSON from a text block.
        registered_fn = server.tool(
            name=name,
            description=description,
            structured_output=True,
        )(fn)

        # Patch the SDK's `Tool.fn` with a logging + error-mapping
        # closure. We replace the reference rather than wrapping the
        # callable because wrapping with a generic `BaseModel`
        # signature breaks pydantic v2 validation against the protocol
        # payload (`'BaseModel' object has no attribute
        # '__private_attributes__'`).
        try:
            tool = server._tool_manager._tools[name]
        except AttributeError:
            log.warning(
                "register_tool.patch_failed",
                tool=name,
                hint="MCPServer internals changed; call/return logging skipped.",
            )
            return registered_fn or fn  # type: ignore[return-value]

        original_fn = tool.fn

        async def patched(*args: Any, **kwargs: Any) -> Any:
            tc_trace_id = _extract_trace_id(args, kwargs)
            bind_context(trace_id=tc_trace_id, tool=name)
            started = time.perf_counter()
            log.info("tool.called", tool=name)
            try:
                result = await original_fn(*args, **kwargs)
            except httpx.HTTPError as exc:
                log.warning(
                    "tool.upstream_error",
                    tool=name,
                    error_type=type(exc).__name__,
                    exc_info=True,
                )
                raise ToolInvocationError(
                    "Upstream Alarm API call failed.",
                    hint="See server logs with the same trace_id for details.",
                ) from exc
            duration_ms = (time.perf_counter() - started) * 1000.0
            log.info("tool.returned", tool=name, duration_ms=round(duration_ms, 2))
            clear_context()
            return result

        tool.fn = patched  # type: ignore[assignment]

        # Tag the wrapper so other modules (e.g. a future CLI tool)
        # can introspect the registration without going through MCP.
        patched.__mcp_tool_name__ = name  # type: ignore[attr-defined]
        patched.__mcp_input_type__ = fn.__annotations__.get(  # type: ignore[attr-defined]
            next(iter(inspect.signature(fn).parameters), ""),
            None,
        )
        return registered_fn or fn  # type: ignore[return-value]

    return decorator


def _validate_handler_signature(fn: Callable[..., Any], *, name: str) -> None:
    """Reject handlers that don't match the documented shapes.

    Two shapes are supported:

    1. **Single Pydantic input** —
       ``async def handler(inp: MyInput) -> Any:``
       The Pydantic model's JSON Schema becomes the tool's
       `inputSchema`; the protocol caller passes ``{"inp": {...}}``.

    2. **Flat typed kwargs** —
       ``async def handler(query: str, site: str | None = None) -> Any:``
       Each parameter becomes a top-level field on the tool's
       `inputSchema`; the protocol caller passes ``{"query": ...,
       "site": ...}``.

    The second shape is preferred for tools with ≤ ~4 simple fields
    because the protocol payload stays flat. The first shape is
    required when a tool has many fields or nested models.
    """
    params = list(inspect.signature(fn).parameters.values())
    if len(params) < 1:
        raise TypeError(
            f"register_tool: handler for '{name}' must take at least one "
            f"argument; got {len(params)}"
        )
    ann = fn.__annotations__ if hasattr(fn, "__annotations__") else {}

    def _resolve(param: inspect.Parameter) -> Any:
        raw = ann.get(param.name, param.annotation)
        if isinstance(raw, str):
            return fn.__globals__.get(raw)
        return raw

    def _is_basemodel(t: Any) -> bool:
        return isinstance(t, type) and issubclass(t, BaseModel)

    pydantic_params = [p for p in params if _is_basemodel(_resolve(p))]

    if pydantic_params:
        # Shape 1: exactly one Pydantic input, no other parameters.
        if len(pydantic_params) > 1:
            raise TypeError(
                f"register_tool: handler for '{name}' has multiple Pydantic "
                f"BaseModel parameters ({[p.name for p in pydantic_params]}); "
                f"use a single Pydantic input or the flat-kwargs shape."
            )
        if len(params) > 1:
            raise TypeError(
                f"register_tool: handler for '{name}' mixes a Pydantic input "
                f"with other parameters; pick one shape."
            )
        return

    # Shape 2: flat kwargs. The SDK builds a flat arg_model with one
    # field per parameter. Every parameter must be typed.
    for param in params:
        resolved = _resolve(param)
        if resolved is inspect.Parameter.empty:
            raise TypeError(
                f"register_tool: handler for '{name}' parameter {param.name!r} "
                f"is missing an annotation; every parameter must be typed."
            )


def _extract_trace_id(args: tuple[Any, ...], kwargs: dict[str, Any]) -> str:
    """Pull a trace id out of the SDK's MCP context if it passed one.

    The SDK injects its own `Context` as a kwarg when the handler
    declares a parameter typed `Context`. Since our handlers don't
    declare such a parameter, this is usually a no-op — but we keep
    the hook so a future handler that opts into SDK context (e.g.
    `access_token`) still binds a trace id.
    """
    ctx = kwargs.get("context")
    if ctx is None:
        return "mcp-no-trace"
    # `Context` carries the request context; pull the request id if
    # available, else the session id, else fall back.
    request = getattr(ctx, "request_context", None)
    if request is not None:
        meta = getattr(request, "meta", None)
        if meta is not None:
            # `_meta` is the JSON-RPC `_meta` carrier; trace_id lives there.
            for key in ("trace_id", "request_id"):
                value = getattr(meta, key, None)
                if value is not None:
                    return str(value)
    session = getattr(ctx, "session_id", None) or getattr(ctx, "session", None)
    if session is not None:
        return str(getattr(session, "id", session))
    return "mcp-no-trace"
