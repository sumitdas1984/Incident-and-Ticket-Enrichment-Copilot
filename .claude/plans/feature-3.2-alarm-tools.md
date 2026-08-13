# Plan — Feature 3.2: Alarm Management Tools (Stories 3.2.1–3.2.4)

> **Context.** Feature 3.1 (PR #77, merged) scaffolded the candidate-developed MCP server with an empty `tools/list`. The LLM cannot actually reach the Alarm API yet — there are no tools. Feature 3.2 wires four production-quality tools onto the server:
>
> * `search_assets` — Story 3.2.1
> * `get_alarm` — Story 3.2.2
> * `summarize_alarms` — Story 3.2.3
> * `recommend_actions` — Story 3.2.4
>
> Each tool is a thin, typed wrapper over an alarm-api endpoint (`connectors/alarm_api/routers/{assets,alarms,recommendations}.py`). Hard constraint #1 (no direct alarm-api calls from the orchestration layer) becomes end-to-end satisfiable in this feature.
>
> Feature 3.3 (retries / timeouts / circuit breakers) is *out of scope here* — those land on top of these tools. Timeouts default to 5 s, retries are off; both are centralised in one place (`AlarmApiClient`) so 3.3 can flip them on without touching the four tool handlers.

---

## 1. Goal

`docker compose up` boots the full stack; the copilot can discover and invoke the four tools; each tool's `input_schema` is typed; each tool propagates the alarm-api bearer token; non-2xx alarm-api responses become structured MCP errors with no secret leakage; `docs/mcp-tool-catalog.md` documents each tool.

## 2. Approach

Five concrete edits. All new code lives in `mcp-servers/alarm-management/`; the alarm-api simulator is unchanged.

### 2.1 `mcp-servers/alarm-management/alarm_api_client.py` (NEW)

A single async client (`httpx.AsyncClient`) used by every tool handler. Centralises:

* **Base URL + auth header** — pulled from `core.config.get_settings()` (so `ALARM_API_BASE_URL` / `ALARM_API_TOKEN` flow through unchanged). The token is a `SecretStr`; we pass `Authorization: Bearer <get_secret_value()>` on every request and never log it.
* **Trace propagation** — `X-Trace-Id: <active_trace_id>` on every request. The active trace id comes from the structlog contextvar that Feature 3.1's `register_tool` binds before each call.
* **Timeouts** — single 5.0 s `httpx.Timeout(connect=5.0, read=5.0, write=5.0, pool=5.0)` constant. Feature 3.3 will swap this for a retry-with-backoff policy.
* **Error mapping** — translates `httpx.HTTPStatusError` to `ToolInvocationError` with a sanitised message (`"Upstream Alarm API returned status <code>."` — no token, no body, no URL with credentials). 404 from the alarm-api becomes a distinct `AlarmNotFoundError` (subclass of `ToolInvocationError`) so `get_alarm` and `recommend_actions` can return a precise message; all other non-2xx surface the generic envelope.
* **Lifespan** — the client is built once at server startup (`__main__.py`'s `MCPServerLifespan.__aenter__`) and closed on shutdown, so we get connection reuse across requests rather than TCP handshakes per call.

Public surface:

```python
class AlarmApiClient:
    def __init__(self, *, base_url: str, token: SecretStr, timeout_seconds: float = 5.0) -> None: ...

    async def get_json(self, path: str, *, params: dict[str, Any] | None = None) -> dict[str, Any]: ...
    async def post_json(self, path: str, *, json: dict[str, Any]) -> dict[str, Any]: ...

    @classmethod
    def from_settings(cls, settings: Settings) -> "AlarmApiClient": ...

class AlarmNotFoundError(ToolInvocationError):
    """Distinct envelope so get_alarm / recommend_actions can report
    "alarm_id not found" without leaking the alarm-api URL or token."""
```

The client attaches itself to the MCP server via a module-level singleton `get_alarm_api_client()` accessor. Tests build their own client via `from_settings()` against a stubbed alarm-api.

### 2.2 `mcp-servers/alarm-management/tools.py` (NEW)

The four tool handlers. Each handler is a flat-kwargs `@register_tool(server, name=..., description=...)` decorated coroutine (Feature 3.1's two accepted shapes; flat-kwargs fits ≤ ~4 simple fields cleanly).

#### 2.2.1 `search_assets` — Story 3.2.1

Maps to `GET /assets/search?query=...&limit=...&unit=...`.

```python
@register_tool(server, name="search_assets", description="Search industrial assets by name fragment...")
async def search_assets(
    query: str = Field(..., min_length=1, max_length=200, description="..."),
    site: str | None = Field(default=None, description="..."),
    unit: str | None = Field(default=None, description="..."),
    limit: int = Field(default=10, ge=1, le=100, description="..."),
) -> dict[str, object]:
```

Input validation: empty / oversized `query` rejected by Pydantic; `limit` clamped 1–100; `site`/`unit` optional. Response: `{"results": [...], "total": N, "query": "..."}` straight from the alarm-api.

#### 2.2.2 `get_alarm` — Story 3.2.2

Maps to `GET /alarms/{alarm_id}`.

```python
@register_tool(server, name="get_alarm", description="Fetch a single alarm by id...")
async def get_alarm(
    alarm_id: str = Field(..., min_length=1, max_length=128, description="..."),
) -> dict[str, object]:
```

404 from the alarm-api → `AlarmNotFoundError("Alarm <id> not found.")`. The MCP transport wraps that into `CallToolResult(isError=True, content=[TextContent("Alarm <id> not found.")])` — no token, no internal stack.

#### 2.2.3 `summarize_alarms` — Story 3.2.3

Maps to `GET /alarms?site=...&asset_id=...&severity=...&start_time=...&end_time=...&page=1&page_size=<limit>`.

The Story's flat-kwargs signature maps cleanly to the alarm-api's filter query — `since`/`until` become `start_time`/`end_time` ISO strings, `asset` becomes `asset_id`, `severity` is the single enum value, `limit` becomes `page_size`. We pin `page=1` and `sort_by=raised_at&sort_order=desc` so the orchestrator gets the most recent top-N.

```python
@register_tool(server, name="summarize_alarms", description="List ranked alarms with filters...")
async def summarize_alarms(
    site: str | None = Field(default=None, description="..."),
    asset: str | None = Field(default=None, description="..."),
    severity: Severity | None = Field(default=None, description="..."),
    since: datetime | None = Field(default=None, description="..."),
    until: datetime | None = Field(default=None, description="..."),
    limit: int = Field(default=25, ge=1, le=500, description="..."),
) -> dict[str, object]:
```

(Choosing `GET /alarms` over `POST /alarms/summary` — the latter returns aggregated buckets + KPIs, the former returns ranked items with priority. Story says "ranked alarms with priority" — `GET /alarms` is the right fit. The `POST /alarms/summary` endpoint is reachable from Feature 3.5 / orchestrator scripts if needed; not part of MCP surface for now.)

#### 2.2.4 `recommend_actions` — Story 3.2.4

Maps to `POST /recommendations/operator-actions` with body `{"alarm_id": <id>, "include_related": false, "include_asset_context": true, "include_historical_pattern": true}`.

```python
@register_tool(server, name="recommend_actions", description="Get recommended operator actions and priority score...")
async def recommend_actions(
    alarm_id: str = Field(..., min_length=1, max_length=128, description="..."),
) -> dict[str, object]:
```

We always set `include_asset_context` and `include_historical_pattern` to `True` because the alarm-api store includes them in `OperatorRecommendation` regardless; this gives the orchestrator the richest payload. `include_related` stays `False` for now (it's used by a separate `/related-alarms` endpoint that isn't in scope).

404 from the alarm-api → `AlarmNotFoundError`. Response: `{"alarm_id": ..., "priority_score": int, "actions": [...], "rationale": "..."}` straight from the alarm-api.

### 2.3 `mcp-servers/alarm-management/__main__.py` — wire the client into the lifespan

Update `MCPServerLifespan.__aenter__` to build and stash the `AlarmApiClient` on the server (e.g. `server.alarm_api_client = AlarmApiClient.from_settings(get_settings())`); `__aexit__` calls `await server.alarm_api_client.aclose()`. The four tool handlers read it via `get_alarm_api_client(server)`.

Tests against an in-process alarm-api (TestClient) get a `monkeypatch`-injected client — see §2.5.

### 2.4 `mcp-servers/alarm-management/__init__.py` — exports

Re-export `AlarmApiClient`, `AlarmNotFoundError`, `register_tool`, `ToolInvocationError`, and `get_alarm_api_client` so callers (and tests) can `from mcp_servers.alarm_management import ...`.

### 2.5 Tests — `tests/integration/mcp_server/test_tools.py` (NEW)

One file with the four tool-handler test groups. Each group exercises:

* **Schema** — `list_tools` includes the tool with the expected `name`, `description`, and a flat top-level `input_schema` (no `$defs` nesting) for the simple fields.
* **Happy path** — call_tool returns `isError=False` and the alarm-api response propagated through.
* **Auth header propagation** — recorded via `httpx.MockTransport`; assert the bearer token made it to the alarm-api call, but **never** assert against `ALARM_API_TOKEN.get_secret_value()` in any log/exception/transport-error path (the trace tests in `test_registration.py` already lock the "no token in logs" invariant).
* **Validation** — out-of-range `limit`, empty `query`, unknown `alarm_id` → structured MCP error, no 5xx.
* **Error mapping** — `httpx.HTTPStatusError(404)` → `AlarmNotFoundError`; other 4xx/5xx → generic `ToolInvocationError`; `httpx.ConnectError` → `ToolInvocationError` (already covered by `test_registration`).

Plus two cross-cutting tests:

* **All four tools in `tools/list`** — one test asserting every tool's name is present.
* **Trace header propagation** — every tool's recorded outgoing request carries an `X-Trace-Id` (the active structlog `trace_id`).

The tests use `httpx.MockTransport` rather than a real alarm-api so they run in-process in <1 s. `ALARM_API_TOKEN` stays a real-looking secret in the test client so we can assert it's sent (but the test asserts on the *header value's presence*, not the literal token).

### 2.6 Documentation — `docs/mcp-tool-catalog.md` (NEW)

Per `Submission_and_Evaluation_Guidelines.md` § 5 (Mandatory MCP Documentation), each of the four tools gets a section with: purpose, input schema, output schema, auth behaviour, source-system operation, error/timeout behaviour, example invocation + response.

`docs/mcp-tool-catalog.md` doesn't exist yet (planned in the umbrella docs). Writing it now is appropriate because it's the artefact the four tools produce, not the architecture.

## 3. Non-goals

- **No retries / circuit breakers.** Those are Feature 3.3. The `AlarmApiClient` has the *interface* to accept them later (`timeout_seconds` is a constructor arg; `get_json` can be wrapped with `tenacity` in 3.3) but the implementation is single-shot.
- **No streaming responses.** MCP supports them; we don't need them for these tools.
- **No advanced ops beyond the four stories.** Correlation / rationalization / flood analysis / KPI calculation stay reachable from `apps/backend` orchestration scripts that can call the alarm-api *via* MCP if needed — they're explicitly out of scope for this Feature per issue #16.
- **No MCP server client integration.** That's Epic 3's other half (the copilot side reaches MCP). This Feature only ships the server side.
- **No GUI changes.** Trace rendering for the new tools is a GUI concern (Epic 7).
- **No changes to the alarm-api simulator.** The alarm-api is the source of truth for the API contract; we wrap it, we don't change it.

## 4. Critical files

- `mcp-servers/alarm-management/alarm_api_client.py` (NEW) — `AlarmApiClient`, `AlarmNotFoundError`.
- `mcp-servers/alarm-management/tools.py` (NEW) — `register_tools(server)` function that registers all four handlers; the module is import-only.
- `mcp-servers/alarm-management/__main__.py` (modified) — `MCPServerLifespan.__aenter__` builds + attaches `AlarmApiClient`; calls `register_tools(server)`.
- `mcp-servers/alarm-management/__init__.py` (modified) — re-export new symbols.
- `tests/integration/mcp_server/test_tools.py` (NEW) — schema, happy-path, auth-header, validation, error-mapping, trace-propagation tests for all four tools.
- `docs/mcp-tool-catalog.md` (NEW) — per-tool documentation per § 5.

`connectors/alarm_api/`, `core/`, `apps/`, `postman/`, `docker-compose.yml`, `Dockerfile`, `Makefile`, `.env.example` stay untouched.

## 5. Verification

1. **Static checks** (must pass before pushing):
   ```bash
   uv sync
   uv run ruff check .
   uv run mypy apps rag connectors core
   uv run pytest -ra
   ```
   Expect: 116 prior + ~15 new = ~131 tests green.

2. **End-to-end via docker compose** (recorded in PR description):
   ```bash
   docker compose up --build -d
   docker compose exec mcp-server curl -sf http://localhost:9000/health
   docker compose exec alarm-api curl -sf http://localhost:8000/health
   # MCP client drives the four tools:
   uv run python -c "import asyncio
   from mcp import ClientSession
   from mcp.client.streamable_http import streamable_http_client
   async def go():
       async with streamable_http_client('http://localhost:9000/mcp') as s:
           async with ClientSession(s[0], s[1]) as session:
               await session.initialize()
               tools = await session.list_tools()
               print('tools:', [t.name for t in tools.tools])
               r = await session.call_tool('search_assets', {'query': 'Boiler'})
               print('search ok:', getattr(r, 'isError', None))
   asyncio.run(go())"
   docker compose down
   ```
   All four tool names appear; `search_assets` returns a successful `CallToolResult`.

3. **Lint / types**: clean (see step 1).

4. **Documentation check**: `docs/mcp-tool-catalog.md` is rendered, every tool has an entry, no TODO markers.

## 6. Rollback

Trivial. All new files are additive. The four tool handlers aren't registered if `register_tools(server)` isn't called from `__main__.py` — reverting that line returns the server to Feature 3.1's empty `tools/list` state. No DB migrations, no API contract changes, no changes to the alarm-api simulator.

---

**Awaiting sign-off.** Reply "approved" to apply, or send edits.