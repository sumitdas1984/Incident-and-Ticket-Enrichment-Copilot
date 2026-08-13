# Feature 9.1 — Documentation

> **Context.** Feature 9.1 (issue #27) is the documentation
> capstone. The brief (`Submission_and_Evaluation_Guidelines.md`
> § 4 README checklist, § 5 MCP docs, § 7 RAG docs, § 9 architecture
> docs) accounts for 10 % of the evaluation score. Issue #27 has
> four sub-issues (#65, #66, #67, #68) corresponding to Stories
> 9.1.1–9.1.4. Required by Feature 9.2 (submission).
>
> Three of the six docs already exist (written incrementally
> during their corresponding feature work):
> - `docs/mcp-tool-catalog.md` (637 lines, Feature 3.2)
> - `docs/rag-design.md` (397 lines, Feature 4.x)
> - `docs/known-limitations.md` (188 lines, Features 4.x + 5.x)
> - `docs/coverage-baseline.md` (132 lines, Feature 8.1)
>
> The remaining work:
> - **README rewrite** — the current `README.md` is the planning-phase
>   stub ("this repository is in the planning phase"). It needs the
>   full § 4 checklist.
> - **`docs/architecture.md`** + **`docs/architecture-diagram.png`**
>   — don't exist yet.
> - **`docs/api-integration.md`** — doesn't exist yet.
> - **`docs/design-decisions.md`** — doesn't exist yet.
>
> **Outcome.** One PR that rewrites `README.md` and lands the three
> missing `docs/` files. The existing catalog / RAG design /
> known-limitations docs are reviewed for accuracy against the
> current codebase and patched where needed.

---

## File-by-file plan

### 1. `README.md` (REWRITE)

Replace the planning-phase stub with the § 4 README. Sections:

* **Title + tagline** — same as today's.
* **Use case** — taken from the brief; updated to reflect the
  actual implementation (was a forward-looking paragraph).
* **Capabilities** — feature list: chat, alarm MCP tools,
  document RAG with citations, structured incident, ticket draft
  with explicit approval modal, MCP+RAG working in one workflow.
* **Tech stack** — Python 3.13, FastAPI, Pydantic v2, MCP SDK
  1.x, ChromaDB (vector store), Streamlit 1.39, pytest,
  Docker Compose.
* **MCP server + tool list** — table pointing at the four
  alarm-management tools; link to `docs/mcp-tool-catalog.md`.
* **RAG corpus + ingestion** — `make ingest` command, link to
  `docs/rag-design.md`.
* **Architecture summary** — one paragraph + link to
  `docs/architecture.md` + the diagram PNG.
* **Quick start** — `make install` / `make ingest` / `make up`
  / `make down`. One-liners with the Docker Compose stack.
* **Configuration** — table of every env var (`ALARM_API_*`,
  `MCP_SERVER_*`, `TICKETING_*`, `VECTOR_STORE_*`, `LLM_*`,
  `APPROVAL_USER`, port overrides) sourced from `.env.example`.
* **Build / run / test commands** — `make` target list pulled
  from the `Makefile`.
* **Sample interactions** — two chat examples: the brief's
  mandatory scenario + a ticket-draft flow.
* **Documentation index** — links to every `docs/` file.
* **Assumptions** — link to `docs/known-limitations.md`.
* **License** — MIT (already in `pyproject.toml`).

### 2. `docs/architecture.md` (NEW)

Architecture document. Sections:

* **Layers** — list the 12 mandated layers (GUI, orchestrator,
  MCP client, MCP server, API connectors, RAG ingestion,
  retrieval service, domain models, auth/config, observability,
  persistence, tests) with one paragraph per layer explaining
  what lives there and where in the repo.
* **Request flow** — a step-by-step trace of one
  `POST /chat` call: Streamlit → FastAPI → planner →
  chain runner → MCP tool call (alarm-management MCP → alarm-api)
  → RAG retrieval → compose → response envelope.
* **Auth boundaries** — which component holds the alarm-api
  bearer token, which component signs the MCP request, what the
  GUI passes through.
* **Observability** — structlog context vars (request_id,
  conversation_id, trace_id), where they're bound, what shows
  up in every log line.
* **The two paths** — MCP path (alarm-api → MCP server →
  orchestrator) and RAG path (corpus → index → retrieval →
  orchestrator) drawn as text diagrams.
* **Hard constraints** — call out #1 (MCP-only path), #3
  (explicit approval), #4 (citations + trace on every
  answer), #6 (prompt-injection defence), #7 (synthetic data
  only) with the file paths that enforce them.

### 3. `docs/architecture-diagram.png` (NEW)

PNG architecture diagram. Generated from a Mermaid source kept
in `docs/architecture-diagram.mmd` so the PNG is regeneratable
without manual editing. The diagram covers the 12 layers + the
two paths. Tool: `npx @mermaid-js/mermaid-cli` (already on
npm paths via Node). Rendered via the `docs/` build step.

If Mermaid CLI is unavailable in CI, fall back to a hand-drawn
ASCII art embedded directly in `docs/architecture.md` (the text
diagrams in the same doc cover the structure anyway — the PNG
is the brief's § 9 requirement).

### 4. `docs/api-integration.md` (NEW)

API integration document. Sections:

* **Alarm Management API** — every endpoint the orchestrator
  reaches through MCP, with method/path/auth/notes. Cross-link
  to `docs/mcp-tool-catalog.md` for the per-tool detail.
* **Ticketing API (mock)** — `POST /tickets/draft` and
  `POST /tickets/preview` on the orchestrator + the ticket-mock
  routes behind them.
* **LLM providers** — OpenAI + Anthropic (key-only; no model
  list); how the mock LLM is the demo fallback.
* **Vector store** — ChromaDB at `VECTOR_STORE_URL`,
  HTTP API only, ephemeral persistence (`./chroma` volume).
* **Auth + secrets** — every secret flows through `core.config`;
  the project-wide rule that no `os.getenv` lives outside
  `core/` (CI enforces).
* **Error envelopes** — the `{detail: {code, message}}` shape
  every backend route emits; how the GUI surfaces it
  (`[code] message` format).

### 5. `docs/design-decisions.md` (NEW)

Design decisions document. ~10 short sections, each in the
shape "**Decision:** …  **Alternatives considered:** …  **Why
we chose this:** …".

Examples (the list will be drafted from what the codebase
actually contains, not invented):

* Mock planner vs LLM planner at startup.
* In-memory conversation store vs SQLite.
* Single-step chain runner vs DAG executor.
* Template-projected Incident vs LLM-generated prose.
* Ticket-mock as the only ticketing backend.
* Streamlit (Python-only) vs React (Node).
* ChromaDB over FAISS / pgvector / etc.
* Deterministic embedder as the demo path.

### 6. Patch existing docs (small accuracy reviews)

* `docs/mcp-tool-catalog.md` — confirm tool list matches the
  current `mcp-servers/alarm-management/tools.py`. (Added a 5th
  tool, `search_similar_tickets`, in Feature 5.2 — the catalog
  predates that.)
* `docs/rag-design.md` — confirm § 7 sections all present.
* `docs/known-limitations.md` — append any newly-discovered
  limitations (e.g. the orchestration layering one surfaced in
  Feature 7.2's plan review).

If those documents are already accurate, this step is a no-op
confirmation in the commit message.

### 7. `.env.example` (no change)

Already covers every env var. Cross-link from the README's
configuration section.

---

## Tests

This feature ships **documentation only** — no application
code changes. The static-gate tests stay green:

```
uv run ruff check .
uv run mypy --explicit-package-bases apps rag connectors core
uv run pytest -ra -m "not slow_embeddings"
```

No new tests are required (and none would meaningfully cover
prose). A documentation review is the verification step.

### Documentation review checklist

* `README.md` — every § 4 bullet present and accurate.
* `docs/architecture.md` — the request flow walks a `POST /chat`
  end-to-end.
* `docs/architecture-diagram.png` — exists, references every
  mandated layer.
* `docs/mcp-tool-catalog.md` — covers every tool registered in
  `mcp-servers/alarm-management/tools.py` and
  `mcp-servers/ticketing/tools.py` (the ticketing server was
  added in Feature 6.1; the catalog predates it).
* `docs/rag-design.md` — covers every § 7 section (source
  types, ingestion, extraction, chunking + metadata, embeddings,
  retrieval, ranking, filters, citations, low-confidence,
  prompt-injection defences, index refresh).
* `docs/api-integration.md` — every external system documented.
* `docs/design-decisions.md` — at least 8 decisions with
  alternatives.
* `docs/known-limitations.md` — refreshed for the current
  codebase.

---

## Verification

1. **Markdown lint (manual).** Every new doc file:
   - Has a top-level H1 title.
   - Every internal `docs/` link resolves (no broken anchors).
   - No claim that contradicts the code (e.g. tool names that
     don't exist, env vars that aren't in `.env.example`).
2. **Existing test suite.** `uv run pytest -ra` — 471 tests
   still pass.
3. **Link check.** A simple grep that every file referenced
   from `README.md` exists under `docs/`.
4. **Mermaid rendering.** `docs/architecture-diagram.png`
   exists. If the Mermaid CLI isn't on PATH locally, fall back
   to the ASCII-art section in `docs/architecture.md`.

---

## What this plan deliberately does NOT do

* No new runtime dependencies. `npm` for Mermaid is a build-time
  tool, not a runtime dep; if it's unavailable we ship the
  ASCII fallback.
* No changes to `docs/01/02/03_*.md` (project overview /
  understanding / plan). Those are internal planning docs and
  aren't part of the § 4-9 brief.
* No diagrams beyond the architecture one. The brief asks for
  one PNG; more diagrams belong in `docs/design-decisions.md`
  as ASCII art (lighter-weight, regeneratable).
* No changes to `docs/known-limitations.md` beyond appending
  any newly-discovered limitations from Features 6-8 (the
  file already covers 10 limitations from Features 4-5).

---

## Rollback

* Delete the three new docs + revert the README.
* Existing 471 tests stay green either way.