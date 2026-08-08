# Architecture

> **Audience.** Evaluators, reviewers, future contributors. This
> document walks the system end-to-end: the 12 mandated layers, the
> request flow, auth boundaries, observability hooks, the MCP and
> RAG paths, and the hard constraints each layer enforces.
>
> A visual overview is in [`docs/architecture-diagram.png`](docs/architecture-diagram.png)
> (regenerated from the Mermaid source in
> [`docs/architecture-diagram.mmd`](docs/architecture-diagram.mmd)
> via `npx -y @mermaid-js/mermaid-cli -i docs/architecture-diagram.mmd -o docs/architecture-diagram.png -b transparent`).
> A per-tool reference for MCP is in
> [`docs/mcp-tool-catalog.md`](docs/mcp-tool-catalog.md). The RAG design
> lives in [`docs/rag-design.md`](docs/rag-design.md). Every external
> system the project touches is in
> [`docs/api-integration.md`](docs/api-integration.md).

---

## 1. The 12 layers

The brief (`Submission_and_Evaluation_Guidelines.md` § 9) requires
clean separation between these layers. We treat them as
**packages with one responsibility each**.

### 1.1 GUI — `apps/frontend/`

A Streamlit application (`apps/frontend/ui.py`) launched via the
candidate-developed launcher (`apps/frontend/__main__.py`). Two
columns: a chat column on the left, a workspace column on the
right (Feature 7.2). The workspace column renders the latest
assistant turn's structured Incident, the editable ticket draft,
the citations panel, the MCP execution trace panel, and the
"Create ticket" button that opens the confirmation modal
(hard constraint #3).

Two HTTP clients own the network:

- `apps/frontend/chat_client.py` — typed `POST /chat` client.
- `apps/frontend/ticket_client.py` — typed `POST /tickets/preview`
  + `POST /tickets/draft` client.

Both read `COPILOT_BACKEND_URL` through `core.config.get_settings()`
(no `os.getenv` outside `core/`).

### 1.2 Copilot orchestration — `apps/backend/orchestrator/`

The orchestrator is the only Python code that talks to the MCP
servers and the RAG service. Its pieces:

- `planner.py` — `MockPlanner` (general NL→slots extractor) and
  `LLMPlanner` (calls the configured LLM, validates JSON against
  `OrchestrationPlan.model_json_schema()`).
- `chain.py` — sequential `ChainRunner` that dispatches each
  plan step to the right tool. Partial-failure handling: a single
  tool error is recorded as `TraceStep(outcome="error")` and the
  chain continues.
- `mcp_client.py` — typed facade over `mcp`'s Streamable HTTP
  transport. Returns `(output, TraceStep)` for the chain.
- `rag_step.py` — wraps `rag.retrieval.RetrievalService.retrieve`.
- `answer.py` — `compose_answer` renders the final assistant text.
- `conversation.py` — in-memory `dict` keyed by `conversation_id`
  (uuid4), thread-safe.
- `incident.py` — `build_incident` template-projects the structured
  `Incident` payload from the chain's outputs (Feature 5.2).

### 1.3 MCP client — `apps/backend/orchestrator/mcp_client.py`

One `MCPClient` per MCP server. The orchestrator holds two
instances in the `OrchestratorBundle`:

- `mcp` — alarm-management MCP client (routes
  `TOOL_CALL`, `SEARCH_ASSETS`, `GET_ALARM`, `SUMMARIZE_ALARMS`,
  `RECOMMEND_ACTIONS`, `SEARCH_SIMILAR_TICKETS`).
- `ticket_mcp` — ticketing MCP client (routes `CREATE_TICKET_DRAFT`).

Both clients own an `httpx` connection pool, retry on transient
errors with exponential back-off, and surface every call as a
`TraceStep(outcome, duration_ms, retry_count, api_status_code)`.

### 1.4 MCP servers — `mcp-servers/`

Two candidate-developed servers, both built on the MCP Python SDK's
Streamable HTTP transport.

- `mcp-servers/alarm-management/` — 5 tools (`search_assets`,
  `get_alarm`, `summarize_alarms`, `recommend_actions`,
  `search_similar_tickets`); defaults to port `9000`.
- `mcp-servers/ticketing/` — 2 tools (`search_tickets`,
  `create_ticket_draft`); defaults to port `9001`.

Both expose `GET /health` (liveness) and `GET /ready`
(readiness — probes the upstream service). The MCP server is the
**only** component that opens an HTTP connection to the
Alarm API or the ticket-mock — hard constraint #1.

### 1.5 API / source-system connectors — `connectors/`

Two FastAPI services that stand in for real industrial systems:

- `connectors/alarm_api/` — implements the Postman collection in
  `postman/Alarm-API-Simulator.postman_collection.json` (asset
  search, alarm retrieval, summaries, recommendations, similar
  tickets). Bearer-token auth via `require_bearer` dependency.
- `connectors/ticket_mock/` — in-memory ticket store with search,
  draft (preview), draft (persisted), audit. Bearer-token auth.
  The approval gate (Feature 6.2) lives in the
  `POST /tickets/draft` route — returns 403 with
  `code="approval_required"` if `approved=False`.

### 1.6 RAG ingestion pipeline — `rag/ingestion/`

The build-time pipeline (`make ingest`):

1. **Loader** (`loader.py`) — walks `rag/documents/`, parses
   YAML front-matter, yields `LoadedDocument` records.
2. **Chunker** (`chunker.py`) — section-aware text chunking
   with metadata inheritance. Line-snaps to paragraph boundaries;
   configurable chunk size + overlap.
3. **Embedder** (`embedder.py`) — `DeterministicEmbeddingModel`
   (default, demo path, no network) or
   `SentenceTransformerEmbeddingModel` (production, downloads
   `all-MiniLM-L6-v2` from Hugging Face).
4. **Index** (`index.py`) — `InMemoryVectorIndex` using numpy
   for cosine similarity. Persists to `var/index/v1.pkl`.
5. **Pipeline** (`pipeline.py`) — the CLI: `python -m rag.inggestion`.

### 1.7 Retrieval service — `rag/retrieval/`

The runtime retrieval facade the orchestrator calls:

- `service.py` — `RetrievalService.retrieve(query, filters)` —
  embeds the query, filters by optional metadata, drops
  injection-blocklisted chunks (see `injection.py`), ranks by
  cosine similarity, classifies the confidence band
  (`high` ≥ 0.50 / `medium` 0.30–0.50 / `low` < 0.30 / `none` no
  hits).
- `citations.py` — `Citation` dataclass + 200-char excerpt
  truncation.
- `ranking.py` — `cosine_similarity`, `top_k`, `rank_candidates`.
- `injection.py` — `DEFAULT_INJECTION_PATTERNS` blocklist
  (regex; catches the canonical "ignore / override / disregard"
  vocabulary plus the two seeds in the corpus).

### 1.8 Domain models — `core/domain.py`

Frozen Pydantic v2 models. The orchestrator and the MCP servers
import from this single source of truth:

- `Alarm`, `AlarmSummary`, `OperatorRecommendation`
- `Asset`
- `Citation`, `Incident`, `TicketDraft`
- `TraceStep` (the row the chain produces on every tool call)
- `Severity` (`Literal["low", "medium", "high", "critical"]`)

### 1.9 Auth + configuration — `core/config.py`

`pydantic-settings` `BaseSettings` with `extra="ignore"`.
Every env var in `.env.example` is typed here. **The CI guard
`.github/workflows/ci.yml` greps the codebase for `os.getenv`
and fails the build if any module outside `core/` reads
environment directly.** That's hard constraint #5.

### 1.10 Observability — `core/logging.py`

Structlog with contextvars (`trace_id`, `conversation_id`,
`request_id`). Every log line in the request flow carries the
context, so the runner can grep one id and follow the call from
GUI → orchestrator → MCP server → connector.

### 1.11 Persistence

Two pieces of state, neither shared across processes:

- **`ConversationStore`** — in-memory dict keyed by
  `conversation_id`. Reset on every restart. Documented in
  `docs/known-limitations.md` § 1.
- **`var/index/v1.pkl`** — the persisted RAG index. Built by
  `make ingest`. Mounted into the `copilot-backend` container.

### 1.12 Tests — `tests/`

471 tests, organised as:

- `tests/unit/` — unit tests per layer (`tests/unit/core/`,
  `tests/unit/orchestrator/`, `tests/unit/rag/`,
  `tests/unit/connectors/`, `tests/unit/frontend/`, `tests/unit/alarm_api/`).
- `tests/integration/` — integration tests against the real
  `apps/backend.create_app()` + `connectors.alarm_api.create_app()`
  + `connectors.ticket_mock.create_app()` fixtures.
- `tests/e2e/test_full_workflow_mcp_rag.py` — Feature 8.1's
  end-to-end scenario: real MCP server + real RAG index +
  real orchestrator + the brief's § 7 scenario.

Static gates in `.github/workflows/ci.yml`: ruff, mypy, the
`os.getenv` guard, pytest with `--cov` flags.

---

## 2. Request flow

A `POST /chat` call walks nine steps. Every step has an audit
trail — either an MCP `TraceStep`, a RAG log line, or both.

```
1.  Streamlit UI        apps/frontend/ui.py            st.chat_input → render_input
2.  Chat client         apps/frontend/chat_client.py   POST /chat, sets x-trace-id
3.  FastAPI             apps/backend/routes.py:chat    binds trace_id + conversation_id
4.  Planner             orchestrator/planner.py        MockPlanner → OrchestrationPlan
5.  Chain runner        orchestrator/chain.py         waves → for each step:
6.  MCP tool call       orchestrator/mcp_client.py    MCPClient.call → TraceStep
7.  RAG retrieval       orchestrator/rag_step.py      RetrievalService.retrieve
8.  Compose answer      orchestrator/answer.py        assemble final answer text
9.  Build incident      orchestrator/incident.py      template-project → Incident
10. ConversationStore   orchestrator/conversation.py  append user + assistant turn
11. Response envelope   orchestrator/request.py       ChatResponse (frozen)
12. Streamlit render    apps/frontend/ui.py            render_history + render_workspace
```

For a `POST /tickets/draft` call (Feature 6.2 + 7.2):

```
1.  Streamlit UI        apps/frontend/ui.py            render_workspace → click "Create ticket"
2.  Ticket client       apps/frontend/ticket_client.py TicketClient.preview → /tickets/preview
3.  Orchestrator        apps/backend/routes.py        POST /tickets/preview
4.  build_draft         connectors/ticket_mock/draft   pure projection, no persistence
5.  Ticket client       apps/frontend/ticket_client.py user clicks Approve → TicketClient.create
6.  Orchestrator        apps/backend/routes.py        POST /tickets/draft
7.  Chain runner        orchestrator/chain.py         CREATE_TICKET_DRAFT → ticket_mcp
8.  MCP server          mcp-servers/ticketing/        create_ticket_draft tool
9.  Ticket-mock         connectors/ticket_mock/      POST /tickets/draft
10. Approval gate       connectors/ticket_mock        raises 403 if approved=False
11. Audit row           connectors/ticket_mock/store  append_audit → request_id matches trace
12. Response            apps/backend/routes.py        TicketDraftResponse with ticket_id + approval block
```

---

## 3. Auth boundaries

Three distinct bearer-token paths; the GUI never holds any of
them.

| Component | Holds | Reads from |
|---|---|---|
| `connectors/alarm_api/` | `ALARM_API_TOKEN` (validates inbound) | env via `core.config` |
| `connectors/ticket_mock/` | `TICKETING_API_TOKEN` (validates inbound) | env via `core.config` |
| `mcp-servers/alarm-management/` | `ALARM_API_TOKEN` (forwards upstream) | env via `core.config` |
| `mcp-servers/ticketing/` | `TICKETING_API_TOKEN` (forwards upstream) | env via `core.config` |
| `apps/backend/` | None (delegates to MCP) | — |
| `apps/frontend/` | None (delegates to backend) | — |

The MCP layer never logs the token. Every MCP error envelope
(`ToolInvocationError`) is sanitised — the upstream status code
is preserved but the URL, the body, and the token are not
included. Verified by
`tests/integration/mcp_server/test_tools.py::test_token_does_not_leak`.

---

## 4. Observability

Structlog contextvars bind three ids per request:

- **`trace_id`** — every inbound HTTP request gets a uuid4 hex
  (or the caller's `x-trace-id`). Bound at the route entry; every
  log line in the request carries it.
- **`conversation_id`** — minted by the orchestrator on the
  first chat turn; threaded through subsequent turns in the
  same conversation. Stored in `ConversationStore`.
- **`request_id`** — minted by the ticket-mock on every
  `POST /tickets/draft` call (gated or not). Bound to the audit
  row so `GET /tickets/audit` can be joined to the orchestrator's
  trace logs.

The MCP layer's `TraceStep` row carries every observability
field the GUI needs:

```json
{
  "server": "alarm-management",
  "tool": "summarize_alarms",
  "args": {"asset_id": "asset-boiler-b-101"},
  "output": { ... },
  "duration_ms": 42,
  "outcome": "success",
  "error": null,
  "retry_count": 0,
  "api_status_code": 200
}
```

---

## 5. The two paths

### 5.1 MCP path (alarm-api)

```
[Operator]                 [GUI]                  [Orchestrator]              [MCP server]              [Alarm API]
    │  "boiler b-101"          │                          │                            │                       │
    ├─────────────────────────►│                          │                            │                       │
    │                          │ POST /chat {message: …}  │                            │                       │
    │                          ├─────────────────────────►│                            │                       │
    │                          │                          │ planner → 5-step plan       │                       │
    │                          │                          │ chain.step[0] = TOOL_CALL   │                       │
    │                          │                          │ MCPClient.call(tool)       │                       │
    │                          │                          ├───────────────────────────►│                       │
    │                          │                          │                            │ GET /alarms?…         │
    │                          │                          │                            ├──────────────────────►│
    │                          │                          │                            │ 200 OK                │
    │                          │                          │                            │◄──────────────────────┤
    │                          │                          │ (output, TraceStep)        │                       │
    │                          │                          │◄───────────────────────────┤                       │
    │                          │                          │ … next step …              │                       │
    │                          │ ChatResponse{answer,…}  │                            │                       │
    │                          │◄─────────────────────────┤                            │                       │
    │ answer + citations       │                          │                            │                       │
    │◄─────────────────────────┤                          │                            │                       │
```

### 5.2 RAG path

```
[Orchestrator]              [RAG step executor]          [RetrievalService]              [In-memory index]
    │ RAG_STEP                       │                          │                            │
    │                                │ RetrievalService.retrieve(query, filters)         │
    │                                ├─────────────────────────►│                            │
    │                                │                          │ embed(query)                 │
    │                                │                          │ filter by metadata          │
    │                                │                          │ drop injection matches      │
    │                                │                          │ rank by cosine              │
    │                                │                          │ classify confidence         │
    │                                │ RetrievalResult          │                            │
    │                                │◄─────────────────────────┤                            │
    │ (citations, dropped_count)     │                          │                            │
    │◄───────────────────────────────┤                          │                            │
```

The retrieval service runs entirely in-memory against
`var/index/v1.pkl` (loaded once at orchestrator boot). The
ChromaDB service at `vector-store:8000` is **not** on the runtime
path — it's only used during `make ingest` for the build-time
vector-store option. The default demo path uses the persisted
in-memory index because it's hermetic (no network at runtime).

---

## 6. Hard constraints

These come from `CLAUDE.md` / the brief. Each maps to the file
that enforces it.

| # | Constraint | Enforced by |
|---|---|---|
| 1 | **MCP and RAG only via the wire** — orchestrator reaches the alarm-api exclusively through MCP. | `mcp-servers/alarm-management/alarm_api_client.py` (the only `httpx.AsyncClient` to the alarm-api); CI grep guard. |
| 2 | **MCP and RAG in the same workflow** — every `POST /chat` issues both. | `apps/backend/orchestrator/chain.py:ChainRunner.run` (mixes MCP and RAG steps in one plan). |
| 3 | **Ticket creation is gated by explicit approval** — the GUI's confirmation modal calls `POST /tickets/draft` with `approved=true`. | `apps/frontend/ui.py:_render_confirmation_modal` (the modal); `connectors/ticket_mock/routers/tickets.py:ticket_draft` (the 403 gate); `connectors/ticket_mock/store.py:append_audit` (the audit row). |
| 4 | **Every answer carries citations and MCP trace** — the response envelope carries both. | `apps/backend/orchestrator/request.py:ChatResponse`; `apps/backend/orchestrator/answer.py:compose_answer`; `apps/frontend/ui.py:render_history`. |
| 5 | **No hard-coded URLs / keys** — every secret flows through `core.config`. | `core/config.py:Settings`; CI grep guard `if grep -rn 'os\.getenv' apps/ mcp-servers/ rag/ connectors/ tests/ ...`. |
| 6 | **RAG defends against prompt injection** — `DEFAULT_INJECTION_PATTERNS` drops injection-bearing chunks. | `rag/retrieval/injection.py`; `tests/unit/rag/test_injection_defence.py`. |
| 7 | **Synthetic data only** — no real industrial system is reachable; the alarm-api is a simulator. | `connectors/alarm_api/seed.py:SEED_*`; `connectors/ticket_mock/seed.py:SEED_TICKETS`. |
| 8 | **No hard-coded answers to the sample questions** — the mock planner is a general extractor. | `apps/backend/orchestrator/planner.py:MockPlanner._extract`; `tests/unit/orchestrator/test_planner.py::test_mock_planner_handles_paraphrase_variants`. |

---

## 7. Cross-references

- **Per-tool reference:** [`docs/mcp-tool-catalog.md`](docs/mcp-tool-catalog.md)
- **RAG design:** [`docs/rag-design.md`](docs/rag-design.md)
- **External systems:** [`docs/api-integration.md`](docs/api-integration.md)
- **Design trade-offs:** [`docs/design-decisions.md`](docs/design-decisions.md)
- **Limitations:** [`docs/known-limitations.md`](docs/known-limitations.md)
- **Coverage:** [`docs/coverage-baseline.md`](docs/coverage-baseline.md)