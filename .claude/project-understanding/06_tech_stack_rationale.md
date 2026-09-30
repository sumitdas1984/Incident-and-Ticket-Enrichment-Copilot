# 06 — Tech stack rationale

> **What this answers.** When the interviewer asks "why X and
> not Y" for any major library, you have a one-line answer.
> This doc collects them.

---

## The stack at a glance

```
┌────────────────────────────────────────────────────────┐
│  Runtime:        Python ≥ 3.13 (per pyproject.toml)    │
│  HTTP/validate:  FastAPI + Pydantic v2                 │
│  MCP SDK:        mcp 1.x — Streamable HTTP transport   │
│  Embeddings:     Deterministic (demo) /                │
│                  sentence-transformers 3.x (prod)      │
│  Vector store:   ChromaDB (HTTP API)                   │
│  GUI:            Streamlit 1.39+                       │
│  Orchestration:  Hand-rolled chain runner + planner    │
│  LLM:            OpenAI / Anthropic / MockLLMClient    │
│  Tests:          pytest + httpx.MockTransport +        │
│                  streamlit.testing.v1.AppTest          │
│  Container:      Docker Compose (docker compose up)   │
└────────────────────────────────────────────────────────┘
```

For each choice: **why this**, **what we rejected**, **when
this would change**.

---

## 1. Python 3.13

**Why:** the brief mandates it (in `pyproject.toml`). 3.13
brings the GIL-free build flags and the new type-parameter
syntax — neither is used here, but the brief's `requires-python
= ">=3.13"` line is.

**What we rejected:** earlier versions (3.10/3.11/3.12) work
fine, but the brief was explicit. No reason to argue.

**When this would change:** never — the brief is the spec.

---

## 2. FastAPI + Pydantic v2

**Why:** FastAPI gives us OpenAPI for free, async-native HTTP
handlers, and a clean dependency-injection story. Pydantic v2
gives us typed request/response models that double as both
runtime validation and OpenAPI schema source. The 12-layer
architecture has well-defined boundaries, and FastAPI makes
those boundaries cheap to declare.

**What we rejected:**
- **Flask** — no first-class typing, no async, schema gen is
  manual.
- **Django REST Framework** — heavyweight for a single-domain
  backend; the ORM and admin are unneeded here.
- **Pure Starlette** — too thin; we'd reinvent request
  validation.

**When this would change:** if we needed a single-binary
deployable for embedded systems, FastAPI's uvicorn dependency
might matter; we could swap to LitServe. Not a current
concern.

---

## 3. MCP SDK (`mcp` 1.x) over Streamable HTTP

**Why:** MCP is the open protocol that the brief's hard
constraint #1 references. Streamable HTTP is the SDK's
recommended transport — it's HTTP-native (no WebSocket
quirks), supports request/response and streaming, and works
cleanly through FastAPI middleware.

**What we rejected:**
- **Raw JSON-RPC over WebSocket** — non-standard, harder to
  test, doesn't compose with FastAPI's HTTP middleware.
- **stdio MCP transport** — fine for desktop tools, awkward
  for a service-to-service setup with multiple servers.

**When this would change:** if Anthropic deprecates Streamable
HTTP for a newer transport, the swap is local to
`apps/backend/orchestrator/mcp_client.py`. The rest of the
orchestrator doesn't care.

---

## 4. ChromaDB (HTTP API)

**Why:** ChromaDB has a clean Python client + a separate HTTP
service. It supports metadata filtering (which the brief's
§ 4 RAG corpus needs: source type, section, page) and
persistent storage. The HTTP API gives us a real network
boundary for tests.

**What we rejected:**
- **FAISS** — fast but no metadata filtering, no persistence
  story beyond pickle.
- **Qdrant / Weaviate / Milvus** — better at scale, but more
  configuration overhead than the brief's timebox fits.
- **In-memory numpy index** — what `var/index/v1.pkl` actually
  is for the demo path. ChromaDB is wired in for production
  paths; the demo runs the in-memory version because it's
  hermetic and zero-deps.

**When this would change:** scale. At >100k chunks or >10
req/s, ChromaDB's HTTP API becomes the bottleneck; we'd move
to Qdrant.

---

## 5. Streamlit 1.39+

**Why:** the brief asks for a GUI. Streamlit gives us a
Python-only GUI (no Node, no bundler), great built-ins
(`st.chat_input`, `st.dialog`, `st.skeleton`), and an
`AppTest` for headless testing. The two-column layout
(chat + workspace) fits Streamlit's `st.columns` pattern.

**What we rejected:**
- **React + FastAPI** — bigger surface area, more
  configuration, more deployment complexity. The brief's
  10-14 hour timebox doesn't fit.
- **Gradio** — also Python-only, but its chat UI is less
  flexible for the workspace column requirement.

**When this would change:** if the GUI needed real-time
multi-user presence, drag-and-drop, or a custom design
system. Streamlit is not the right tool for those.

---

## 6. Hand-rolled chain runner + planner

**Why:** the brief explicitly requires "multi-step MCP
chaining" — a deterministic order of MCP calls. A custom
runner is the smallest thing that does this correctly, with
no framework overhead. The plan schema (`PlanStep.waves`)
already supports DAG execution; v1 just runs sequentially.

**What we rejected:**
- **LangChain** — large dependency, opinionated abstractions,
  most of which we don't need.
- **LlamaIndex** — RAG-focused, but the orchestration is
  thinner than what the brief's multi-step chaining needs.
- **DSPy** — interesting but overkill for v1.

**When this would change:** if the chain grew beyond 5-7
steps or required cross-step retry policies, the hand-rolled
runner would get unwieldy. LangGraph is the natural next
step.

---

## 7. MockLLMClient + LLM adapters

**Why:** the brief asks for a hermetic demo path — one that
runs without an API key. `MockLLMClient` returns deterministic
answers for known intents, so the demo is reproducible.
Production paths are one config switch (`LLM_PROVIDER=openai`
or `anthropic`).

**What we rejected:**
- **Real LLM from day one** — requires an API key, breaks
  hermetic demo, needs prompt iteration that the timebox
  doesn't fit.
- **Multiple LLM providers baked in** — we have adapters for
  OpenAI and Anthropic, but only one is active at a time.

**When this would change:** if we needed streaming responses
in the GUI. The mock doesn't stream; a real LLM adapter would
need a `stream=True` path through the FastAPI handler.

---

## 8. Deterministic embedder (demo) / sentence-transformers 3.x (prod)

**Why:** the demo embedder is a hash-based deterministic
function — same input, same vector, every run. This makes
tests reproducible and avoids the 100MB model download on
first run. Production switches to `sentence-transformers` via
a one-line config.

**What we rejected:**
- **OpenAI embeddings API** — requires a key, costs money,
  breaks the demo's hermetic path.
- **A custom transformer from scratch** — way out of scope.

**When this would change:** at production. The swap is local
to `rag/ingestion/embedder.py`.

---

## 9. Docker Compose

**Why:** seven services (copilot backend, frontend, alarm-api,
alarm-mcp, ticketing-mcp, ticket-mock, vector-store) need to
start together with health checks and the right network
topology. Compose does this declaratively in 200 lines of
YAML.

**What we rejected:**
- **Kubernetes** — overkill for a single-host demo.
- **Bash orchestration** — fragile, no health checks.

**When this would change:** at production scale. The Compose
file becomes a Helm chart; the in-container simulators get
swapped for real APIs.

---

## 10. uv (the package manager)

**Why:** `uv` is fast, deterministic (via `uv.lock`), and
PEP 723-compatible. The brief asks for "runs from a clean
environment"; `uv sync` does that in seconds.

**What we rejected:**
- **Poetry** — slower, more opinionated, lock file format
  is non-standard.
- **pip + venv** — works, but no lock file by default, slower
  installs.

**When this would change:** probably never. `uv` is the right
tool.

---

## If asked in the interview

**Q: "Why FastAPI and not Flask?"**

> FastAPI gives us typed request/response models via Pydantic
> v2, async-native handlers, and a free OpenAPI spec. Flask
> would have us reinventing all three.

**Q: "Why Streamlit and not React?"**

> Streamlit is Python-only — no Node, no bundler. The brief's
> 10-14 hour timebox doesn't fit a React + FastAPI split, and
> `st.dialog` gives us the modal the hard constraint #3 needs
> without writing any JS.

**Q: "Why a hand-rolled chain runner and not LangChain?"**

> The brief's "multi-step MCP chaining" is a deterministic
> ordered list. A custom runner is the smallest thing that
> does this correctly. The plan schema already supports
> wave-aware parallel execution for when we need it.

**Q: "Why MockLLMClient as the default?"**

> Hermetic demo. The brief requires the system to run without
> an API key. MockLLMClient gives us deterministic answers
> for known intents; production paths are one config switch.

---

## Open questions for next time

- *What's the actual prompt to the LLM?* →
  `apps/backend/orchestrator/answer.py` builder.
- *Why Streamable HTTP and not stdio MCP?* → Decision #6 in
  `docs/design-decisions.md`.
- *What's the model size for sentence-transformers?* →
  `rag/ingestion/embedder.py` config.
