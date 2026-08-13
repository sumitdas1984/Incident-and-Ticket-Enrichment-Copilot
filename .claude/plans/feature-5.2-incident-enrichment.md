# Plan — Feature 5.2: Incident Enrichment (Stories 5.2.1 + 5.2.2)

> **Context.** Feature 5.1 ships the orchestrator — the chain runner, MCP client, RAG integration, and `/chat` endpoint. The current output is a free-form text answer. Feature 5.2 turns that into a **structured `Incident` payload** that the GUI and the ticket-creation flow (Epic 6) consume. The brief's `Assignment_Use_Case.md` § 4 lists 6 expected workflow steps ("prepare a structured incident draft"); the current orchestrator covers steps 1, 2, 3, 5 (MCP + RAG) but step 4 (search similar tickets) is missing and step 6 (typed draft) is the explicit deliverable.
>
> **Parent issues:** Epic 5 — Copilot Intelligence — `#6`; Feature 5.2 — `#21`; Story 5.2.1 — `#51`; Story 5.2.2 — `#52`.
>
> **What we don't do here:** ticket creation (Epic 6), GUI rendering (Epic 7), LLM-driven incident generation (template-based composition is the right shape for the timebox), a real "ticket similarity" index (the alarm-api simulator returns a small static list).
>
> **What we explicitly do:** hard constraint #4 (citations + trace on every answer), hard constraint #1 (the new tool goes through the MCP server, never direct), the brief's step 4 (search similar tickets), and the brief's step 6 (typed `Incident` payload).

---

## 1. Goal

A FastAPI run that:

1. Exposes the brief's workflow step 4 (`search_similar_tickets`) as a new MCP tool on the alarm-management server. The tool calls a new `GET /tickets/similar` endpoint on the alarm-api simulator and returns a list of past-ticket summaries.
2. Adds a new `SEARCH_SIMILAR_TICKETS` step kind to the orchestrator's plan schema. The chain runner emits a `TraceStep` for the call and feeds the result into the `Incident` payload.
3. Defines an `IncidentBuilder` that takes the chain's outputs (intent, alarm context, recommendations, RAG excerpts, similar tickets, citations) and produces a typed `core.domain.Incident` payload by template projection.
4. Adds an optional `incident` field to the `ChatResponse` envelope. The field is present when the chain produced an incident draft; absent when the request was a casual chat (e.g. "what's the weather?").
5. E2E test: the brief's § 7 scenario runs end-to-end and the response carries a typed `Incident` with all six sections populated.

---

## 2. Approach

### 2.1 New MCP tool — `search_similar_tickets`

**Alarm-api simulator (`connectors/alarm_api/`):**

* New module `connectors/alarm_api/routers/tickets.py` with `GET /tickets/similar`. Query parameters: `text` (required, free-form), `site` (optional), `asset_class` (optional), `limit` (default 5). Returns a `TicketListResponse` with `items: list[TicketSummary]`, `total: int`.
* New `TicketSummary` model in `connectors/alarm_api/models.py`: `id: str, title: str, status: str, similarity: float, closed_at: datetime, resolution_excerpt: str`. The data lives in a small static list (3–5 entries) seeded in `connectors/alarm_api/seed.py` for determinism.
* Register the router in `connectors/alarm_api/app.py::create_app`.
* Tests in `tests/integration/alarm_api/test_tickets.py` — `tests/unit/core/test_models.py` already has the shape; we mirror the existing router test pattern.

**MCP server (`mcp-servers/alarm-management/`):**

* New tool in `mcp-servers/alarm-management/tools.py`:
  ```python
  @register_tool(server, name="search_similar_tickets", description="...")
  async def search_similar_tickets(text: str, site: str | None = None,
                                  asset_class: str | None = None,
                                  limit: int = 5) -> SimilarTicketsResponse:
      return await alarm_api_client.get_json("/tickets/similar", params={...})
  ```
* Input shape: `text` (required), `site` (optional), `asset_class` (optional), `limit: int = 5`. Output shape: `{"items": [...], "total": N}`.
* Tests in `tests/integration/mcp_server/test_tools.py` follow the existing pattern (mock transport + `AlarmApiClient`).

**Alarm-api client** (`mcp-servers/alarm-management/alarm_api_client.py`) — `get_json` already supports `params`. No client change.

### 2.2 New step kind — `SEARCH_SIMILAR_TICKETS`

**Plan schema (`apps/backend/orchestrator/plan.py`):**

Add a fourth payload type to the discriminated union:

```python
class SimilarTicketsPayload(BaseModel):
    model_config = _BASE_PLAN_CONFIG
    kind: Literal[PlanStepKind.SEARCH_SIMILAR_TICKETS] = PlanStepKind.SEARCH_SIMILAR_TICKETS
    text: str
    site: str | None = None
    asset_class: str | None = None
    limit: int = 5
```

`PlanStepKind` gains `SEARCH_SIMILAR_TICKETS = "search_similar_tickets"`. The union on `PlanStep.payload` is extended; the discriminated dispatch picks the right model.

**Chain runner (`apps/backend/orchestrator/chain.py`):**

The dispatcher gains a fourth branch — `SEARCH_SIMILAR_TICKETS` calls `mcp_client.call(tool="search_similar_tickets", args=payload.model_dump())`. The result is recorded as a `TraceStep` (the same way `TOOL_CALL` already does) and stashed in `prior_outputs[step_id]`. The incident builder reads `prior_outputs` for the `similar_tickets` field.

**Mock planner (`apps/backend/orchestrator/planner.py`):**

Emit a `SEARCH_SIMILAR_TICKETS` step when the chain includes an alarm-derived context (i.e. any plan that has a `summarize_alarms` step). The slot extractor already produces `asset_id` and `site`; those flow into the new step's args. The step is **always** emitted for incident-shaped requests — never for casual chat.

### 2.3 Incident builder

**New module (`apps/backend/orchestrator/incident.py`):**

```python
@dataclass(frozen=True)
class IncidentContext:
    """The chain's outputs projected into the Incident fields."""
    intent: str
    chain_result: ChainResult
    plan: OrchestrationPlan
    request: str

def build_incident(ctx: IncidentContext) -> Incident:
    """Template-based projection from ChainResult + plan to Incident."""
    ...
```

Builder logic:

* `id` → `uuid.uuid4().hex`.
* `created_at` → `datetime.now(tz=timezone.utc)`.
* `title` → first sentence of the intent + " — " + first non-empty chunk-excerpt section title.
* `summary` → `compose_answer(intent, prior_outputs, citations, ...)` (the existing composer).
* `severity` → derived from the highest-severity alarm in the chain's `summarize_alarms` output (falls back to `LOW`).
* `likely_cause` → first RAG excerpt's section header + first 200 chars.
* `recommended_actions` → from the `recommend_actions` MCP tool output (already typed in `core.domain.OperatorRecommendation`). Empty list when the tool didn't run.
* `citations` → `chain_result.citations` (already in `core.domain.Citation` shape).
* `similar_tickets` → from the `search_similar_tickets` step output. Empty list when the step didn't run.

The builder is **deterministic** — same chain outputs produce the same `Incident` (modulo `id` and `created_at`). No LLM call. The LLM-driven path is a one-line switch later.

**Test surface (`tests/unit/orchestrator/test_incident.py`):** ~10 tests covering each field's projection, empty-chain behaviour, missing-step fallback, and the round-trip with the E2E chain.

### 2.4 Response envelope

**`apps/backend/orchestrator/request.py`:** add `Incident` (already in `core.domain`) as an optional field on `ChatResponse`:

```python
class ChatResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    conversation_id: str
    answer: str
    citations: list[Citation] = Field(default_factory=list)
    trace: list[TraceStep] = Field(default_factory=list)
    rag_confidence: str = "none"
    dropped_count: int = 0
    intent: str = ""
    raw_payload: dict[str, Any] = Field(default_factory=dict)
    incident: Incident | None = None     # NEW
```

**`apps/backend/routes.py`:** after building the chain's `ChainResult`, call `build_incident(IncidentContext(...))` and attach to the response. The `incident` field is `None` when the chain didn't produce the required inputs (e.g. chat requests that don't have an alarm context).

**Polling rule:** the chain runner's existing partial-failure handling means a missing `recommend_actions` step or `search_similar_tickets` step produces empty lists in the `Incident` — the builder never raises. The `incident` field is present whenever the chain ran, absent when the chain was bypassed.

### 2.5 E2E workflow glue

**Brief's expected workflow:**
1. Retrieve and prioritize alarms through MCP — `summarize_alarms` (5.1).
2. Enrich the selected alarm with asset context — `search_assets` + `get_alarm` (5.1).
3. Retrieve recommended actions — `recommend_actions` (5.1).
4. Search similar tickets — `search_similar_tickets` (5.2 NEW).
5. Retrieve relevant support documents — RAG (5.1).
6. Prepare a structured incident draft — `IncidentBuilder` (5.2 NEW).

The chain runner's existing flow already runs steps 1, 2, 3, 5. Step 4 slots into the chain between the alarm-summary and the rag-query step. The orchestrator's `MockPlanner` is updated to emit the new step.

The `E2E acceptance` integration test in `tests/integration/test_orchestrator_e2e_acceptance.py` is extended:

* Mock `search_similar_tickets` to return 2 canned tickets.
* Run the brief's scenario; assert `body["incident"]` is not None.
* Assert each `Incident` field is populated (title, summary, severity, likely_cause, recommended_actions, citations, similar_tickets).

### 2.6 Tests

**Unit (`tests/unit/orchestrator/`):**

| File | Coverage |
|---|---|
| `test_incident.py` (NEW) | `IncidentBuilder` projects each field; empty-chain fallback; round-trip with the chain. |
| `test_plan.py` (extend) | `SimilarTicketsPayload` shape; discriminator dispatch. |
| `test_chain.py` (extend) | `SEARCH_SIMILAR_TICKETS` step dispatches to MCP. |

**Integration (`tests/integration/`):**

| File | Coverage |
|---|---|
| `tests/integration/alarm_api/test_tickets.py` (NEW) | `GET /tickets/similar` returns the seeded list; filters work. |
| `tests/integration/mcp_server/test_tools.py` (extend) | `search_similar_tickets` tool via the MCP wire. |
| `tests/integration/test_orchestrator_e2e_acceptance.py` (extend) | Brief scenario runs; response carries `incident` with all six sections. |

Expected test count delta: ~15 new tests. Total: ~344 + ~15 = ~359.

### 2.7 Non-goals

- **No LLM-driven incident generation.** Template-based projection per user decision.
- **No real ticket similarity index.** Static seeded list in the alarm-api matches the brief's "synthetic" data expectation.
- **No ticket creation.** Epic 6 (Feature 6.1) wires the actual ticket draft.
- **No GUI rendering.** Epic 7.
- **No new runtime dependencies.** `httpx`, `pydantic`, `mcp`, `fastapi` are all in `pyproject.toml`.

### 2.8 Dependencies

No new dependencies. The new `TicketSummary` model lives in `connectors/alarm_api/models.py` (already Pydantic). The new MCP tool uses `httpx` (already there).

---

## 3. Critical files

### New

- `connectors/alarm_api/routers/tickets.py` — `GET /tickets/similar` route.
- `apps/backend/orchestrator/incident.py` — `IncidentContext` + `build_incident`.
- `tests/unit/orchestrator/test_incident.py` — unit tests for the builder.
- `tests/integration/alarm_api/test_tickets.py` — integration tests for the new endpoint.

### Modified

- `connectors/alarm_api/models.py` — `TicketSummary`, `TicketListResponse` Pydantic models.
- `connectors/alarm_api/seed.py` — static seed list of 3–5 past tickets.
- `connectors/alarm_api/app.py` — register the tickets router.
- `mcp-servers/alarm-management/tools.py` — `search_similar_tickets` tool registration.
- `apps/backend/orchestrator/plan.py` — add `SimilarTicketsPayload` + extend `PlanStepKind` + extend the union.
- `apps/backend/orchestrator/chain.py` — dispatch `SEARCH_SIMILAR_TICKETS` to MCP.
- `apps/backend/orchestrator/planner.py` — `MockPlanner` emits the new step.
- `apps/backend/orchestrator/request.py` — add `incident: Incident | None` to `ChatResponse`.
- `apps/backend/routes.py` — call `build_incident(...)` and attach to the response.
- `tests/integration/mcp_server/test_tools.py` — extend with the new tool.
- `tests/integration/test_orchestrator_e2e_acceptance.py` — extend the assertion list.
- `docs/known-limitations.md` — note the static seed list, template-based composition, and the step-4 stub path.

### Untouched

- `mcp-servers/alarm-management/registry.py` — the new tool uses the existing `@register_tool` decorator.
- `mcp-servers/alarm-management/alarm_api_client.py` — `get_json` already supports the `params` arg.
- `apps/backend/orchestrator/mcp_client.py` — the MCP client is generic; the new tool is wired by name.
- `rag/`, `connectors/alarm_api/routers/{alarms,assets,recommendations}.py` — unchanged.

### Patterns to reuse (with file paths)

- `mcp-servers/alarm-management/registry.py::register_tool` — decorator for the new tool.
- `mcp-servers/alarm-management/retry.py::retry_with_policy` — wraps the new tool's `get_json` call (already automatic via `AlarmApiClient`).
- `core.domain.Incident` — the response payload model (already exists).
- `core.domain.Citation`, `TraceStep`, `OperatorRecommendation` — already-used in the chain.
- `apps/backend/orchestrator/answer.py::compose_answer` — re-used for the `Incident.summary` field.
- `connectors/alarm_api/routers/recommendations.py` — the router pattern to mirror for `tickets.py`.
- `connectors/alarm_api/seed.py::SEED_*` — the seed pattern for the static ticket list.
- `tests/integration/mcp_server/test_tools.py` — the integration test pattern for MCP tools.

---

## 4. Verification

1. **Static gates (must pass before push):**
   ```bash
   uv sync
   uv run ruff check .
   uv run mypy --explicit-package-bases apps rag connectors core
   uv run pytest -ra
   ```
   Expect: ~344 (post-5.1 baseline) + ~15 new = ~359 tests pass.

2. **Live smoke (incident draft):**
   ```python
   from fastapi.testclient import TestClient
   from apps.backend import create_app

   app = create_app()
   client = TestClient(app)
   r = client.post("/chat", json={"message": "Investigate Boiler Feed Pump 101 high-severity alarms over the last 90 days."})
   print(r.json()["incident"])
   ```
   Expect: `incident` is a dict with `id`, `title`, `summary`, `severity`, `likely_cause`, `recommended_actions`, `citations`, `similar_tickets`, `created_at`.

3. **Live smoke (casual chat):**
   ```python
   r = client.post("/chat", json={"message": "what's the weather?"})
   assert r.json()["incident"] is None
   ```
   The `incident` field is absent for non-incident requests.

4. **Live HTTP (docker-compose):**
   ```bash
   docker compose up --build
   curl -X POST http://localhost:8001/chat -H 'content-type: application/json' \
        -d '{"message":"Investigate Boiler Feed Pump 101 high-severity alarms over the last 90 days"}'
   ```
   Expect: 200, `incident` payload with `similar_tickets` populated from the alarm-api.

5. **Lint / type / docs:** clean (see step 1).

---

## 5. Rollback

Trivial. The new MCP tool, alarm-api endpoint, and orchestrator step are additive. Removing them is a `git revert`. The `ChatResponse.incident` field is optional and the existing GUI path ignores it.

---

## 6. Branch + PR

- Branch: `feature/feature-5.2-incident-enrichment` (off `developer` at `31571ee`, post-Feature-5.1 merge).
- Single PR closes `#51` (5.2.1) and `#52` (5.2.2).
- After merge: Epic 6 (ticket creation) and Epic 7 (GUI) can branch off.

---

**Awaiting sign-off.** Reply "approved" to apply, or send edits.
