# Plan — Feature 6.1: Ticket Service (Stories 6.1.1 + 6.1.2)

> **Context.** Feature 5.2 ships the orchestrator's structured `Incident` payload. The brief's workflow step 7 ("require explicit approval before a ticket write operation") and step 8 ("return the created ticket identifier or draft preview") require a ticket service. The current repo has a placeholder `connectors/__main__.py` (the ticket-mock stub) but no real ticket capability. Feature 6.1 builds the ticket service end-to-end: a candidate-built mock ticket service in `connectors/`, a new MCP server in `mcp-servers/`, and the orchestrator wire-up. The approval gate (Feature 6.2) is stubbed here — `create_ticket` is callable but the orchestrator never invokes it without an explicit `approved=True` flag.
>
> **Parent issues:** Epic 6 — Ticket Management — `#7`; Feature 6.1 — `#22`; Story 6.1.1 — `#53`; Story 6.1.2 — `#54`.
>
> **What we don't do here:** approval UX (Feature 6.2), GUI confirmation modal (Feature 7.2), real ticket-system integration (Jira / Azure DevOps / ServiceNow / GitHub Issues).
>
> **What we explicitly do:** the brief's workflow step 5 (search similar tickets — already shipped in 5.2 via the alarm-api's `/tickets/similar` but the orchestrator should use the *ticket service's* search here for similar tickets, not the alarm-api's), step 7 (build the draft), step 8 (return ticket id). Hard constraint #3 (write operations require explicit user approval) — the service rejects `create_ticket` calls without `approved=True`. Hard constraint #1 (MCP-only via the wire) — the ticket tools are exposed via a new MCP server.

---

## 1. Goal

A Flow that:

1. Exposes two MCP tools on a new `mcp-servers/ticketing/` server: `search_tickets(query, site?, asset_id?, limit=5)` and `create_ticket_draft(incident: IncidentPayload, approved: bool)`.
2. The ticket service (`connectors/ticket-mock/`) backs the MCP tools: in-memory store with deterministic seed data, search by text + filters, draft generation from an `Incident`-shaped payload.
3. The orchestrator exposes a new endpoint `POST /tickets/draft` that takes a `conversation_id` + the previously-returned `Incident` and returns a `TicketDraft`. The endpoint calls the ticket MCP's `create_ticket_draft` only when the request carries `approved=True`.
4. The orchestrator's chain runner has a new `CREATE_TICKET_DRAFT` step kind. The mock planner emits it when the request is "create a ticket" or the chain has an `Incident` to act on.
5. The history now records ticket creation events with the ticket id; the GUI shows the id in the audit trail.

---

## 2. Approach

### 2.1 Ticket service (`connectors/ticket-mock/`)

**New package layout:**

```
connectors/ticket-mock/
├── __init__.py
├── __main__.py          # the existing placeholder moves here
├── app.py               # the FastAPI factory
├── models.py            # Ticket, TicketDraft, request / response models
├── store.py             # in-memory ticket store with deterministic seed
├── search.py            # search scoring (alarm id, asset id, free-text)
├── draft.py             # template-based draft generation from an Incident
└── routers/
    ├── tickets.py       # GET /tickets/search, POST /tickets/draft
    └── health.py        # /health
```

The existing `connectors/__main__.py` placeholder is replaced by `connectors/ticket-mock/__main__.py`. The FastAPI factory mirrors `connectors/alarm_api/app.py::create_app`.

**Models (`core.domain` extension):** `Ticket` (id, title, body, status, severity, asset_id, site, created_at, closed_at), `TicketDraft` (already exists in `core.domain.py` — uses it directly), `TicketSearchRequest`, `TicketDraftRequest`.

**Store (`connectors/ticket-mock/store.py`):** `TicketStore` class with an in-memory `dict[str, Ticket]`, seeded with 3 deterministic tickets (one resolved, one in-progress, one open). Thread-safe with a `threading.Lock`.

**Search (`connectors/ticket-mock/search.py`):** `search_tickets(query, site, asset_id, limit)` returns a deterministic top-N ranked list. Scoring: `1.0` for an exact asset_id match, `0.5` for a query-substring match, `0.2` for a tag match. Tied scores fall back to the seed's id order.

**Draft (`connectors/ticket-mock/draft.py`):** `build_draft(incident_payload, approved)` returns a `TicketDraft`. The body is composed of:
- the `Incident.summary` verbatim,
- a numbered list of `Incident.recommended_actions`,
- the `Incident.citations` rendered as a footer block.
- a `labels` list derived from `incident.severity` and `incident.similar_tickets`.

When `approved=False`, the service still produces the draft but tags it as `preview` (no ticket id). When `approved=True`, the service persists the ticket and returns the draft with `"ticket_id"` set.

**Router (`connectors/ticket-mock/routers/tickets.py`):**
- `GET /tickets/search` — query params: `text`, `site`, `asset_id`, `limit`. Returns `TicketListResponse`.
- `POST /tickets/draft` — body: `TicketDraftRequest` (with `incident` and `approved`). Returns `TicketDraftResponse` (with `ticket_id` when `approved=True`).

**App registration (`connectors/ticket-mock/app.py`):** `create_app()` factory — mirrors `connectors/alarm_api/app.py::create_app`. Health probe + tickets router.

### 2.2 New MCP server (`mcp-servers/ticketing/`)

**New package layout:**

```
mcp-servers/ticketing/
├── __init__.py
├── __main__.py          # the uvicorn entry, mirrors alarm-management/__main__.py
├── context.py           # the configure_logging / bind_context / lifespan
├── registry.py          # the @register_tool decorator (copied from alarm-management)
├── health.py            # /health, /ready
├── lifespan.py          # make_asgi_app helper
├── ticket_client.py     # the AlarmApiClient-equivalent for the ticket service
└── tools.py             # 2 tools: search_tickets, create_ticket_draft
```

**`tools.py`** registers two tools via the `@register_tool` pattern from `mcp-servers/alarm-management/registry.py`. The ticket client's `get_json` / `post_json` calls hit the ticket service's HTTP endpoints.

**`__main__.py`** mirrors `mcp-servers/alarm-management/__main__.py` — `mcp_server.streamable_http_app()` on `settings.ticketing_api_port`.

### 2.3 Orchestrator wiring

**New step kind (`PlanStepKind.CREATE_TICKET_DRAFT`):**

```python
class CreateTicketDraftPayload(BaseModel):
    model_config = _BASE_PLAN_CONFIG
    kind: Literal[PlanStepKind.CREATE_TICKET_DRAFT] = PlanStepKind.CREATE_TICKET_DRAFT
    incident: core.domain.Incident  # the structured incident payload
    approved: bool = False
```

**`PlanStep.payload` union extension.** Same discriminated-union pattern.

**Chain runner dispatch (`apps/backend/orchestrator/chain.py`):** new branch:
```python
elif step.kind == PlanStepKind.CREATE_TICKET_DRAFT:
    payload = step.payload
    output, ts = await self._call_mcp(
        step_id=step.step_id,
        tool="create_ticket_draft",
        args={"incident": payload.incident.model_dump(mode="json"), "approved": payload.approved},
        server="ticketing",
    )
```
The MCP client is configured with a second base_url (`ticketing_mcp_url`, default `http://localhost:9001`). The `call_mcp` helper is reused — the only change is the `server` field in the `TraceStep`.

**Mock planner (`MockPlanner`):** emit a `CREATE_TICKET_DRAFT` step when the request mentions "create a ticket" or includes the keyword "ticket". `approved=False` by default — the GUI sends `approved=True` when the user clicks the confirm button.

**New endpoint (`POST /tickets/draft`):** accepts a `TicketDraftRequest` with `conversation_id` and `incident`. The handler rebuilds the `IncidentContext` from the conversation store, calls `chain.run` with a one-step `OrchestrationPlan` (just the `CREATE_TICKET_DRAFT` step), and returns the `TicketDraft`.

**New endpoint (`POST /tickets/{ticket_id}`):** placeholder for now (the actual ticket-creation UX lands in Feature 7.2 with the GUI confirmation modal). Returns the ticket state.

### 2.4 Settings (`core/config.py`)

Add:
```python
ticketing_api_base_url: str = "http://localhost:8003"
ticketing_api_port: int = 8003
ticketing_mcp_url: str = "http://localhost:9001"
ticketing_mcp_port: int = 9001
```

`ticketing_api_*` is the ticket service's HTTP URL (the FastAPI service). `ticketing_mcp_*` is the MCP server's URL. The orchestrator's `MCPClient` is constructed with the ticketing URL.

### 2.5 Tests

**Unit (`tests/unit/`):**

| File | Coverage |
|---|---|
| `connectors/ticket-mock/test_store.py` (NEW) | In-memory store, deterministic seed, lock-safety. |
| `connectors/ticket-mock/test_search.py` (NEW) | Search scoring, ranking, top-N, filter combinations. |
| `connectors/ticket-mock/test_draft.py` (NEW) | Draft generation from an Incident, both `approved=True` and `approved=False` paths. |
| `apps/backend/orchestrator/test_ticket_step.py` (NEW) | Plan schema, dispatch, partial-failure. |

**Integration (`tests/integration/`):**

| File | Coverage |
|---|---|
| `tests/integration/ticket_mock/test_endpoints.py` (NEW) | `GET /tickets/search`, `POST /tickets/draft`, wire shape. |
| `tests/integration/mcp_server_ticketing/test_tools.py` (NEW) | `search_tickets` and `create_ticket_draft` via the MCP wire. |
| `tests/integration/test_orchestrator_ticket_e2e.py` (NEW) | `POST /tickets/draft` end-to-end against the running MCP server. |

Expected test count delta: ~15 new tests. Total: ~360 + ~15 = ~375.

### 2.6 Non-goals

- **No approval gate logic.** Stubbed: `create_ticket` is callable via the MCP tool but the orchestrator never invokes it without an explicit `approved=True` flag. The full gate lands in Feature 6.2.
- **No real ticket-system integration.** The mock ticket service. A follow-up PR swaps it for Jira / Azure DevOps / ServiceNow / GitHub Issues.
- **No ticket lifecycle endpoints.** `GET /tickets/{id}` is a placeholder; the GUI surfaces ticket ids from the response.
- **No new runtime dependencies.** Pydantic, FastAPI, httpx, mcp are all already in `pyproject.toml`.

### 2.7 Dependencies

No new runtime dependencies. The ticket service is a FastAPI app + in-memory store; the MCP server uses the same `httpx` client as the alarm-management MCP.

---

## 3. Critical files

### New

- `connectors/ticket-mock/__init__.py`
- `connectors/ticket-mock/__main__.py`
- `connectors/ticket-mock/app.py`
- `connectors/ticket-mock/models.py`
- `connectors/ticket-mock/store.py`
- `connectors/ticket-mock/search.py`
- `connectors/ticket-mock/draft.py`
- `connectors/ticket-mock/routers/__init__.py`
- `connectors/ticket-mock/routers/tickets.py`
- `connectors/ticket-mock/routers/health.py`
- `mcp-servers/ticketing/__init__.py`
- `mcp-servers/ticketing/__main__.py`
- `mcp-servers/ticketing/context.py`
- `mcp-servers/ticketing/registry.py`
- `mcp-servers/ticketing/health.py`
- `mcp-servers/ticketing/lifespan.py`
- `mcp-servers/ticketing/ticket_client.py`
- `mcp-servers/ticketing/tools.py`
- `tests/unit/connectors/ticket_mock/test_store.py`
- `tests/unit/connectors/ticket_mock/test_search.py`
- `tests/unit/connectors/ticket_mock/test_draft.py`
- `tests/unit/orchestrator/test_ticket_step.py`
- `tests/integration/ticket_mock/test_endpoints.py`
- `tests/integration/mcp_server_ticketing/test_tools.py`
- `tests/integration/test_orchestrator_ticket_e2e.py`

### Modified

- `core/config.py` — add `ticketing_api_*`, `ticketing_mcp_*` fields.
- `core/domain.py` — `Ticket` model (already exists partially; complete the model).
- `apps/backend/orchestrator/plan.py` — `CreateTicketDraftPayload` + `PlanStepKind.CREATE_TICKET_DRAFT` + union extension.
- `apps/backend/orchestrator/chain.py` — `CREATE_TICKET_DRAFT` dispatch.
- `apps/backend/orchestrator/planner.py` — `MockPlanner` emits the new step.
- `apps/backend/orchestrator/request.py` — `TicketDraftRequest` envelope.
- `apps/backend/routes.py` — `POST /tickets/draft` handler.
- `apps/backend/wiring.py` — second `MCPClient` for the ticketing base URL.
- `connectors/__main__.py` — replaced by the new package (or deleted, with `connectors/ticket-mock/__main__.py` as the new entry).
- `docs/known-limitations.md` — note the approved-flag stub, the in-memory ticket store, and the static seed.

### Untouched

- `mcp-servers/alarm-management/` — the alarm tools stay independent.
- `apps/backend/orchestrator/mcp_client.py` — already generic.
- `rag/`, `core/domain.py` (aside from the `Ticket` model) — unchanged.

### Patterns to reuse (with file paths)

- `connectors/alarm_api/app.py::create_app` — the FastAPI factory pattern.
- `connectors/alarm_api/routers/alarms.py` — the router pattern.
- `mcp-servers/alarm-management/__main__.py` — the uvicorn MCP entry.
- `mcp-servers/alarm-management/registry.py::register_tool` — the tool decorator.
- `mcp-servers/alarm-management/alarm_api_client.py` — the `get_json` / `post_json` HTTP client.
- `mcp-servers/alarm-management/lifespan.py::make_asgi_app` — the lifespan wrapper.
- `apps/backend/orchestrator/chain.py::_call_mcp` — the shared MCP dispatch helper.
- `apps/backend/orchestrator/incident.py` — the Incident builder produces the payload for the draft.
- `core/domain.py::TicketDraft` — the response envelope model.

---

## 4. Verification

1. **Static gates (must pass before push):**
   ```bash
   uv sync
   uv run ruff check .
   uv run mypy --explicit-package-bases apps rag connectors core
   uv run pytest -ra
   ```
   Expect: ~360 (post-5.2 baseline) + ~15 new = ~375 tests pass.

2. **Live smoke (ticket draft):**
   ```python
   from fastapi.testclient import TestClient
   from apps.backend import create_app

   app = create_app()
   client = TestClient(app)

   # Step 1: chat → get incident
   r = client.post("/chat", json={"message": "Investigate Boiler Feed Pump 101 high-severity alarms"})
   incident = r.json()["incident"]

   # Step 2: draft a ticket (approved=False for preview)
   r2 = client.post("/tickets/draft", json={"incident": incident, "approved": False})
   print(r2.json())
   ```
   Expect: 200, ticket draft with `labels`, `body`, `severity`, but no `ticket_id` (preview mode).

3. **Live smoke (approved=True):**
   ```python
   r3 = client.post("/tickets/draft", json={"incident": incident, "approved": True})
   print(r3.json())
   ```
   Expect: 200, ticket draft with `ticket_id` set (e.g. "TKT-2001").

4. **Live HTTP (docker-compose):**
   ```bash
   docker compose up --build   # alarm-api + alarm-mcp + ticket-mock + ticket-mcp + copilot-backend
   curl -X POST http://localhost:8001/chat -H 'content-type: application/json' \
        -d '{"message":"Investigate Boiler Feed Pump 101 high-severity alarms"}'
   curl -X POST http://localhost:8001/tickets/draft -H 'content-type: application/json' \
        -d '{"incident": <incident from above>, "approved": true}'
   ```
   Expect: 200, ticket draft with `ticket_id`.

5. **Lint / type / docs:** clean (see step 1).

---

## 5. Rollback

Removing the ticket service (`connectors/ticket-mock/`) and the MCP server (`mcp-servers/ticketing/`) is a multi-file delete. The orchestrator's `CREATE_TICKET_DRAFT` step is additive; reverting it removes the planner's emission and the chain runner's dispatch. The orchestrator's `POST /tickets/draft` endpoint is also additive.

---

## 6. Branch + PR

- Branch: `feature/feature-6.1-ticket-service` (off `developer` at `16a6dc6`, post-Feature-5.2 merge).
- Single PR closes `#53` (6.1.1) and `#54` (6.1.2).
- After merge: Feature 6.2 (approval gate) and Epic 7 (GUI) can branch off.

---

**Awaiting sign-off.** Reply "approved" to apply, or send edits.
