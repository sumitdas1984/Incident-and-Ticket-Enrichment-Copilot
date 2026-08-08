# API Integration

> **Audience.** Reviewers, contributors, integrators wiring this
> project to a real industrial backend. Documents every external
> system the project talks to, the wire shape, and the auth /
> error-envelope conventions.

---

## 1. Alarm Management API

The orchestrator reaches the Alarm API **exclusively through MCP**
(hard constraint #1). The connector service
(`connectors/alarm-api/`) implements every endpoint the
orchestrator's chain calls. The Postman collection in
`postman/Alarm-API-Simulator.postman_collection.json` is the
authoritative wire-shape reference.

| Setting | Value | Source |
|---|---|---|
| Default URL | `http://localhost:8000` | `ALARM_API_BASE_URL` |
| Bearer token | `replace-me` placeholder | `ALARM_API_TOKEN` (SecretStr) |
| Container port | `8000` | `ALARM_API_PORT` |
| Auth header | `Authorization: Bearer <token>` | enforced by `connectors.alarm_api.auth.require_bearer` |
| Trace header | `X-Trace-Id: <uuid4 hex>` | forwarded from the MCP server's structlog contextvar |
| Retry policy | `ALARM_API_MAX_ATTEMPTS=3`, `ALARM_API_INITIAL_BACKOFF_S=0.25`, `ALARM_API_MAX_BACKOFF_S=2.0` | `connectors/alarm_api/alarm_api_client.py` |

### Endpoints the orchestrator reaches

Every endpoint is a thin Python wrapper in
`mcp-servers/alarm-management/alarm_api_client.py`. The MCP
server's tools call these wrappers; the wrapper builds the
upstream request, attaches auth + trace headers, and applies the
retry layer.

| Method | Path | MCP tool | Notes |
|---|---|---|---|
| `GET` | `/health` | — | Liveness. Always 200. |
| `GET` | `/ready` | — | Readiness — verifies upstream reachability. |
| `GET` | `/assets/search` | `search_assets` | Query: `query`, `site`, `unit`. |
| `GET` | `/alarms/{id}` | `get_alarm` | Single alarm by id. 404 → `AlarmNotFoundError`. |
| `GET` | `/alarms` | `summarize_alarms` | Time-bounded summary: `asset_id`, `since`, `until`. |
| `POST` | `/recommendations/operator-actions` | `recommend_actions` | Body: `alarm_id`, `include_*` flags. |
| `GET` | `/tickets/similar` | `search_similar_tickets` | Query: `text`, `site`, `asset_class`, `limit`. |

### Error envelopes

The connector surfaces upstream failures as:

| Condition | Envelope |
|---|---|
| `ALARM_NOT_FOUND` (404) | `{detail: {code: "alarm_not_found", message: "Alarm <id> not found."}}` |
| Generic 4xx / 5xx | `{detail: {code: "alarm_api_error", message: "<sanitised>"}}` |
| Bearer missing/wrong | `401` with `{detail: {code: "unauthorized", message: "..."}}` |
| Transport error | `503` with `{detail: {code: "alarm_api_unreachable", message: "..."}}` |

The MCP layer maps these to a sanitised `ToolInvocationError` —
no upstream URL, no body, no token.

### Retry semantics

The retry layer (`connectors/alarm_api/retry.py`) retries on:

- `httpx.ConnectError`, `httpx.ReadTimeout`, `httpx.ConnectTimeout`.
- HTTP 5xx.
- HTTP 429 (rate-limited).

It does **not** retry on 4xx (client error). The orchestrator's
`MCPClient` adds a second layer of retry on top; the two compose
cleanly because each layer's policy is independent.

---

## 2. Ticketing API (mock)

The orchestrator reaches the ticket-mock **through MCP** for the
gated create path. For previews (Feature 7.2), it goes directly
to the ticket-mock's `POST /tickets/preview` route (the orchestrator's
own route, not the MCP server). Both paths use the same
`Authorization: Bearer <TICKETING_API_TOKEN>`.

| Setting | Value | Source |
|---|---|---|
| Default URL | `http://localhost:8003` | `TICKETING_API_URL` |
| Bearer token | `replace-me` placeholder | `TICKETING_API_TOKEN` (SecretStr) |
| Container port | `8000` (the ticket-mock's own port) | The compose service `ticket-mock` exposes `8000`. |

### Routes the orchestrator exposes

| Method | Path | Source | Notes |
|---|---|---|---|
| `POST` | `/tickets/preview` | `apps/backend/routes.py:ticket_preview` | Pure projection via `connectors.ticket_mock.draft.build_draft(approved=False)`. No MCP, no chain, no audit. |
| `POST` | `/tickets/draft` | `apps/backend/routes.py:ticket_draft` | Builds a one-step `OrchestrationPlan` with `CREATE_TICKET_DRAFT`, runs through the chain. The chain routes to the ticketing MCP server's `create_ticket_draft` tool. |
| `GET` | `/tickets/search` | `connectors/ticket_mock/routers/tickets.py:search_tickets` | Exposed via the ticket-mock. Reached by the ticketing MCP's `search_tickets` tool. |
| `GET` | `/tickets/audit` | `connectors/ticket_mock/routers/tickets.py:tickets_audit` | Audit log (Feature 6.2). Used by reviewers / tests, not by the chain. |

### Approval gate (Feature 6.2)

`POST /tickets/draft` on the ticket-mock enforces the approval
gate. When `approved=False`:

```json
HTTP 403
{
  "detail": {
    "code": "approval_required",
    "message": "ticket creation requires explicit approval",
    "request_id": "<uuid4 hex>",
    "requires_approval": true
  }
}
```

The MCP server surfaces this as `ToolInvocationError`; the
orchestrator's chain records the rejection in the `TraceStep`
with `error="…(code=approval_required, request_id=…)"`. The
`request_id` matches the `x-trace-id` header on the inbound MCP
call so the approval trail is traceable end-to-end.

When `approved=True` the ticket-mock:

1. Persists the ticket via `TicketStore.create`.
2. Appends an audit row via `TicketStore.append_audit` (carrying
   `request_id`, `approved_by`, `approved_at`, `incident_id`,
   `action="create_ticket"`).
3. Returns 200 with the persisted ticket id + the `approval`
   block.

---

## 3. LLM providers

The orchestrator's planner calls the configured LLM through
`apps/backend/orchestrator/llm_client.py`. Two adapters:

- `OpenAILLMClient` — `openai` chat completions.
- `AnthropicLLMClient` — `anthropic` messages.

A `MockLLMClient` ships as the default and is the demo fallback —
it emits a deterministic one-RAG-step + compose plan based on
NL→slots extraction (no network, no API key).

### Configuration

| Setting | Default | Effect |
|---|---|---|
| `LLM_PROVIDER` | `mock` | `mock` / `openai` / `anthropic` |
| `LLM_API_KEY` | `replace-me` | Sent to the configured provider |
| `LLM_MODEL` | `gpt-4o-mini` | Model name passed to the provider |

The wiring layer (`apps/backend/wiring.py:build_orchestrator`)
constructs the LLM client from these three settings. Switching
from mock to a real provider is one config change.

### What the planner does

The `LLMPlanner` calls the LLM with:

- The tool catalog (names + one-line descriptions).
- `OrchestrationPlan.model_json_schema()` — Pydantic-generated
  JSON Schema for the discriminated-union plan payload.

The LLM returns a JSON object the orchestrator validates against
`OrchestrationPlan`. On first failure, the planner retries once
with corrective feedback.

---

## 4. Vector store

The build-time ingestion pipeline persists the RAG index to
`var/index/v1.pkl`. Two options for the build:

### Option A — In-memory (default, demo path)

The persisted `var/index/v1.pkl` is loaded by the orchestrator's
RAG step at boot. The orchestrator's runtime never talks to
ChromaDB — the index is an in-memory numpy array. This is the
default and keeps the runtime hermetic.

### Option B — ChromaDB (build-time)

A ChromaDB service runs in the Docker Compose stack
(`vector-store:8000`) for the **build** phase. `make ingest` can
write the corpus to ChromaDB instead of the pickle. The
runtime retrieval service supports both: pick the loader at
`apps/backend/wiring.py`.

| Setting | Default | Notes |
|---|---|---|
| `VECTOR_STORE_URL` | `http://localhost:8002` | ChromaDB HTTP URL. The compose service is `vector-store:8000`. |
| `DOCUMENT_PATH` | `./rag/documents` | The corpus directory. |
| `var/index/v1.pkl` | (gitignored) | The persisted on-disk index. Built by `make ingest`. |

See [`docs/rag-design.md`](docs/rag-design.md) for the full
ingestion, chunking, embedding, and retrieval design.

---

## 5. Auth + secrets

Every secret flows through `core.config.Settings` —
`pydantic-settings` `BaseSettings` with `env_file=".env"`.

### Project-wide rule

> No `os.getenv` outside `core/`. Enforced by CI:
> `.github/workflows/ci.yml` greps `apps/ mcp-servers/ rag/
> connectors/ tests/` for the literal string `os.getenv` and
> fails the build if any match is found.

### What lives where

| Setting class | Where it's read | Where it's used |
|---|---|---|
| App-internal settings (LLM provider, ports, URLs) | `core.config.Settings` | read via `get_settings()`; singleton + `cache_clear()` in tests |
| `ALARM_API_TOKEN` | `core.config.Settings.alarm_api_token` (SecretStr) | read by `mcp-servers/alarm-management/alarm_api_client.py` |
| `TICKETING_API_TOKEN` | `core.config.Settings.ticketing_api_token` (SecretStr) | read by `mcp-servers/ticketing/ticket_client.py` |
| `LLM_API_KEY` | `core.config.Settings.llm_api_key` (SecretStr) | read by `apps/backend/orchestrator/llm_client.py` |

`.env.example` ships with `replace-me` placeholders for every
secret (CLAUDE.md).

---

## 6. Error envelopes

Every backend route emits FastAPI's standard envelope:

```json
{ "detail": { "code": "<machine-readable>", "message": "<human-readable>" } }
```

Codes used across the project:

| Code | Origin | Meaning |
|---|---|---|
| `planner_error` | `apps/backend/routes.py` | The planner failed to produce a valid plan. 422. |
| `mcp_error` | `apps/backend/routes.py` | The chain's MCP step raised `MCPError`. 502. |
| `rag_error` | `apps/backend/routes.py` | The chain's RAG step raised `RAGError`. 502. |
| `orchestrator_error` | `apps/backend/routes.py` | A non-MCP / non-RAG error in the chain. 500. |
| `ticket_mcp_error` | `apps/backend/routes.py` | The ticket-mock rejected the create with a 403/4xx/5xx. 502. |
| `alarm_not_found` | `connectors/alarm_api` | 404 from the alarm-api. 404. |
| `alarm_api_error` | `connectors/alarm_api` | Generic 4xx / 5xx. Echoed status. |
| `alarm_api_unreachable` | `connectors/alarm_api` | Transport error. 503. |
| `unauthorized` | `connectors/alarm_api` | Bearer missing or wrong. 401. |
| `approval_required` | `connectors/ticket_mock` | The ticket-mock's gate. 403. |
| `backend_unreachable` | `apps/frontend/chat_client.py`, `ticket_client.py` | GUI's transport-error code. Surfaced to the GUI as `st.error("[code] message")`. |

### How the GUI surfaces them

Both `ChatClient.send` and `TicketClient.preview/create` raise
typed errors (`ChatError`, `TicketError`) that carry the
`code` and `message`. The UI renders them as
`st.error(f"[{code}] {message}")` or the modal renders them
in an error panel (Story 7.2.3).

---

## 7. Cross-references

- **Per-tool reference:** [`docs/mcp-tool-catalog.md`](docs/mcp-tool-catalog.md)
- **Architecture walkthrough:** [`docs/architecture.md`](docs/architecture.md)
- **RAG design:** [`docs/rag-design.md`](docs/rag-design.md)
- **Test surface:** [`docs/coverage-baseline.md`](docs/coverage-baseline.md)
- **Limitations:** [`docs/known-limitations.md`](docs/known-limitations.md)