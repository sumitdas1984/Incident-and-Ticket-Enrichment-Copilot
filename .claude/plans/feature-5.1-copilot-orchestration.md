# Plan — Feature 5.1: Copilot Orchestration (Stories 5.1.1 + 5.1.2 + 5.1.3)

> **Context.** Epics 3 (MCP) and 4 (RAG) ship and are tested. The orchestrator layer is the missing piece — the brief's hard constraint #2 (MCP and RAG in one workflow) and the mandatory E2E acceptance scenario (investigate recurring high-severity alarms for asset X over 90 days, retrieve the operating procedure, return recommended actions) require this layer to land. Feature 5.1 lands all three stories (5.1.1 chat endpoint, 5.1.2 MCP client, 5.1.3 RAG integration) in one PR — the chain is end-to-end testable only once all three stories are in place.
>
> **Parent issues:** Epic 5 — Copilot Intelligence — `#6`; Feature 5.1 — `#20`; Story 5.1.1 — `#48`; Story 5.1.2 — `#49`; Story 5.1.3 — `#50`.
>
> **What we don't do here:** WebSocket streaming (HTTP only for v1), persistent conversation storage (in-memory dict), ticketing/MCP-tool that performs a write (must not be on the orchestrator's hot path — comes in Epic 6), LLM-based prompt-injection detection (regex blocklist is the first layer; deeper detection is a future hardening pass).
>
> **What we explicitly do:** Hard constraints #1 (MCP-only via the wire), #2 (RAG + MCP in one workflow), #4 (citations + trace), #8 (no hard-coded answers — the mock planner is a *general* NL-to-slots extractor, not a regex bucket).

---

## 1. Goal

A FastAPI app at `apps/backend/` that:

1. Accepts a natural-language incident request at `POST /chat` and returns a typed JSON envelope with: `answer`, `citations`, `trace`, `rag_confidence`, `dropped_count`, `conversation_id`.
2. Plans execution via a hybrid planner: LLM produces a structured JSON plan (validated against a Pydantic schema), executed by a chain runner. A `MockPlanner` is the default — it is a *general* NL-to-slots extractor (entity, temporal window, verb) that emits a typed plan structurally identical to the LLM's output.
3. Makes every MCP call through the `mcp_client` facade (raw `streamable_http_client` + `ClientSession` — never `httpx` to the alarm-api).
4. Calls `rag.retrieval.RetrievalService.retrieve(...)` inside the same plan; the citations land in the response envelope.
5. Builds an MCP execution trace as `list[core.domain.TraceStep]` — one row per MCP tool call.
6. Retains conversation context across turns keyed by `conversation_id` (in-memory dict).
7. Surfaces a typed error envelope on the wire (`{code, message, trace_id, details}`) matching the alarm-api's envelope shape so the frontend has one error type.

---

## 2. Approach

### 2.1 Package layout

```
apps/backend/
├── __init__.py
├── __main__.py                  # reworked: configure_logging, build deps, mount routes, run uvicorn
├── routes.py                    # /chat (POST), /health (GET)
├── wiring.py                    # build_chain_runner(settings) — centralises dependency construction
└── orchestrator/
    ├── __init__.py              # public re-exports
    ├── request.py               # ChatRequest, ChatResponse, ConversationMessage, ToolCatalogEntry
    ├── plan.py                  # PlanStepKind, PlanStep, OrchestrationPlan, payload models
    ├── planner.py               # Planner protocol, LLMPlanner, MockPlanner
    ├── mcp_client.py            # MCPClient facade (streamable_http + ClientSession), MCPSessionFactory
    ├── chain.py                 # ChainRunner, ChainResult, _resolve_waves
    ├── rag_step.py              # RagStepExecutor (calls RetrievalService, builds citations)
    ├── llm_client.py            # LLMClient protocol, MockLLMClient, OpenAILLMClient, AnthropicLLMClient
    ├── conversation.py          # ConversationStore (in-memory dict)
    ├── citations.py             # to_domain_citation() adapter
    ├── answer.py                # compose_answer() formatter
    └── errors.py                # PlannerError, ChainError, LLMError, ConversationNotFoundError
```

### 2.2 Story 5.1.1 — `/chat` endpoint + conversation store

`apps/backend/routes.py`:

```python
from fastapi import APIRouter, Depends, Request
from core.utils import TraceContext, trace_scope
from apps.backend.orchestrator.request import ChatRequest, ChatResponse
from apps.backend.orchestrator.chain import ChainRunner

router = APIRouter()

@router.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest, request: Request) -> ChatResponse:
    runner: ChainRunner = request.app.state.chain_runner
    store = request.app.state.conversation_store
    with trace_scope(TraceContext(conversation_id=req.conversation_id, trace_id=new_id())):
        history = store.get_or_create(req.conversation_id)
        plan = await runner.plan(req.message, history)
        result = await runner.run(plan)
        history.append(ConversationMessage(role="user", content=req.message))
        history.append(ConversationMessage(role="assistant", content=result.answer))
        return ChatResponse(
            conversation_id=history.id,
            answer=result.answer,
            citations=result.citations,
            trace=result.trace,
            rag_confidence=result.rag_confidence,
            dropped_count=result.dropped_count,
        )
```

`ConversationStore` is `dict[str, ConversationHistory]` keyed by `conversation_id`. New conversation_id is a UUID4 when `req.conversation_id` is `None`. Documented in `docs/known-limitations.md` as ephemeral.

### 2.3 Story 5.1.2 — MCP client + chain

#### 2.3.1 `apps/backend/orchestrator/mcp_client.py`

```python
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from core.config import get_settings
from core.exceptions import MCPError
from core.domain import TraceStep
import time

class MCPClient:
    """Thin facade over Streamable HTTP transport. One session per call."""

    def __init__(self, *, base_url: str) -> None:
        self._base_url = base_url.rstrip("/")
        self._endpoint = f"{self._base_url}/mcp"

    async def list_tools(self) -> list[ToolCatalogEntry]:
        async with streamable_http_client(self._endpoint) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.list_tools()
                return [ToolCatalogEntry.from_mcp(t) for t in result.tools]

    async def call(self, *, tool: str, args: dict[str, Any]) -> tuple[Any, TraceStep]:
        started = time.perf_counter()
        async with streamable_http_client(self._endpoint) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.call_tool(name=tool, arguments=args)
                duration_ms = int((time.perf_counter() - started) * 1000)
                if result.is_error:
                    raise MCPError(f"Tool {tool!r} returned is_error: {result.content}")
                return result.structured_content, TraceStep(
                    server="alarm-management",
                    tool=tool,
                    args=args,
                    output=result.structured_content,
                    duration_ms=duration_ms,
                    outcome="success",
                )
```

`ClientSession` is **not safe to share across concurrent `call_tool` invocations** — sequential is the right default. Future parallel support is a session-per-wave pattern; the chain runner is wave-aware (see 2.3.3) but ships sequential.

#### 2.3.2 `apps/backend/orchestrator/plan.py` — typed discriminator union

```python
class PlanStepKind(StrEnum):
    TOOL_CALL = "tool_call"
    RAG_QUERY = "rag_query"
    COMPOSE = "compose"

class ToolCallPayload(BaseModel):
    server: str = "alarm-management"
    tool: str
    args: dict[str, Any] = Field(default_factory=dict)

class RagQueryPayload(BaseModel):
    query: str
    k: int = 5
    filters: RetrievalFilters | None = None

class ComposePayload(BaseModel):
    template: Literal["answer_with_citations", "incident_summary"] = "answer_with_citations"

class PlanStep(BaseModel):
    step_id: str
    kind: PlanStepKind
    payload: ToolCallPayload | RagQueryPayload | ComposePayload = Field(discriminator="kind_compat")
    depends_on: list[str] = Field(default_factory=list)

class OrchestrationPlan(BaseModel):
    plan_id: str
    intent: str
    steps: list[PlanStep]
```

The discriminator is `kind_compat` (a derived field matching `kind`) so Pydantic's `model_json_schema()` produces clean `oneOf` clauses for the LLM-facing JSON schema. The `model_json_schema()` is generated once and embedded in the planner's system prompt.

#### 2.3.3 `apps/backend/orchestrator/chain.py` — wave-aware runner (sequential v1)

```python
class ChainRunner:
    def __init__(self, *, mcp: MCPClient, rag: RetrievalService) -> None:
        self._mcp = mcp
        self._rag = rag

    async def run(self, plan: OrchestrationPlan) -> ChainResult:
        waves = self._resolve_waves(plan)
        ctx: dict[str, Any] = {}  # step_id → output
        trace: list[TraceStep] = []
        citations: list[Citation] = []
        rag_confidence = "none"
        dropped_count = 0
        for wave in waves:
            for step in wave:
                if step.kind == PlanStepKind.TOOL_CALL:
                    payload = step.payload  # type: ignore[assignment]
                    output, ts = await self._mcp.call(tool=payload.tool, args=payload.args)
                    ctx[step.step_id] = output
                    trace.append(ts)
                elif step.kind == PlanStepKind.RAG_QUERY:
                    payload = step.payload  # type: ignore[assignment]
                    rag_result = self._rag.retrieve(payload.query, k=payload.k, filters=payload.filters)
                    ctx[step.step_id] = rag_result
                    citations.extend(to_domain_citation(c) for c in rag_result.citations)
                    rag_confidence = rag_result.confidence
                    dropped_count = rag_result.dropped_count
                else:  # COMPOSE
                    answer = compose_answer(prior_outputs=ctx, citations=citations)
                    ctx[step.step_id] = answer
        final = ctx[plan.steps[-1].step_id] if plan.steps else ""
        return ChainResult(answer=final, citations=citations, trace=trace,
                           rag_confidence=rag_confidence, dropped_count=dropped_count)

    def _resolve_waves(self, plan: OrchestrationPlan) -> list[list[PlanStep]]:
        # v1: every step is independent (no depends_on). One wave.
        return [plan.steps]
```

### 2.4 Story 5.1.3 — RAG inside the orchestration flow

`apps/backend/orchestrator/rag_step.py` is the executor (called from `ChainRunner`). It wraps `RetrievalService.retrieve(...)` and converts:

```python
def to_domain_citation(rag_citation: rag.retrieval.Citation) -> core.domain.Citation:
    return core.domain.Citation(
        doc_id=rag_citation.doc_id,
        section=rag_citation.section,
        page=None,  # rag.retrieval doesn't carry page; chunk_id is the citeable unit
        score=rag_citation.score,
        excerpt=rag_citation.excerpt,
    )
```

**Important:** `core.domain.Citation` and `rag.retrieval.citations.Citation` are two different classes. The adapter is the single most likely silent bug — without it, the response envelope would leak the wrong field shape on the wire. Adapter lives in `apps/backend/orchestrator/citations.py` with a round-trip test.

### 2.5 Planner

#### 2.5.1 `Planner` protocol

```python
class Planner(Protocol):
    async def plan(
        self,
        request: str,
        conversation: list[ConversationMessage],
        tool_catalog: list[ToolCatalogEntry],
    ) -> OrchestrationPlan: ...
```

#### 2.5.2 `MockPlanner` — general extractor (NOT a regex bucket)

Per hard constraint #8 the mock must not pattern-match on the question text. The mock is a small general NL-to-slots extractor:

1. Extract an entity-like token (capitalised noun phrase + digits, hyphenated-id, quoted string).
2. Extract a temporal window (`(\d+)\s*(day|week|month|year)s?`).
3. Extract a verb (`summarize`, `recommend`, `list`, `show`, `find`).
4. Build the plan from these slots — same shape the LLM would emit.

Tests pin the four phrasings of "Boiler Feed Pump 101" (Q6 risk) to confirm the extractor generalises.

#### 2.5.3 `LLMPlanner`

System prompt = `MCP.initialize.instructions` + summarised tool catalog (`name`, `description`, stripped `input_schema`) + `OrchestrationPlan.model_json_schema()` + directive "respond with a single JSON object; no prose." Wire-side: `response_format={"type":"json_schema", ...}` on OpenAI, JSON delimiters on Anthropic. Single retry with corrective validation-error feedback on first `ValidationError`.

### 2.6 LLM client

`apps/backend/orchestrator/llm_client.py`:

```python
class LLMClient(Protocol):
    async def complete(self, prompt: str, *, response_format: Literal["json", "text"] = "text") -> str: ...
```

Three adapters: `MockLLMClient` (returns canned JSON; used by `MockPlanner`'s underlying LLM call if any, but in practice `MockPlanner` doesn't call the LLM at all — it builds the plan directly), `OpenAILLMClient`, `AnthropicLLMClient`. All use `httpx.AsyncClient` instantiated once at startup.

### 2.7 Wiring

`apps/backend/wiring.py`:

```python
def build_chain_runner(*, settings: Settings, retrieval_service: RetrievalService) -> ChainRunner:
    mcp = MCPClient(base_url=settings.mcp_server_url)
    return ChainRunner(mcp=mcp, rag=retrieval_service)
```

`apps/backend/__main__.py`:
- `configure_logging(settings.log_level)`.
- `bind_context(service="copilot-backend", mcp_server="alarm-management")`.
- Build `RetrievalService` from `var/index/v1.pkl` (Feature 4.1 artefact).
- Build `MCPClient` from `settings.mcp_server_url`.
- Build `ChainRunner` via `wiring.build_chain_runner`.
- Build `ConversationStore`.
- Convert `apps/backend/__main__.py` to an app-factory pattern: `def create_app() -> FastAPI` mirroring `connectors/alarm_api/app.py::create_app()`.
- Move `/health` from `__main__.py` to `routes.py`. Keep `__main__.py` as the uvicorn entry that calls `create_app()` and runs it.

### 2.8 Settings additions

```python
# core/config.py
planner_provider: Literal["mock", "llm"] = "mock"
llm_model: str = "gpt-4o-mini"
index_path: str = "./var/index/v1.pkl"
```

`llm_api_key` already exists. No new secret material.

### 2.9 Exception handling

`apps/backend/orchestrator/errors.py`:

```python
class PlannerError(CopilotError): ...
class ChainError(CopilotError): ...
class LLMError(CopilotError): ...  # add to core/exceptions.py
```

`LLMError` is added to `core/exceptions.py` (the Plan agent's Q8 finding). FastAPI exception handlers map `LLMError`/`MCPError`/`RAGError`/`CopilotError` to the alarm-api's `{code, message, trace_id, details}` envelope, registered in `routes.py`.

### 2.10 Tests

**Unit (`tests/unit/orchestrator/`):**

| File | Coverage |
|---|---|
| `test_plan.py` | Schema validation, payload discriminator dispatch, missing fields, `model_json_schema()` shape. |
| `test_planner.py` | `MockPlanner` extracts asset IDs across phrasings; builds 3-step plan; no-plan-on-empty-request. `LLMPlanner` parses + validates JSON; rejects malformed plans with one retry. |
| `test_chain.py` | Executes a 3-step plan; captures trace; partial-failure → step `outcome="error"`, chain continues. |
| `test_rag_step.py` | RAG step surfaces citations + confidence + dropped_count; low-confidence path. |
| `test_mcp_client.py` | Maps `is_error` → `MCPError`; captures timing; `tools/list` returns typed catalog. |
| `test_conversation.py` | Store round-trip; new conversation_id generation; concurrent turn appends. |
| `test_answer.py` | Composer formats citations into the answer string. |
| `test_citations.py` | `to_domain_citation()` mapping round-trip; missing-field tolerance. |
| `test_llm_client.py` | `MockLLMClient` returns canned JSON; `OpenAILLMClient` formats the right wire payload (mock the HTTP layer). |
| `test_partial_failure.py` | Tool error mid-chain; chain completes with that step's `outcome="error"` in the trace; final answer still produced. |
| `test_mock_planner_phrasing_variations.py` | Four phrasings of "Boiler Feed Pump 101" produce equivalent plans. |

**Integration (`tests/integration/`):**

New `tests/integration/conftest.py` extracts `mcp_url` fixture from `test_tools_list.py` and adds `mcp_server_with_mock_alarm_api` and `chain_runner_with_mocks`.

| File | Coverage |
|---|---|
| `test_orchestrator_end_to_end.py` | `POST /chat` → plan → MCP + RAG → response. Uses `mcp_url` fixture. |
| `test_orchestrator_e2e_acceptance.py` | Exact brief scenario: "investigate recurring high-severity alarms for Boiler Feed Pump 101 over the last 90 days, retrieve the operating procedure, return recommended actions." |
| `test_orchestrator_conversation.py` | Two turns on the same `conversation_id`; second turn sees the first turn's message in the planner context. |

All tests use `DeterministicEmbeddingModel` (Feature 4.1 test embedder) for RAG. The real `SentenceTransformerEmbeddingModel` is gated behind `slow_embeddings` (already configured).

### 2.11 Non-goals

- **No WebSocket.** HTTP only. The streaming path is a one-line follow-up.
- **No persistent conversation store.** In-memory dict. Documented in `docs/known-limitations.md`.
- **No DAG parallel execution.** Wave-aware skeleton, sequential v1.
- **No LLM-based injection detection.** The regex blocklist in `rag.retrieval.injection` is the first layer.
- **No ticketing / write operations.** Story 5.1.3 is RAG read-only. The MCP tools available are read-only by design.
- **No new runtime dependencies.** `httpx`, `tenacity`, `mcp`, `pydantic`, `fastapi` are all already in `pyproject.toml`.

### 2.12 Dependencies

No new dependencies. `httpx` (already in `pyproject.toml`) is used for the LLM client. `mcp` (already pinned `>=1.0`, resolved to `2.0.0`) covers the client surface.

---

## 3. Critical files

### New

- `apps/backend/orchestrator/__init__.py`
- `apps/backend/orchestrator/request.py`
- `apps/backend/orchestrator/plan.py`
- `apps/backend/orchestrator/planner.py`
- `apps/backend/orchestrator/mcp_client.py`
- `apps/backend/orchestrator/chain.py`
- `apps/backend/orchestrator/rag_step.py`
- `apps/backend/orchestrator/llm_client.py`
- `apps/backend/orchestrator/conversation.py`
- `apps/backend/orchestrator/citations.py`
- `apps/backend/orchestrator/answer.py`
- `apps/backend/orchestrator/errors.py`
- `apps/backend/routes.py`
- `apps/backend/wiring.py`
- `tests/integration/conftest.py`
- `tests/unit/orchestrator/__init__.py`
- `tests/unit/orchestrator/test_*.py` (per the table in 2.10)
- `tests/integration/test_orchestrator_*.py` (per the table in 2.10)

### Modified

- `apps/backend/__main__.py` — replace placeholder with the app-factory + uvicorn entry described in 2.7.
- `core/config.py` — add `planner_provider`, `llm_model`, `index_path`.
- `core/exceptions.py` — add `LLMError(CopilotError)`.
- `tests/integration/mcp_server/test_tools_list.py` — refactor to use the shared `mcp_url` fixture (no behaviour change).
- `docs/known-limitations.md` — document the in-memory conversation store.

### Untouched

- `mcp-servers/`, `rag/ingestion/`, `rag/retrieval/` — the orchestrator is the consumer, not the producer.
- `apps/frontend/` — the GUI lands in Epic 7.
- `connectors/` — the alarm-api simulator is unchanged; the orchestrator calls it only via the MCP server.

### Patterns to reuse (with file paths)

- `core.logging.bind_context` / `clear_context` / `get_logger` / `configure_logging` — `apps/backend/orchestrator/*` mirrors the existing module-level pattern.
- `core.utils.TraceContext` / `trace_scope` — handler context manager (already exists).
- `core.domain.TraceStep` / `core.domain.Citation` — verbatim in the response envelope.
- `core.exceptions.MCPError` / `RAGError` / `CopilotError` — base for the new orchestrator exceptions.
- `rag.retrieval.RetrievalService.retrieve(...)` — read by `RagStepExecutor`.
- `core.config.get_settings()` — `@lru_cache` singleton; tests call `cache_clear()`.
- `conftest.py mcp_url` fixture pattern from `tests/integration/mcp_server/test_tools_list.py` — extracted to `tests/integration/conftest.py`.
- `AlarmApiClient.from_settings` / `RetryPolicy` from `mcp-servers/alarm-management/alarm_api_client.py` / `retry.py` — *not* promoted to `core/` in this PR (out of scope). The LLM and MCP clients use `httpx.AsyncClient` directly with `tenacity.wait_exponential_jitter` (already in `pyproject.toml`).

---

## 4. Verification

1. **Static gates (must pass before push):**
   ```bash
   uv sync
   uv run ruff check .
   uv run mypy --explicit-package-bases apps rag connectors core
   uv run pytest -ra
   ```
   Expect: 286 (post-4.2 baseline) + ~25 new = ~311 tests pass.

2. **Live smoke (orchestrator + RAG):**
   ```python
   from apps.backend.orchestrator import ChainRunner, MockPlanner, MCPClient
   from rag.retrieval import RetrievalService
   from pathlib import Path
   from rag.ingestion import InMemoryVectorIndex, DeterministicEmbeddingModel

   idx = InMemoryVectorIndex.load(Path("var/index/v1.pkl"))
   service = RetrievalService(index=idx, embedder=DeterministicEmbeddingModel(dimension=idx.metadata.dimension))
   runner = ChainRunner(mcp=MCPClient(base_url="http://localhost:9000"), rag=service)
   plan = await MockPlanner().plan(
       "investigate recurring high-severity alarms for Boiler Feed Pump 101 over the last 90 days",
       conversation=[], tool_catalog=[],
   )
   result = await runner.run(plan)
   print(result.answer, len(result.citations), len(result.trace))
   ```
   Expect: non-empty `answer`, ≥1 citation, ≥2 trace steps.

3. **Live HTTP smoke:**
   ```bash
   docker compose up --build &  # alarm-api + mcp-server + copilot-backend
   curl -X POST http://localhost:8001/chat \
       -H 'content-type: application/json' \
       -d '{"message":"investigate recurring high-severity alarms for Boiler Feed Pump 101 over the last 90 days"}'
   ```
   Expect: 200 OK with `{"answer": "...", "citations": [...], "trace": [...], "rag_confidence": "...", "dropped_count": N, "conversation_id": "..."}`.

4. **Lint / type / docs:** clean (see step 1).

5. **Conftest extraction sanity:** `tests/integration/mcp_server/test_tools_list.py` still passes after the conftest refactor.

---

## 5. Rollback

Trivial. The orchestrator is a new package; removing it is a `git revert`. The MCP server, RAG pipeline, and alarm-api simulator are untouched. The shared `conftest.py` is a refactor; the old fixture is preserved in the test file's git history if rollback is needed.

---

## 6. Branch + PR

- Branch: `feature/feature-5.1-orchestration` (off `developer` at `d9d312c`, post-Feature-4.2 merge).
- Single PR closes `#48` (5.1.1), `#49` (5.1.2), `#50` (5.1.3).
- After merge: Feature 5.2 (incident enrichment: format final answer, generate draft ticket) and Epic 7 (GUI) can branch off.

---

**Awaiting sign-off.** Reply "approved" to apply, or send edits.
