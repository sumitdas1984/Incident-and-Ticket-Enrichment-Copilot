# 03 — High-level architecture (the 12 layers)

> **What this answers.** When someone asks "how is the project
> structured", you should be able to name the layers, say what
> each does in one sentence, and point at the folder each one
> lives in. This doc is your vocabulary list.

---

## Mental model in 30 seconds

Think of the project as **three concentric rings**:

```
   ┌──────────────────────────────────────────────┐
   │  Outer ring: things the user touches          │
   │  ─ GUI (browser)                              │
   │  ─ External systems (alarm API, ticket API)   │
   ├──────────────────────────────────────────────┤
   │  Middle ring: the copilot's brain            │
   │  ─ Orchestrator (planner + chain runner)      │
   │  ─ MCP client                                 │
   │  ─ MCP servers (alarm + ticketing)            │
   ├──────────────────────────────────────────────┤
   │  Inner ring: cross-cutting + supporting       │
   │  ─ RAG ingestion / retrieval                  │
   │  ─ Domain models / config / logging           │
   │  ─ Tests                                      │
   └──────────────────────────────────────────────┘
```

The brief requires **12 distinct layers**, each with one
responsibility. The list below walks them in the order an
operator's request flows through them.

---

## The 12 layers, in request order

For each layer: **what it does** (one sentence) → **where it
lives** → **what it talks to**.

### Layer 1 — GUI

- **What:** The chat interface the operator sees in the browser.
- **Where:** `apps/frontend/` — `ui.py` (Streamlit app),
  `theme.py` (CSS helpers), `chat_client.py` (typed HTTP to
  `/chat`), `ticket_client.py` (typed HTTP to `/tickets/*`).
- **Talks to:** the copilot backend over HTTP.

### Layer 2 — Copilot orchestration

- **What:** The "brain" — receives the question, plans the
  work, runs the chain, composes the answer.
- **Where:** `apps/backend/orchestrator/` — `request.py`
  (FastAPI route), `planner.py` (intent + slots extractor),
  `chain.py` (chain runner), `plan.py` (plan schema),
  `answer.py` (composes final answer), `mcp_client.py`,
  `rag_step.py`, `ticket_step.py`.
- **Talks to:** MCP servers (for live data) + RAG retrieval
  service (for documents) + LLM client (for composition).

### Layer 3 — MCP client

- **What:** Typed facade over the `mcp` SDK. The orchestrator
  calls `.invoke(server, tool, args)` and gets back a typed
  response.
- **Where:** `apps/backend/orchestrator/mcp_client.py`.
- **Talks to:** the MCP servers.

### Layer 4 — MCP servers

- **What:** Two candidates-developed servers that translate MCP
  tool calls into API calls. One wraps the alarm API; one wraps
  the ticket API.
- **Where:** `mcp-servers/alarm-management/` (5 tools) and
  `mcp-servers/ticketing/` (2 tools).
- **Talks to:** the alarm API / ticket-mock via HTTP.

### Layer 5 — API / source-system connectors

- **What:** Thin HTTP clients + the in-container simulators
  themselves (alarm-api + ticket-mock).
- **Where:** `connectors/alarm_api/` (the FastAPI simulator
  with 15 endpoints + seed data), `connectors/ticket_mock/`
  (the ticket service with audit log + approval gate).
- **Talks to:** nothing external — these are in-container.

### Layer 6 — RAG ingestion pipeline

- **What:** The offline, one-time pipeline that turns the
  markdown corpus into a persisted vector index.
- **Where:** `rag/ingestion/` — `loader.py` (read .md files),
  `chunker.py` (split into passages), `embedder.py` (text →
  vector), `pipeline.py` (orchestrate), `index.py` (persist).
- **Talks to:** writes `var/index/v1.pkl`. Nothing else.

### Layer 7 — Retrieval service

- **What:** The online, per-request service that searches the
  index for relevant passages, filters out prompt-injection
  attempts, formats citations.
- **Where:** `rag/retrieval/` — `service.py` (the public API),
  `citations.py` (formatting), `ranking.py`, `injection.py`
  (blocklist), `low_confidence.py` (threshold logic).
- **Talks to:** the persisted index + (transitively) the LLM
  client when assembling the prompt.

### Layer 8 — Domain models

- **What:** The Pydantic types that flow through the system —
  `Alarm`, `Asset`, `Citation`, `Incident`, `TraceStep`,
  `ChatRequest`, `ChatResponse`.
- **Where:** `core/domain.py`.
- **Talks to:** nobody — just types.

### Layer 9 — Auth + configuration

- **What:** Singleton settings object read from environment.
  Every other module goes through `core.config.get_settings()`.
- **Where:** `core/config.py`.
- **Talks to:** `os.getenv` (this is the only place that's
  allowed to).

### Layer 10 — Observability

- **What:** structlog contextvars that tag every log line with
  `request_id`, `conversation_id`, `trace_id`, plus an MCP
  call log that captures `tool`, `duration_ms`, `outcome`,
  `api_status_code`.
- **Where:** `core/logging.py`, plus per-call sites that
  thread the contextvars.
- **Talks to:** stdout (structured JSON) and the `chat_client`
  / MCP client, which propagate trace headers.

### Layer 11 — Persistence

- **What:** Two stores — the in-memory conversation store
  (`apps/backend/orchestrator/conversation.py`) and the
  persisted RAG index (`var/index/v1.pkl`).
- **Where:** `apps/backend/orchestrator/conversation.py`,
  `var/index/`.
- **Talks to:** the orchestrator + retrieval service,
  respectively.

### Layer 12 — Tests

- **What:** 471 tests across unit, integration, and e2e.
- **Where:** `tests/{unit,integration,e2e}/`.
- **Talks to:** every layer above, via direct imports (unit)
  or via the FastAPI test client (integration / e2e).

---

## The mapping to the brief

The brief's `Submission_and_Evaluation_Guidelines.md` § 9 lists
the 12 mandated layers. This is a 1:1 mapping — when the
reviewer reads the brief's § 9 list, they should see exactly
the 12 layers above, in the same order.

---

## The shape, as a sentence

> "An operator types into the GUI; the orchestrator plans and
> runs a chain that interleaves MCP calls and RAG retrieval;
> the MCP servers wrap two in-container simulators; every
> cross-cutting concern (config, logging, types, persistence)
> lives in `core/`; tests cover all 12 layers; the whole thing
> runs in Docker Compose with seven services."

---

## Folder map (cheat sheet)

```
.
├── apps/
│   ├── frontend/             # Layer 1  (GUI)
│   └── backend/orchestrator/ # Layers 2, 3, 11 (brain + client + persistence)
├── mcp-servers/
│   ├── alarm-management/     # Layer 4  (alarm MCP server)
│   └── ticketing/            # Layer 4  (ticketing MCP server)
├── connectors/
│   ├── alarm_api/            # Layer 5  (alarm simulator)
│   └── ticket_mock/          # Layer 5  (ticket simulator)
├── rag/
│   ├── ingestion/            # Layer 6
│   └── retrieval/            # Layer 7
├── core/
│   ├── domain.py             # Layer 8
│   ├── config.py             # Layer 9
│   └── logging.py            # Layer 10
├── tests/                    # Layer 12
└── var/index/                # Layer 11 (RAG index, gitignored)
```

---

## If asked in the interview

**Q: "Walk me through the architecture."**

> Twelve layers. The GUI posts to the orchestrator; the
> orchestrator plans and runs a chain that interleaves MCP
> calls and RAG retrieval; the MCP servers wrap two
> in-container simulators; every cross-cutting concern — types,
> config, logging, persistence — lives in `core/`; 471 tests
> cover all of it.

**Q: "Why twelve layers — isn't that overkill for a 10-hour
project?"**

> The brief mandates them. But the layers aren't bureaucracy —
> each one has a single responsibility, which is what makes the
> hard constraints enforceable. The approval gate (layer 5) is
> a separate module from the GUI (layer 1) precisely so the
> brief's hard constraint #3 can be unit-tested in isolation.

**Q: "What would you change if you had more time?"**

> The wave-aware plan runner is built but only sequential
> execution is wired. With more time I'd turn on the DAG
> executor so independent MCP calls can run in parallel. See
> decision #3 in `docs/design-decisions.md`.

---

## Open questions for next time

- *How does the chain runner actually execute steps?* → Doc 04.
- *Why are the simulators in-container rather than mocked?* →
  Doc 06 + Doc 08 (decisions § 5, § 13).
- *What does the audit log look like?* → Doc 05.
