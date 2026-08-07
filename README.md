# Incident-and-Ticket-Enrichment-Copilot

> An enterprise AI copilot that enriches industrial incidents by combining Alarm Management APIs (reached exclusively through a candidate-developed MCP server) with document-based RAG, producing evidence-backed incident tickets that only get created after explicit user confirmation.

> **Status:** this repository is in the **planning phase** of the round-1 ABB Senior Software Engineer – Copilot Integration assignment (deadline **9 August 2026**). The current tree holds the assignment package, the project plan, and the GitHub issue tracker; implementation lands under `apps/`, `mcp-servers/`, `rag/`, `connectors/`, and `tests/` per the layout in `ASSIGNMENT_BRIEF.md`.

---

## Use case

When a high-priority industrial alarm occurs, service engineers currently spend 20–30 minutes manually gathering the context needed for an incident ticket:

- the live alarm and the asset it belongs to
- similar historical tickets
- the relevant operating procedure / troubleshooting guide
- recommended next actions

This copilot collapses that into a single natural-language request:

> *"Prepare an incident for the highest-priority active alarm in EastRefinery."*

It returns a structured, evidence-backed incident draft — citations, MCP execution trace, and all — and only ever writes a ticket after the operator explicitly approves.

The full use case is defined in `Assignment_Use_Case.md` § 4.

## Capabilities

- **Natural-language incident requests** handled by a chat-style GUI with conversation context.
- **Asset, alarm, summary, and recommendation lookups** delivered as MCP tools over a candidate-developed MCP server connected to an Alarm Management API simulator.
- **Document retrieval** over a synthetic troubleshooting / operating-procedure corpus, with explicit citations and a prompt-injection guard.
- **Multi-step orchestration** that pipes each MCP tool's output into the next and integrates RAG in the same workflow — never as a separate demo.
- **Editable incident draft** with a confirmation modal — no ticket is ever written without explicit user approval.
- **Visible MCP execution trace and document citations** on every response, surfaced in the GUI.

## Tech stack

| Layer | Choice | Notes |
|---|---|---|
| Language | **Python 3.13+** | Per `pyproject.toml`. |
| Backend | **FastAPI** | Async, typed, Pydantic-native. |
| MCP server | **Candidate-developed** | `mcp-servers/alarm-management/` (Python, FastMCP). |
| Alarm API | **Candidate-developed simulator** | Implemented from `postman/Alarm-API-Simulator.postman_collection.json`. |
| RAG | Embeddings + vector index | Final model + store picked in `docs/rag-design.md`. |
| LLM | Provider-agnostic via env | Default picked in implementation. |
| GUI | TBD (Streamlit / Gradio / React) | Decision documented in `docs/design-decisions.md`. |
| Packaging | **Docker Compose** | `docker compose up --build` from a clean clone. |
| Tests | **pytest** | Unit + MCP + RAG + orchestration + one E2E. |
| CI | **GitHub Actions** | Format, lint, static analysis, all test layers, build. |

## MCP server

> To be populated when `mcp-servers/alarm-management/` ships. Will cover:
>
> - How to start the server independently (`make run-mcp`).
> - Tool list — name, purpose, input/output schemas, auth behaviour, error / timeout behaviour.
> - Pagination, retry-with-backoff, and API-error mapping guarantees.
> - Full contract in `docs/mcp-tool-catalog.md`.

The minimum tool surface (per `Assignment_Use_Case.md` § 2.1):

1. `search_asset(query, site?)` — typed asset resolution.
2. `get_alarm(alarm_id)` — single-alarm lookup.
3. `summarize_alarms(site?, asset?, severity?, since?, until?, limit)` — ranked alarm list with priority.
4. `recommend_actions(alarm_id)` — recommended operator actions + priority score.

## RAG

> To be populated when `rag/` ships. Will cover:
>
> - Corpus location (`rag/documents/`) and document types (troubleshooting guides, operating procedures, knowledge articles, resolution notes, escalation procedures).
> - Ingestion command (`make ingest`) — chunking, embeddings, indexing.
> - Chunk metadata schema.
> - Retrieval behaviour, citations, low-confidence and prompt-injection handling.
> - Full design in `docs/rag-design.md`.

## Quick start

```bash
# 1. Clone
git clone https://github.com/sumitdas1984/Incident-and-Ticket-Enrichment-Copilot.git
cd Incident-and-Ticket-Enrichment-Copilot

# 2. Configure
cp .env.example .env
# Edit .env and fill in: ALARM_API_TOKEN, MCP_SERVER_URL, LLM_API_KEY, VECTOR_STORE_URL, TICKETING_API_URL.

# 3. Run the full stack
docker compose up --build

# 4. Validate the Alarm API simulator against the Postman contract
make validate-api

# 5. Rebuild the RAG index from the committed corpus
make ingest

# 6. Run all tests
make test
```

Health checks on each service gate the application — visit `http://localhost:<frontend-port>` once Compose reports every service healthy.

## Configuration

All configuration is environment-driven. `.env.example` ships placeholders only — **no secrets are committed**.

| Variable | Purpose |
|---|---|
| `ALARM_API_BASE_URL` | URL of the Alarm API simulator (e.g. `http://alarm-api:8000`). |
| `ALARM_API_TOKEN` | Bearer token for Alarm API calls. |
| `MCP_SERVER_URL` | URL of the candidate-developed MCP server (e.g. `http://mcp-server:9000`). |
| `LLM_PROVIDER` | LLM provider name (e.g. `openai`, `anthropic`). |
| `LLM_API_KEY` | API key for the LLM provider. |
| `VECTOR_STORE_URL` | URL of the vector store (Chroma / FAISS / in-process). |
| `DOCUMENT_PATH` | Path to the document corpus (default `./rag/documents`). |
| `TICKETING_API_URL` | URL of the mock ticket service. |

## Build / run / test

The `Makefile` and `docker-compose.yml` will expose (planned):

```bash
make build         # build all Docker images
make up            # start the full stack
make down          # stop the stack
make test          # run all test layers
make lint          # ruff / mypy / formatter
make validate-api  # run the Alarm API Postman validation
make ingest        # rebuild the RAG index
```

CI runs formatting, lint, static analysis, every test layer, and build validation on every push.

## Sample interactions

> To be recorded once the E2E flow works. Will include:
>
> 1. **The mandatory E2E scenario** (`Assignment_Use_Case.md` § 7) — investigate recurring high-severity alarms for an asset over the last 90 days, identify contributing factors, retrieve the operating procedure, and return recommended actions with citations.
> 2. **A "happy path" ticket creation** showing the explicit user-confirmation modal.
> 3. **A failure / degraded scenario** showing graceful behaviour (e.g. low-confidence retrieval, MCP tool timeout).

Screenshots and the ≤ 10-minute demo video live under `docs/screenshots/` and a separately linked location.

## Architecture summary

Full version with diagram in `docs/architecture.md` and `docs/architecture-diagram.png`. At a glance:

```
┌──────────────────┐
│       GUI        │   chat + incident workspace + citations + MCP trace
└────────┬─────────┘
         │  HTTP
┌────────▼─────────┐
│  Copilot         │   intent + multi-step orchestration
│  Orchestration   │
└────┬───────────┬─┘
     │           │
┌────▼──────┐ ┌──▼───────────┐
│ MCP client│ │  RAG retriever│
└────┬──────┘ └──┬────────────┘
     │           │
┌────▼──────┐ ┌──▼───────────┐
│MCP server │ │ Vector index │
│ (we build)│ │  + documents │
└────┬──────┘ └──────────────┘
     │  (HTTP)
┌────▼──────────┐
│ Alarm API sim │
│  (we build)   │
└───────────────┘
```

The hard rule: **the orchestrator never calls the Alarm API directly.** All access goes through the MCP server, which is the only sanctioned bridge between the LLM and the enterprise system. MCP and RAG participate in the *same* business workflow, never as two disconnected demos.

The mandated 12-layer separation (per `Assignment_Use_Case.md` § 6) lives behind this diagram: GUI · orchestration · MCP client · MCP server · API connector · RAG ingestion · retrieval · domain models · auth/config · observability · persistence · MCP tools / RAG content.

## Assumptions

- The Alarm API simulator (`postman/Alarm-API-Simulator.postman_collection.json`) is the source of truth for the API contract — there is no real industrial system to integrate against.
- The mock ticket service is acceptable per the brief; no real Jira / ServiceNow / Azure DevOps integration is required.
- Embedding model and vector store choices will be locked in `docs/rag-design.md` once decided.
- LLM provider is configurable via env; default picked at implementation time.
- During local dev, mock providers are acceptable for tests to avoid burning LLM credits.

## Known limitations

> Tracked here as the system takes shape. Initial entries:
>
> - **Single-tenant:** no per-user auth on the chat UI yet (local-only).
> - **English-only:** corpus and LLM prompts are English.
> - **No streaming UI:** responses return all at once.
> - **Single-strategy chunking:** no per-document-type tuning in RAG.
> - **In-memory mock ticket service:** data is lost on restart.
> - **No persistent conversation storage:** context lives only in-process.
>
> New entries will be appended as they're discovered.

## Mandatory documentation

- `docs/architecture.md` + `docs/architecture-diagram.png`
- `docs/mcp-tool-catalog.md`
- `docs/rag-design.md`
- `docs/api-integration.md`
- `docs/design-decisions.md`
- `docs/known-limitations.md`

## Mandatory evidence

- `docs/screenshots/` — MCP tool discovery, MCP execution trace, RAG citations, one successful and one failure / degraded scenario.
- A ≤ 10-minute demo video uploaded to an accessible location, linked from the README.

## Related

- [`ASSIGNMENT_BRIEF.md`](ASSIGNMENT_BRIEF.md) — what's in this folder and how the assignment is structured.
- [`Assignment_Use_Case.md`](Assignment_Use_Case.md) — the full assignment brief.
- [`Submission_and_Evaluation_Guidelines.md`](Submission_and_Evaluation_Guidelines.md) — submission requirements and scoring framework.
- [`docs/03_project-plan.md`](docs/03_project-plan.md) — implementation roadmap.
- [GitHub Issues](https://github.com/sumitdas1984/Incident-and-Ticket-Enrichment-Copilot/issues) — tracked work across 9 Epics, 18 Features, 44 Stories.