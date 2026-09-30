# Plan — Feature 3.1: MCP Server (Story 3.1.1 + 3.1.2)

> **Context.** Epic 2 (Alarm Management Platform) is complete: the `connectors/alarm_api` simulator is reachable, validated against the Postman collection, and now ships in Docker Compose. Epic 3 must now deliver the candidate-developed MCP server that wraps the Alarm API. Without it, hard constraint #1 — "the copilot must call the Alarm Management API exclusively through the MCP server" — cannot be satisfied, and 40 % of the evaluation score is on the line.
>
> Feature 3.1 is the **scaffolding + registration** half of the MCP server: boot a real, typed, discoverable server with `tools/list`, health/readiness, and a clean plug-in point for the concrete Alarm tools that Feature 3.2 will register. Concrete tool implementations (asset search, alarm retrieval, etc.) are **out of scope here** — they land in Feature 3.2.

---

## 1. Goal

- `docker compose up --build` starts the `mcp-server` container; its `/health` returns 200.
- `GET /mcp/tools` (and the equivalent MCP `tools/list`) returns the full registered tool set with typed input/output schemas — empty or populated, but well-formed.
- Adding a new tool requires a single decorator call; no edit to the transport, the registry, or the request router.
- Handlers receive trace context (`trace_id`, `conversation_id`, `request_id`) so logs and the GUI trace pane line up.
- All test layers pass; `make lint` and `make test` are green locally; CI is green on the PR.

## 2. Approach

Five concrete edits. No new directories — we expand what's already there. No rewrite of `connectors/alarm_api` — the simulator stays the system of record and the MCP server is a thin typed wrapper.

### 2.1 `pyproject.toml` — add `mcp` as a project dependency

The candidate-developed MCP server must implement the MCP protocol. Add the official Python SDK to runtime deps so `mcp-servers/alarm-management/` can `from mcp.server.fastmcp import FastMCP` (the path the README already names):

```toml
    "structlog>=24.4",
    "mcp>=1.0",
```

Why SDK over a hand-rolled protocol: (a) the assignment package's recommended-stack text and the README both name FastMCP; (b) typed tool schemas (`@mcp.tool` with Pydantic `BaseModel` inputs) are exactly the discoverability contract the brief requires; (c) rolling our own JSON-RPC framing for MCP is yak-shaving we can't afford in the timebox.

Version pin `>=1.0` keeps the dependency compatible with both the local FastMCP API and the published 1.x line; we let `uv lock` resolve the minor version.

### 2.2 `mcp-servers/alarm-management/__main__.py` — boot FastMCP over Streamable HTTP

Replace the placeholder FastAPI app with a FastMCP server bound to a single FastAPI app via `FastMCP(...).streamable_http_app()`. The MCP server runs over Streamable HTTP on the existing `MCP_SERVER_PORT` (default 9000) — picked because the orchestrator already speaks HTTP to its dependencies (alarm-api, vector-store, ticket-mock) and adding a stdio subprocess would break docker-compose's existing health-gated service shape.

Shape (top of file):

```python
from __future__ import annotations
from mcp.server.fastmcp import FastMCP

from core.config import get_settings
from core.logging import bind_context, configure_logging, get_logger

settings = get_settings()
configure_logging(settings.log_level)
log = get_logger(__name__)
bind_context(service="mcp-server", mcp_server="alarm-management")

mcp = FastMCP("alarm-management", instructions=...)


# --- Health + readiness (separate plain FastAPI app merged via lifespan) ---
# The MCP app exposes /mcp/tools, /mcp/invoke, and (via streamable_http_app)
# a /mcp transport endpoint. Health/readiness need to stay on a plain route
# so docker-compose's `curl /health` keeps working without going through MCP.
```

The FastMCP app is mounted under `/mcp`; a sibling plain FastAPI app on the same port provides `/health` (no auth) and `/ready` (probes the alarm-api dependency). They're stitched together with `FastAPI.mount` or a `Lifespan` hook — chosen to keep `docker-compose.yml`'s healthcheck pointing at `http://localhost:9000/health` unchanged.

Readiness is a real probe (calls `GET <ALARM_API_BASE_URL>/health` with the configured token and a 500 ms timeout), not a static `200`. Reason: docker-compose's `depends_on: condition: service_healthy` gates `copilot-backend` on `mcp-server`, and a `mcp-server` that boots before the alarm-api is ready would otherwise accept traffic it can't fulfill.

**Transport choice justification (recorded in plan, repeated in `docs/mcp-tool-catalog.md`):** Streamable HTTP. The orchestrator already speaks HTTP. stdio would force the orchestrator into subprocess lifecycle management it doesn't otherwise need. Both transports are equally valid MCP; HTTP fits the existing compose network.

### 2.3 `mcp-servers/alarm-management/registry.py` — decorator + `@mcp.tool` bridge

The minimum registration path the brief requires is "typed schema in `tools/list`", "handler receives trace context", "auto-register on decoration". We layer a thin decorator over the SDK's `MCPServer.tool()` so handler code stays focused on business logic:

```python
@register_tool(server, name="search_assets", description="...")
async def search_assets(query: str, site: str | None = None) -> dict[str, object]:
    ...
```

The decorator:

1. validates the handler's signature at decoration time — the handler must take either one Pydantic `BaseModel` parameter (single-input shape) or several primitive-typed parameters (flat-kwargs shape); anything else raises `TypeError` so misuses fail fast (and locally),
2. calls `server.tool(name=..., description=..., structured_output=True)` to register with the MCP layer (so the SDK builds the typed `inputSchema` from the actual annotations),
3. patches the SDK's `Tool.fn` reference with a logging-and-error-mapping closure so `tool.called` / `tool.returned` fire and `httpx.HTTPError` is caught and re-raised as `ToolInvocationError`,
4. binds a trace_id (from the SDK's `Context`, or `"mcp-no-trace"` as the fallback) to the structlog context so nested log calls inside the handler inherit it.

Two shape decisions worth calling out:

* **No handler `ctx` parameter.** The plan originally proposed `async def handler(inp, ctx: ToolContext) -> Any` with `ctx` auto-populated. The MCP SDK's `find_context_parameter` matches any parameter typed `Context`, which would have made `ctx` a required argument in the protocol payload — the orchestrator couldn't satisfy it. We instead bind trace context to the structlog contextvar (via `core.logging.bind_context`) so any nested log call inherits it. This matches MCP's design intent: the SDK's `Context` is transport-level, not tool-contract-level.
* **Flat-kwargs in addition to single-Pydantic.** The SDK supports both — the single-Pydantic shape wraps the dict under the parameter name (`{"inp": {...}}`); the flat-kwargs shape produces a flat top-level schema (`{"query": ..., "site": ...}`). For tools with ≤ ~4 simple fields the flat shape is friendlier to orchestrators. `TestRegisterToolFlatKwargsShapeBuildsFlatSchema` locks the choice in.

Why a custom decorator instead of just `server.tool()`: the SDK's decorator doesn't know about our trace binding, our `httpx` error mapping, or our handler signature validation. Mixing them keeps the SDK's schema-generation (the part that's hard to re-implement) and replaces only the parts we need.

`ToolContext` (in `mcp_servers/alarm_management/context.py`) is a frozen dataclass so the typing is honest and testable, even though no handler currently consumes it directly.

### 2.4 `mcp-servers/alarm-management/health.py` — `/health` and `/ready` routes

Two endpoints, both unauthenticated:

- `GET /health` → `{"status":"ok","service":"alarm-management-mcp","version":<sha>}` always 200. Liveness.
- `GET /ready` → `503` if `ALARM_API_BASE_URL/health` doesn't return 200 within 500 ms; `200` otherwise. Readiness.

Why split liveness vs readiness: docker-compose's healthcheck is a liveness check (`/health`); we add `/ready` so the orchestrator can probe whether the MCP server can actually serve (its only critical dependency is the alarm-api).

Both routes return JSON, never log secrets, never expose the alarm-api token in any error message.

### 2.5 `tests/integration/mcp_server/` — server-level integration tests

New directory `tests/integration/mcp_server/`. Three test files, mirroring the `tests/integration/alarm_api/` shape (which uses in-process `TestClient`, not Docker):

- `test_health.py` — boots `create_app()`, asserts `/health` is 200 without auth, asserts `/ready` flips to 200 after the alarm-api dependency is reachable.
- `test_tools_list.py` — calls the MCP `tools/list` over the Streamable HTTP transport (using the official `mcp` client SDK against our in-process ASGI app via httpx2/ASGITransport); asserts the response is well-formed JSON, every registered tool has `name`, `description`, `inputSchema` (with `type: "object"`), and any schema referenced by a tool is retrievable.
- `test_registration.py` — adds an inline `@register_tool` fixture and asserts (a) it appears in `tools/list`, (b) the registered schema matches the Pydantic input model (round-trip via JSON Schema), (c) the trace context is propagated to the handler.

Each test uses an in-process ASGI client (FastAPI TestClient) pointed at our composed app — no Docker, no Newman. The integration marker is reserved for tests that *require* a running stack (we don't write any in this feature; the docker-compose-level smoke check is `make up` + curl `/health`, captured in the PR description).

`tests/integration/mcp_server/__init__.py` and `tests/integration/alarm_api/__init__.py` already exist as package markers; the new directory follows the same shape.

### 2.6 README + design-decision docs — leave for the umbrella PR

Not in this feature. The `docs/mcp-tool-catalog.md` and the README's "MCP server" section get populated when the concrete tools land in Feature 3.2 — populating them now with a single empty tool entry would just be edited again next feature.

## 3. Non-goals

- **No concrete Alarm tools in this feature.** `search_assets`, `get_alarm`, `summarize_alarms`, `recommend_actions` all land in Feature 3.2. Feature 3.1 ships the registration path, not the tool set.
- **No retries / timeouts / circuit breakers.** Those land in Feature 3.3 (MCP Reliability).
- **No MCP client.** That's Epic 3's other half (Features 3.4 / 3.5, called out in the parent Epic 3 acceptance criteria).
- **No GUI changes.** The trace-pane rendering of MCP execution is Epic 7.
- **No second MCP server** (the optional secondary server for ticketing). Out of scope for Feature 3.1; can be added later under `mcp-servers/optional-secondary-server/`.
- **No stdio subprocess transport.** Decision documented above; revisit only if a downstream MCP client genuinely can't speak HTTP.
- **No protocol-level negotiation.** The MCP SDK handles `initialize` / `notifications/cancelled`; we don't roll our own.

## 4. Critical files

- `pyproject.toml` — add `"mcp>=1.0"` and `"httpx>=0.27"` to `dependencies` (2 lines).
- `mcp-servers/alarm-management/__main__.py` — replace FastAPI placeholder with `MCPServer` + `make_asgi_app()` composition (rewrite of an existing file).
- `mcp-servers/alarm-management/registry.py` (NEW) — `@register_tool` decorator + signature validation + handler patching.
- `mcp-servers/alarm-management/context.py` (NEW) — `ToolContext` dataclass (defined but not yet wired into handlers; carried forward to Feature 3.2).
- `mcp-servers/alarm-management/health.py` (NEW) — `/health` and `/ready` routes attached via `MCPServer.custom_route()`.
- `mcp-servers/alarm-management/lifespan.py` (NEW) — Starlette-compatible `MCPServerLifespan` that drives `session_manager.run()` for the app's lifetime, plus `make_asgi_app()` helper.
- `mcp-servers/alarm-management/__init__.py` — update docstring and exports.
- `tests/integration/mcp_server/__init__.py` (NEW) — package marker.
- `tests/integration/mcp_server/test_health.py` (NEW).
- `tests/integration/mcp_server/test_tools_list.py` (NEW).
- `tests/integration/mcp_server/test_registration.py` (NEW).

`docker-compose.yml`, `Dockerfile`, `Makefile`, `core/`, `connectors/alarm_api/`, `.env.example`, and the Postman collections stay untouched.

## 5. Verification

1. **Local sanity (must pass before pushing):**
   ```bash
   uv sync
   uv run ruff check .
   uv run mypy apps rag connectors core   # mcp-servers stays excluded per pyproject.toml
   uv run pytest -ra                      # expect 99 prior + ~8 new = 107 green
   ```
2. **Smoke-test the server boots and responds:**
   ```bash
   uv run python -m mcp_servers.alarm_management &
   MCP_PID=$!
   curl -sf http://localhost:9000/health   # {"status":"ok",...}
   curl -sf http://localhost:9000/mcp/tools  # JSON tools/list response
   kill $MCP_PID
   ```
3. **End-to-end via Docker Compose** (recorded in PR description, not enforced in CI for this feature):
   ```bash
   docker compose up --build -d mcp-server
   docker compose exec mcp-server curl -sf http://localhost:9000/health
   docker compose down
   ```
   `/health` must come back 200 before `depends_on: condition: service_healthy` on `copilot-backend` would unblock it.
4. **Lint/types**: clean (see step 1).
5. **Trace propagation assertion** in `test_registration.py` — every call records `trace_id` in its log line; we assert via `caplog` / `structlog.testing.capture_logs`.

## 6. Rollback

Trivial. The placeholder FastAPI app in `mcp-servers/alarm-management/__main__.py` is committed in `developer`; reverting the file restores it. The new files (`registry.py`, `context.py`, `health.py`, three tests) are additive — `git rm` them and the service still boots, just with the placeholder back. No DB migrations, no API contract changes, no change to the alarm-api contract.

---

**Awaiting sign-off.** Reply "approved" to apply, or send edits.