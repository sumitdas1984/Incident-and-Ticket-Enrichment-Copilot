# Incident-and-Ticket-Enrichment-Copilot

> An enterprise AI copilot that enriches industrial incidents by combining
> Alarm Management APIs (reached exclusively through a candidate-developed MCP
> server) with document-based RAG, producing evidence-backed incident tickets
> that only get created after explicit user confirmation.

The full use case is defined in `Assignment_Use_Case.md` § 4. The full
evaluation rubric and packaging requirements live in
`Submission_and_Evaluation_Guidelines.md`.

---

## Demo video

A 3:40 walkthrough of the end-to-end flow — five screens from empty
state to ticket created — is hosted on OneDrive:

> **Demo video link:**
> [https://1drv.ms/v/c/c68ba60bd1f54a88/IQCuXHQ3CNewTrJ1r6bmqSfVAeHkHT9fRVum4hWdQnYyRVo?e=H1C7Pe](https://1drv.ms/v/c/c68ba60bd1f54a88/IQCuXHQ3CNewTrJ1r6bmqSfVAeHkHT9fRVum4hWdQnYyRVo?e=H1C7Pe)

---

## Use case

When a high-priority industrial alarm occurs, service engineers currently
spend 20–30 minutes manually gathering the context needed for an incident
ticket:

- the live alarm and the asset it belongs to
- similar historical tickets
- the relevant operating procedure / troubleshooting guide
- recommended next actions

This copilot collapses that into a single natural-language request:

> *"Investigate recurring high-severity alarms for boiler B-101 in the last
> 90 days."*

It returns a structured, evidence-backed incident draft — citations, MCP
execution trace, and all — and only ever writes a ticket after the
operator explicitly approves in a confirmation modal (hard constraint #3).

---

## Capabilities

- **Natural-language incident requests** handled by a chat-style GUI with
  conversation context.
- **Alarm, asset, summary, and recommendation lookups** delivered as MCP
  tools over a candidate-developed MCP server (`mcp-servers/alarm-management/`)
  connected to an Alarm Management API simulator.
- **Document retrieval** over a synthetic troubleshooting /
  operating-procedure corpus, with explicit citations and a prompt-injection
  guard.
- **Structured incident draft** carrying the alarm context, asset, likely
  cause, recommended actions, similar tickets, and the RAG citations that
  support it.
- **Ticket draft with explicit approval** — the operator edits the draft in
  the GUI's workspace column, then approves a confirmation modal that gates
  the create-ticket call (hard constraint #3).
- **MCP and RAG in one workflow** — a single `POST /chat` call exercises
  both paths; every answer carries both citations and an MCP trace.

---

## Tech stack

| Layer | Choice |
|---|---|
| Runtime | Python ≥ 3.13 (per `pyproject.toml`) |
| HTTP / validation | FastAPI + Pydantic v2 |
| MCP SDK | `mcp` 1.x — Streamable HTTP transport |
| Embeddings | Deterministic embedder (demo); `sentence-transformers` 3.x (production) |
| Vector store | ChromaDB (HTTP API) |
| GUI | Streamlit 1.39+ (`st.chat_input`, `st.dialog`, `st.skeleton`) |
| Orchestration | Hand-rolled chain runner + planner; sequential v1, wave-aware |
| LLM | OpenAI / Anthropic adapters + `MockLLMClient` fallback |
| Tests | pytest + `httpx.MockTransport` + Streamlit `AppTest` |
| Container | Docker Compose (`docker compose up --build`) |

---

## MCP server + tool list

Two candidate-developed MCP servers wrap the Alarm API and the ticket-mock
respectively. Both speak Streamable HTTP. The orchestrator reaches the
alarm-api **exclusively** through MCP — that's hard constraint #1.

### `alarm-management` (port `9000`)

| Tool | Purpose |
|---|---|
| `search_assets` | Find assets by name fragment + optional site/unit filters. |
| `get_alarm` | Fetch a single alarm by id. |
| `summarize_alarms` | Time-bounded alarm summary for an asset. |
| `recommend_actions` | Priority score + recommended actions + rationale for an alarm. |
| `search_similar_tickets` | Free-form text + site/asset_class filters; grounds the incident draft. |

### `ticketing` (port `9001`)

| Tool | Purpose |
|---|---|
| `search_tickets` | Free-form text + asset_id/site/status filters against the ticket store. |
| `create_ticket_draft` | Generate (preview) or persist (approved) a ticket from an Incident payload. |

Full per-tool documentation — input/output schemas, auth, source-system
operations, error/timeout behaviour, example invocations — lives in
[`docs/mcp-tool-catalog.md`](docs/mcp-tool-catalog.md).

---

## RAG corpus + ingestion

The RAG corpus lives at `rag/documents/` — six synthetic-but-realistic
markdown files spanning five source types (`troubleshooting`,
`procedure`, `knowledge_article`, `resolution_note`, `escalation`). Two
documents deliberately embed prompt-injection seeds so the retrieval
service's defensive blocklist is exercised end-to-end.

To build the persisted index:

```bash
make ingest            # runs uv run python -m rag.ingestion
```

Output: `var/index/v1.pkl` (gitignored). The Docker Compose stack
mounts this file so the copilot backend can boot without re-ingesting.

Full RAG design — source types, ingestion, chunking, embeddings,
retrieval, ranking, filters, citations, low-confidence handling,
prompt-injection defences — lives in
[`docs/rag-design.md`](docs/rag-design.md).

---

## Architecture summary

The copilot is composed of **12 mandated layers** (per
`Submission_and_Evaluation_Guidelines.md` § 9):

1. **GUI** (`apps/frontend/`) — Streamlit chat + workspace column.
2. **Copilot orchestration** (`apps/backend/orchestrator/`) — planner +
   chain runner + RAG step executor.
3. **MCP client** (`apps/backend/orchestrator/mcp_client.py`) — typed
   facade over `mcp` SDK Streamable HTTP.
4. **MCP servers** (`mcp-servers/`) — `alarm-management` +
   `ticketing`.
5. **API / source-system connectors** (`connectors/`) — `alarm-api`
   simulator + `ticket-mock` service.
6. **RAG ingestion pipeline** (`rag/ingestion/`) — loader, chunker,
   deterministic / sentence-transformers embedder, in-memory vector
   index, persisted to `var/index/v1.pkl`.
7. **Retrieval service** (`rag/retrieval/`) — confidence bands,
   citation formatting, prompt-injection blocklist.
8. **Domain models** (`core/domain.py`) — `Alarm`, `Citation`,
   `Incident`, `TraceStep`, etc.
9. **Auth + configuration** (`core/config.py`) — singleton settings
   read from env; CI enforces no `os.getenv` outside this module.
10. **Observability** (`core/logging.py`) — structlog contextvars
    (`trace_id`, `conversation_id`, `request_id`).
11. **Persistence** — in-memory conversation store + `var/index/v1.pkl`
    for the RAG index.
12. **Tests** (`tests/`) — unit (471) + integration + e2e.

The end-to-end request flow, auth boundaries, and the MCP+RAG path
diagrams are in [`docs/architecture.md`](docs/architecture.md) and
[`docs/architecture-diagram.png`](docs/architecture-diagram.png).

---

## Quick start

The Docker Compose stack runs the full system from a clean checkout:

```bash
make install            # uv sync — Python deps + uv-managed venv
cp .env.example .env    # edit secrets; defaults are placeholders
make ingest             # build the RAG index once (writes var/index/v1.pkl)
make up                 # docker compose up --build -d
```

Then open `http://localhost:5173` for the GUI (Streamlit) and
`http://localhost:8001/health` for the copilot backend.

Tear down:

```bash
make down               # docker compose down -v
```

Run unit + integration tests locally:

```bash
make test               # uv run pytest -ra
make lint               # ruff + mypy + os.getenv guard
```

---

## Configuration

Every env var the system reads lives in `.env.example` (committed) and
flows through `core.config.Settings`. The CI guard
`.github/workflows/ci.yml` rejects any `os.getenv` outside `core/`.

| Var | Default | Purpose |
|---|---|---|
| `ALARM_API_BASE_URL` | `http://localhost:8000` | Alarm API simulator URL. |
| `ALARM_API_TOKEN` | `replace-me` | Bearer token for the Alarm API. |
| `ALARM_API_PORT` | `8000` | Container-internal port for the alarm-api service. |
| `MCP_SERVER_URL` | `http://localhost:9000` | Alarm-management MCP URL. |
| `MCP_SERVER_PORT` | `9000` | Container-internal port. |
| `TICKETING_API_URL` | `http://localhost:8003` | Ticket-mock service URL. |
| `TICKETING_API_TOKEN` | `replace-me` | Bearer token for the ticket-mock. |
| `TICKETING_MCP_URL` | `http://localhost:9001` | Ticketing MCP URL. |
| `TICKETING_MCP_PORT` | `9001` | Container-internal port. |
| `VECTOR_STORE_URL` | `http://localhost:8002` | ChromaDB URL (compose service: `vector-store:8000`). |
| `DOCUMENT_PATH` | `./rag/documents` | RAG corpus directory. |
| `LLM_PROVIDER` | `mock` | `mock` / `openai` / `anthropic`. |
| `LLM_API_KEY` | `replace-me` | LLM provider key (no-op when `LLM_PROVIDER=mock`). |
| `LLM_MODEL` | `gpt-4o-mini` | Model name passed to the configured provider. |
| `PLANNER_PROVIDER` | `mock` | `mock` / `llm`. The `mock` planner is a general NL→slots extractor. |
| `APPROVAL_USER` | `operator` | Identity stamped on every approved ticket creation (Feature 6.2). |
| `COPILOT_BACKEND_URL` | `http://localhost:8000` | The URL the Streamlit GUI POSTs `/chat` to. |
| `BACKEND_PORT` | `8001` | Host port mapping for the copilot-backend service. |
| `FRONTEND_PORT` | `5173` | Host port mapping for the frontend service. |

Full details (retries, timeouts, planner toggle, etc.) live in
[`docs/api-integration.md`](docs/api-integration.md).

---

## Build / run / test commands

The `Makefile` is the canonical source of truth:

| Target | Effect |
|---|---|
| `make install` | `uv sync` — Python deps + uv-managed venv. |
| `make ingest` | Build `var/index/v1.pkl` from `rag/documents/`. |
| `make up` | `docker compose up --build -d`. |
| `make down` | `docker compose down -v`. |
| `make test` | `uv run pytest -ra` (471 tests, 1 deselected). |
| `make lint` | ruff + mypy + the `os.getenv`-outside-`core/` guard. |
| `make validate-api` | Newman against the Alarm API Postman collections. |
| `make validate-api-only` | Run Newman without spawning the simulator. |
| `make build` | `docker compose build`. |
| `make lock` | `uv lock`. |
| `make sync` | `uv sync`. |

---

## Sample interactions

**Brief's mandatory § 7 scenario (Story 8.1.4):**

> *"Investigate recurring high-severity alarms for Boiler Feed Pump 101
> over the last 90 days. Identify likely contributing factors.
> Retrieve the relevant operating procedure and return recommended
> actions."*

```bash
curl -sX POST http://localhost:8001/chat \
  -H 'content-type: application/json' \
  -H "x-trace-id: $(uuidgen)" \
  -d '{
    "message": "Investigate recurring high-severity alarms for Boiler Feed Pump 101 over the last 90 days."
  }' | jq
```

The response carries a non-empty `answer`, a non-empty `citations`
list, a `trace` with the alarm-management MCP and RAG steps, and a
structured `Incident` payload.

**Ticket draft + approval flow (Features 6.2 + 7.2):**

```bash
# 1. Preview the draft the ticket-mock would produce.
curl -sX POST http://localhost:8001/tickets/preview \
  -H 'content-type: application/json' \
  -d '{
    "incident": {
      "id": "INC-9001",
      "title": "Boiler B-101 tube leak suspect",
      "summary": "Recurring high-temp alarms; inspect tube sheet.",
      "severity": "critical",
      "recommended_actions": ["Reduce feed rate to 80%", "Inspect lower tube sheet"],
      "similar_tickets": ["TKT-1042"]
    }
  }' | jq

# 2. Approve + persist — gates via the approval layer (hard constraint #3).
curl -sX POST http://localhost:8001/tickets/draft \
  -H 'content-type: application/json' \
  -d '{
    "incident": { ... same as above ... },
    "approved": true
  }' | jq
```

---

## Documentation index

| Doc | Audience | What it covers |
|---|---|---|
| [`docs/architecture.md`](docs/architecture.md) | Reviewers, contributors | The 12 layers, request flow, auth, observability, hard constraints. |
| [`docs/architecture-diagram.png`](docs/architecture-diagram.png) | Reviewers | Visual: 12 layers + MCP + RAG paths. |
| [`docs/mcp-tool-catalog.md`](docs/mcp-tool-catalog.md) | Orchestrator, GUI | Every MCP tool: name, schema, auth, source op, error/timeout, example. |
| [`docs/rag-design.md`](docs/rag-design.md) | Reviewers, contributors | Source types, ingestion, chunking, embeddings, retrieval, citations, prompt-injection defences, index refresh. |
| [`docs/api-integration.md`](docs/api-integration.md) | Reviewers, contributors | Every external system the project touches. |
| [`docs/design-decisions.md`](docs/design-decisions.md) | Reviewers | Rejected alternatives + rationale. |
| [`docs/known-limitations.md`](docs/known-limitations.md) | Reviewers | What's deliberate vs deferred, and what it'd take to lift each. |
| [`docs/coverage-baseline.md`](docs/coverage-baseline.md) | Reviewers, CI | Per-package coverage thresholds + the baseline snapshot. |
| [`docs/deployment-verification.md`](docs/deployment-verification.md) | Reviewers | § 9.2.1 docker-stack verification + brief's § 7 E2E through the running stack. |
| [`docs/submission-message.md`](docs/submission-message.md) | Submission | § 19 sharing checklist + § 20 submission message. |
| [`docs/screenshots/`](docs/screenshots/) | Reviewers | Demo screenshots (paths from the brief's § 18 placeholder). |

---

## Assumptions

- **Synthetic data only.** No real industrial system is reachable;
  the alarm-api is a simulator, the ticket-mock is in-memory, the
  RAG corpus is six markdown files. Hard constraint #7.
- **Demo path is hermetic.** `LLM_PROVIDER=mock` and a deterministic
  embedder mean the system runs without an API key. The
  production paths are one config switch each.
- **Streamlit for the GUI.** Chosen because the image stays
  Python-only (no Node / bundler). Story 7.2's workspace column +
  modal are well-supported by Streamlit 1.39's `st.dialog` and
  `st.skeleton`.

Full list in [`docs/known-limitations.md`](docs/known-limitations.md).

---

## License

MIT (per `pyproject.toml`).