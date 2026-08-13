# Known Limitations

This document tracks the deliberate limitations of the current
implementation, what they future-proof, and the work they would
require to lift.

## 1. In-memory conversation store

The orchestrator's :class:`~apps.backend.orchestrator.conversation.ConversationStore`
is a process-local ``dict`` keyed by ``conversation_id``. The
store is rebuilt on every restart and is not shared across
processes.

**Why documented:** the brief's hard constraints do not require
durable conversation storage. The hard timebox (10–14 h) does
not accommodate a database dependency.

**What it would take to lift:** swap the in-memory dict for
SQLite (single-process) or Redis (multi-process). The
:class:`~apps.backend.orchestrator.conversation.ConversationStore`
API is small enough that the swap is a one-file change.

## 2. Deterministic embedder in the bundled demo path

The FastAPI app's default embedder is
:class:`~rag.ingestion.DeterministicEmbeddingModel` so the demo
runs without downloading the ``sentence-transformers`` model
weights. The real :class:`~rag.ingestion.SentenceTransformerEmbeddingModel`
is a drop-in replacement; the orchestrator's wiring is
embedder-agnostic.

**Why documented:** the deterministic embedder is **not**
semantically meaningful. The retrieval ranks patterns, not
topics. The orchestrator's E2E acceptance test still passes
because the chain wires MCP + RAG into a single workflow
(hard constraint #2); the *semantic quality* of the answer
improves dramatically when the real model is wired.

**What it would take to lift:** change the
``_build_rag`` helper in :file:`apps/backend/wiring.py` to
construct a :class:`~rag.ingestion.SentenceTransformerEmbeddingModel`
with the model name expected by the production deployment.

## 3. HTTP only (no WebSocket streaming)

The orchestrator's ``/chat`` endpoint is HTTP-only. The brief's
Story 5.1.1 mentions "HTTP + WebSocket"; the WebSocket path
streams tokens as the chain runs.

**Why documented:** the HTTP path is the minimum viable surface
and is what the GUI (Epic 7) consumes. A WebSocket path is
one routing change + one streaming endpoint.

**What it would take to lift:** add a ``/chat/stream`` endpoint
that wraps the chain runner in a generator. The chain runner
already emits ``TraceStep`` rows as it runs; the stream
surface is a thin wrapper.

## 4. Sequential chain runner

The :class:`~apps.backend.orchestrator.chain.ChainRunner`
executes steps in order. The runner's :meth:`_resolve_waves`
is wave-aware — it groups steps by ``depends_on`` — but the
current implementation collapses every step into one wave.

**Why documented:** the brief's E2E acceptance scenario is
strictly sequential (``search_assets`` → ``summarize_alarms``
→ ``recommend_actions`` → ``RAG`` → ``compose``). Wave
parallelism is a future story.

**What it would take to lift:** topologically sort the plan's
steps by ``depends_on`` and execute each wave with
``asyncio.gather``. The session lifecycle on the MCP client
needs to be a session-per-wave (not session-per-call) to keep
the MCP SDK's ``ClientSession`` reuse rules satisfied.

## 5. Wave-aware plan with empty ``depends_on``

The :class:`~apps.backend.orchestrator.plan.OrchestrationPlan`
schema carries a ``depends_on`` field but the planner never
populates it. Plain sequential plans are emitted.

**Why documented:** the v1 chain runner does not enforce
``depends_on`` semantics. The field is plumbed so the future
wave-aware runner can read it without a schema migration.

**What it would take to lift:** the planner must emit
``depends_on`` references; the chain runner must topologically
sort and resolve waves.

## 6. The LLM planner's mock is a deterministic extractor, not a switch

The :class:`~apps.backend.orchestrator.planner.MockPlanner`
is a *general* NL-to-slots extractor that builds a plan from
the request's structural tokens (asset id, temporal window,
verb). It does **not** pattern-match on the user's question
text — the same shape is produced by the
:class:`~apps.backend.orchestrator.planner.LLMPlanner` when
the configured LLM is real.

**Why documented:** Hard constraint #8 forbids hard-coded
answers to the sample questions. The mock's "regex" is a
slot extractor, not an intent taxonomy. The four-phrasing
test guards against the recipe.

**What it would take to lift:** the LLM planner is the right
default for production. Configure ``LLM_PROVIDER=openai`` (or
``anthropic``) and ``LLM_API_KEY`` and the orchestrator
switches to the LLM-driven planner automatically.

## 7. Embedder backend is config-driven (closed)

The orchestrator's runtime embedder is selected by
``EMBEDDER_BACKEND`` in ``.env`` (default
``deterministic``). The wiring in
``apps/backend/wiring.py:_build_rag`` compares the wired
embedder's ``model_name`` against the index's
``IndexMetadata.embedder_name`` and raises ``LLMError`` on
mismatch, so the operator never silently retrieves
nonsense.

To run with the real model:

```bash
# Rebuild the index with the real embedder
uv run python -m rag.ingestion \
  --corpus rag/documents \
  --index var/index/v1.pkl \
  --embedder sentence-transformers

# Switch the runtime to match
echo "EMBEDDER_BACKEND=sentence-transformers" >> .env
```

The shipped index is built with the deterministic embedder
so the demo path is hermetic. The guard was added to close
out the historic "the orchestrator silently produces
nonsense if the embedders don't match" footgun.

## 8. Static seeded ticket list (Feature 5.2)

The alarm-api's ``/tickets/similar`` endpoint
(:file:`connectors/alarm_api/routers/tickets.py`) returns a
small static list seeded in :file:`connectors/alarm_api/seed.py`.
Five entries cover the four asset classes in the corpus
(``boiler``, ``compressor``, ``cooling_water``, ``site``).

**Why documented:** a real ticket-similarity index requires an
embedding model and a vector store — both already present in
the project, but wiring them up adds latency and complexity
the demo path does not need. The seeded list has pre-baked
``similarity`` scores so the orchestrator's top-N filter is
deterministic.

**What it would take to lift:** store the seed list in a
proper table (e.g. a SQLite-backed ``tickets`` table populated
on alarm-api startup), expose a vector-store-backed similarity
search, and add a `/tickets` admin endpoint for ticket
lifecycle management. The seeded list is the 1.0 placeholder.

## 9. Template-based Incident projection (Feature 5.2)

The :class:`~apps.backend.orchestrator.incident.build_incident`
function projects the chain's outputs into a typed
:class:`~core.domain.Incident` payload via template projection
(no LLM call). Title, summary, likely_cause, recommended_actions,
citations, and similar_tickets are derived from the chain's
trace, citations, and tool outputs.

**Why documented:** the brief's workflow step 6 ("prepare a
structured incident draft") is a projection of data the
orchestrator already has. The LLM does not invent any new
information — it would only rephrase what's already in the
chain's outputs. Template projection is deterministic, fast,
and auditable.

**What it would take to lift:** pass an :class:`LLMClient` to
the IncidentBuilder and override the ``title`` / ``summary`` /
``likely_cause`` fields with an LLM-driven rewrite. The
template projection stays as the fallback when the LLM client
is ``MockLLMClient``.

## 10. Mock LLM client emits a minimal plan

The :class:`~apps.backend.orchestrator.llm_client.MockLLMClient`
emits a one-RAG-step + compose plan. The chain runner
executes it correctly, but the plan is not a realistic
substitute for an LLM-generated plan when the
:func:`~apps.backend.wiring.build_orchestrator` factory wires
the LLM-driven planner on top.

**Why documented:** the demo path needs to be runnable without
an API key. The mock LLM is a placeholder for the integration
shape; the real LLM client is the production path.

**What it would take to lift:** None — the production path
is one config switch.
