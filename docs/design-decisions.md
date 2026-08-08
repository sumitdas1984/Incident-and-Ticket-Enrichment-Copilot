# Design Decisions

> **Audience.** Reviewers asking "why did you build it this way?"
> Each section is a single decision with the alternatives that were
> considered and the trade-offs that picked the chosen path.
>
> The decisions here are made on **the project's terms**: a
> 10-14 hour timebox, a single contributor, no GPU, no
> real industrial system, and a self-contained demo path that runs
> without API keys. Different constraints could push the choice
> differently — call out the trade-offs so a future reviewer can
> re-evaluate.

---

## 1. Mock planner + Mock LLM as the demo default

**Decision.** The default planner is `MockPlanner` (a general
NL→slots extractor); the default LLM is `MockLLMClient`. The
production path is `LLMPlanner` + the configured provider; one
config switch (`LLM_PROVIDER`, `PLANNER_PROVIDER`).

**Alternatives considered.**

- Real LLM from day one. Rejected: requires an API key, makes the
  demo path non-hermetic, and the brief's timebox doesn't
  accommodate the iteration loop on prompt engineering.
- Hard-coded intent / script-style routing. Rejected: violates
  hard constraint #8 ("no hard-coded answers to the sample
  questions").

**Why we chose this.** A general NL→slots extractor produces
realistic plans on the brief's sample questions without an
external dependency. The LLM-driven path is the same code shape
— only the planner implementation differs — so swapping is a
one-line config.

---

## 2. In-memory conversation store

**Decision.** `ConversationStore` is a process-local `dict` keyed
by `conversation_id`.

**Alternatives considered.**

- SQLite (`conversation.db`). Rejected: adds a native dep and
  doesn't match the brief's "rebuildable from a clean checkout"
  posture.
- Redis. Rejected: requires a separate service in the compose
  stack; the brief's timebox doesn't fit the configuration cost.

**Why we chose this.** The conversation store's API is small
(append / get_or_create / get_messages). Swapping to SQLite is a
one-file change documented in
`docs/known-limitations.md` § 1. Conversations are not the
system of record — they're an audit trail — so losing them on
restart is acceptable for the demo.

---

## 3. Sequential chain runner

**Decision.** `ChainRunner.run` executes steps in order. The plan
already supports a wave-aware structure (`PlanStep.waves`), but
v1 runs all waves sequentially.

**Alternatives considered.**

- DAG executor with concurrent step dispatch. Rejected: adds
  complexity (cancellation, error containment across tasks)
  that the brief's demo doesn't need.
- Step-by-step with persistent state. Rejected: the demo doesn't
  need to survive crashes mid-chain.

**Why we chose this.** The brief's example workflow is linear
(asset → alarm → RAG → compose). Sequential execution matches
the actual demo shape; the wave structure in `PlanStep` keeps the
door open for parallelism without committing to it now.

---

## 4. Template-projected Incident (no LLM prose)

**Decision.** The structured `Incident` payload is built by
`apps/backend/orchestrator/incident.py:build_incident`, which
projects fields from the chain's outputs — title from the
incident asset / alarm, summary from the recommended_actions,
severity from the highest-severity alarm, similar_tickets from
the `search_similar_tickets` step output.

**Alternatives considered.**

- LLM-generated prose for the Incident. Rejected: adds latency,
  depends on the configured LLM provider, and makes the
  acceptance test for "incident shape" depend on LLM output
  stability.
- Strictly raw alarm-api output (no projection). Rejected:
  exposes alarm-api internals to the GUI.

**Why we chose this.** The template projection is deterministic
and testable. The LLM-driven path can override the prose fields
later without changing the wire envelope — the planner already
emits a `ComposePayload` that the answer composer can fill in.

---

## 5. Ticket-mock as the only ticketing backend

**Decision.** The orchestrator's `POST /tickets/draft` reaches the
ticket-mock (`connectors/ticket_mock/`) via a candidate-developed
MCP server (`mcp-servers/ticketing/`). No real ticketing vendor
is wired.

**Alternatives considered.**

- Real Jira / Azure DevOps / ServiceNow integration. Rejected:
  the brief explicitly allows a mock; real integration would
  exceed the timebox and require credentials the assignment
  package doesn't ship.
- Direct orchestrator → ticket-mock HTTP (skip the MCP layer).
  Rejected: violates the "MCP for write operations too" pattern;
  every persisted write should go through the same protocol as
  every read so the audit trace is uniform.

**Why we chose this.** A mock backend keeps the system
self-contained. The MCP wrapper is one layer that an integrator
would replace with a real-vendor adapter — the orchestrator
doesn't change.

---

## 6. Streamlit for the GUI

**Decision.** The GUI is a Streamlit application.

**Alternatives considered.**

- React (per the brief's allow-list). Rejected: requires a Node
  build chain in the Docker image, doubles the image size, and
  the timebox doesn't fit building a TypeScript toolchain from
  scratch.
- Gradio. Rejected: chat primitives are less rich than
  Streamlit's `st.chat_input` / `st.chat_message`, and the
  workspace layout (two-column, modal) is more awkward.
- FastAPI templates + hand-rolled JS. Rejected: more code, same
  outcome.

**Why we chose this.** Streamlit is Python-only, ships the chat
primitives the brief calls for, supports `st.dialog` (Feature
7.2's confirmation modal) and `st.skeleton` (Story 7.2.3's
loading state), and keeps the Docker image lean — no Node,
no bundler, no separate build stage.

---

## 7. ChromaDB at build-time, in-memory numpy at runtime

**Decision.** The build-time ingestion pipeline can use ChromaDB
(or the in-memory index). The runtime retrieval service uses the
in-memory numpy index loaded from `var/index/v1.pkl`.

**Alternatives considered.**

- ChromaDB at runtime (every query is a network round-trip).
  Rejected: adds an HTTP hop on the hot path for no functional
  benefit — the persisted numpy array is small enough to fit in
  memory and lookup is faster.
- FAISS. Rejected: native dep, no metadata-filtering parity with
  ChromaDB's API; we don't need FAISS's scale.
- pgvector / Qdrant / Weaviate. Rejected: add a service to the
  compose stack the brief doesn't require.

**Why we chose this.** A 6-document corpus fits comfortably in
memory. The ChromaDB service stays in compose for the build
pipeline and the option of runtime ChromaDB queries (the
retrieval service supports both). See
[`docs/rag-design.md`](docs/rag-design.md).

---

## 8. Deterministic embedder as the demo path

**Decision.** The default embedder is `DeterministicEmbeddingModel`
— a small, hand-rolled model with no network. The production
embedder is `SentenceTransformerEmbeddingModel`
(`sentence-transformers/all-MiniLM-L6-v2`).

**Alternatives considered.**

- SentenceTransformer only. Rejected: requires a Hugging Face
  download on first use, and the CI runner gets rate-limited
  (HTTP 429) — see `tests/unit/rag/test_embedder.py`'s marker.
- OpenAI embeddings. Rejected: requires an API key.

**Why we chose this.** The deterministic embedder is
side-effect-free and runs in CI without network access. The
production path is a one-config-switch. The embedder interface
is identical so swapping is transparent.

---

## 9. Single planning step (no separate prompt-engineering module)

**Decision.** The LLM planner's prompt is constructed inline in
`apps/backend/orchestrator/planner.py:LLMPlanner._build_prompt`.
No separate prompt-engineering module, no prompt versioning.

**Alternatives considered.**

- A `prompts/` package with versioned Jinja templates. Rejected:
  YAGNI for the demo. The current prompt is small (~30 lines)
  and the schema is the source of truth — versioning Jinja adds
  operational weight without behavioral benefit.

**Why we chose this.** When the prompt stabilises (post-demo),
extracting to a templates package is mechanical. Until then,
inline keeps the change trace easy to follow.

---

## 10. Connection-pool-per-MCP-client (no global pool)

**Decision.** Each `MCPClient` owns its own `httpx.AsyncClient`.
There is no shared connection pool.

**Alternatives considered.**

- A module-level `httpx.AsyncClient` shared across clients.
  Rejected: makes test isolation harder — every test would need
  to reset the pool.
- httpx's `Limits` per client to bound concurrency. Not yet
  needed: the demo never issues > 1 in-flight request per
  client.

**Why we chose this.** Per-client ownership is the simplest
correct model. The retry layer in
`apps/backend/orchestrator/mcp_client.py:MCPRetryingTransport`
adds backoff + jitter without a global pool.

---

## 11. In-process FastAPI `TestClient` for integration tests

**Decision.** Integration tests mount the real
`apps.backend.create_app()` + `connectors.alarm_api.create_app()`
+ `connectors.ticket_mock.create_app()` on a `fastapi.testclient.TestClient`
in the same Python process.

**Alternatives considered.**

- Docker Compose for integration tests. Rejected: slow (container
  boot), flaky on CI runners with constrained disk.
- Mock the connector services in tests. Rejected: loses
  integration value — we'd need separate unit + integration
  tests for the mock to be trustworthy.

**Why we chose this.** The orchestrator's wiring fails closed
when `var/index/v1.pkl` is missing, but the integration tests
use an in-memory index so the test suite is self-contained. The
docker compose stack remains the deployment verification
surface.

---

## 12. Streamable HTTP transport (not stdio) for MCP

**Decision.** Both MCP servers speak Streamable HTTP, not stdio.

**Alternatives considered.**

- stdio MCP. Rejected: harder to debug (no logs visible without
  launching the server manually), and the docker compose
  healthcheck pattern (`GET /health`) requires HTTP.
- WebSocket transport. Rejected: adds a dependency we don't
  need; Streamable HTTP is sufficient.

**Why we chose this.** Streamable HTTP is the canonical
deployment posture for MCP servers (Feature 3.x). The
orchestrator's `MCPClient` is transport-agnostic at the API
level — swapping requires changing only the transport factory.

---

## 13. 471 tests, not 1000

**Decision.** The repo ships 471 tests: unit, integration, and
one end-to-end. No load tests, no property-based tests, no fuzz
tests.

**Alternatives considered.**

- Hypothesis for property-based RAG tests. Rejected: the demo's
  corpus is 6 documents; property-based testing adds setup cost
  the brief doesn't require.
- Locust / k6 load tests. Rejected: no production traffic to
  simulate; load testing the demo stack doesn't measure anything
  the brief asks for.

**Why we chose this.** Coverage is 88 % overall; every package
is at or above its threshold; the end-to-end scenario exercises
MCP + RAG together (Feature 8.1). The brief's § 13 TDD bar is
met without the extras.

---

## 14. Structured `Incident` (not raw alarm-api output)

**Decision.** The orchestrator projects every response into a
structured `Incident` payload
(`apps/backend/orchestrator/incident.py:build_incident`). The
GUI renders it as a first-class panel (Story 7.2.1).

**Alternatives considered.**

- Render only the alarm-api's raw response. Rejected: the brief
  calls for a structured incident draft with citations and
  recommended actions — the raw response doesn't carry these.
- Render only the LLM's free-form prose. Rejected: hard
  constraint #4 requires every answer to carry structured
  citations and trace.

**Why we chose this.** A structured payload is testable, types
its way through Pydantic v2, and matches the brief's expected
workspace shape.

---

## Cross-references

- **Architecture walkthrough:** [`docs/architecture.md`](docs/architecture.md)
- **Per-tool reference:** [`docs/mcp-tool-catalog.md`](docs/mcp-tool-catalog.md)
- **RAG design:** [`docs/rag-design.md`](docs/rag-design.md)
- **Limitations:** [`docs/known-limitations.md`](docs/known-limitations.md)
- **Coverage baseline:** [`docs/coverage-baseline.md`](docs/coverage-baseline.md)