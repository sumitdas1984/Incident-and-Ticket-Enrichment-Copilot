# 09 — Interview Q&A flashcards

> **What this answers.** Common questions an ABB interviewer
> might ask about this project, with crisp 2-3 sentence
> answers. Read these last. Use them to quiz yourself the
> morning of the interview.

---

## The opening questions

**Q: "Tell me about the project."**

> A chat-style copilot that turns an industrial alarm-system
> question into an evidence-backed incident ticket. Live data
> comes in via a candidate-developed MCP server; procedure
> docs come in via RAG. Every ticket is gated by explicit
> operator approval before any write. The whole thing runs
> hermetically via Docker Compose — no real industrial system,
> no API keys.

**Q: "What problem were you solving?"**

> Service engineers spend 20-30 minutes gathering context
> across the alarm system and procedure docs to write a good
> ticket. The copilot collapses that into a single
> natural-language request, with every recommended action
> backed by a citation the engineer can read.

**Q: "What does 'good' look like in the demo?"**

> Operator types one question, copilot returns an answer with
> citations + execution trace, engineer edits the ticket
> draft, clicks Approve, and a ticket ID appears. Five
> screens, three minutes, all against in-container simulators.

---

## The architecture questions

**Q: "How is the system structured?"**

> Twelve layers, each with one responsibility. GUI →
> orchestrator → MCP clients → MCP servers → API connectors →
> RAG ingestion/retrieval → domain models → config → logging
> → persistence → tests. The brief mandates the breakdown,
> and each layer is a folder with a single clear purpose.

**Q: "What are the two pillars?"**

> MCP for live system data, RAG for procedure documents. They
> solve different problems and are complementary — the alarm
> system is structured and changes every minute, the
> procedures are static prose. Hard constraint #2 requires
> they appear together in the same workflow.

**Q: "Why MCP and not direct HTTP?"**

> Three reasons. The alarm team can swap implementations
> without touching our code. The copilot team can swap LLMs
> without touching the alarm-system integration. And every
> tool call is structured, typed, and auditable. Hard
> constraint #1 enforces this — no `httpx` in the orchestrator.

**Q: "Why RAG and not fine-tuning?"**

> Procedures change over time. RAG lets us update a markdown
> file and re-ingest without retraining. It also gives us
> citations — fine-tuned models can't tell you which document
> a claim came from.

---

## The hard-constraint questions

**Q: "How do you enforce the MCP-only path?"**

> Architecturally — there's no HTTP client in the
> orchestrator, only the MCP client. And CI greps for `httpx`
> imports outside the MCP server and fails the build. The
> guard has caught real PRs (decision history in PR #88).

**Q: "How do you prevent prompt injection?"**

> A blocklist filter runs before retrieved chunks reach the
> LLM. Two seeded corpus documents deliberately embed
> injection patterns, so the filter is exercised in every
> demo. Dropped chunks are counted and surfaced to the
> operator as a transparency signal.

**Q: "How do you guarantee explicit approval?"**

> Two layers of gating. The GUI requires a click in a modal
> — and that modal is below the fold. The connector enforces
> `approved == true` and returns 403 otherwise. Every
> approved write appends an immutable audit row.

**Q: "How do you handle no-result from RAG?"**

> Low-confidence flag. If the top match scores below a
> threshold, the response carries `rag_confidence: "low"`
> and the GUI shows a red `RAG · LOW` pill. The operator
> sees the score and can decide whether to trust the answer.

**Q: "How is the audit log protected?"**

> It's append-only. The ticket-mock has no DELETE endpoint on
> `/tickets/audit` — once a row is appended, it stays. The
> success panel surfaces the row's `request_id` so the
> operator can correlate it with the log entries.

---

## The "why this stack" questions

**Q: "Why FastAPI?"**

> Typed request/response models via Pydantic v2, async-native
> handlers, free OpenAPI spec. Flask would have us reinventing
> all three.

**Q: "Why Streamlit?"**

> Python-only — no Node, no bundler. `st.dialog` gives us the
> modal the approval gate needs without writing any JS. The
> 10-14 hour timebox didn't fit a React + FastAPI split.

**Q: "Why a hand-rolled chain runner?"**

> The brief's "multi-step MCP chaining" is a deterministic
> ordered list. A custom runner is the smallest thing that
> does this correctly. The plan schema already supports
> wave-aware parallel execution for when we need it.

**Q: "Why MockLLMClient as the default?"**

> Hermetic demo. The brief requires the system to run without
> an API key. Production paths are one config switch
> (`LLM_PROVIDER=openai` or `anthropic`).

**Q: "Why Streamable HTTP for MCP and not stdio?"**

> Streamable HTTP composes with FastAPI middleware, no
> WebSocket quirks, works for service-to-service. Stdio is
> fine for desktop tools but awkward here.

---

## The testing questions

**Q: "How many tests, and what do they cover?"**

> 471 passing, 1 deselected (the slow-embeddings one). 303
> unit tests cover single-function behaviour. 167 integration
> tests cover module interactions over real HTTP. 1 e2e test
> runs the canonical scenario end-to-end and asserts both
> pillars produced output.

**Q: "What's the one test that matters most?"**

> `tests/e2e/test_full_workflow_mcp_rag.py`. It runs the
> brief's § 7 scenario and asserts: answer is non-empty,
> citations is non-empty (RAG worked), trace is non-empty
> (MCP worked), incident is a complete payload. If any of
> those four fail, hard constraints #2 or #4 are violated.

**Q: "What's your CI guard do?"**

> Two grep checks. One enforces MCP-only path (no `httpx`
> outside the MCP server). One enforces config-via-core (no
> `os.getenv` outside `core/`). Both fail the build on
> violation.

---

## The "what would you change" questions

**Q: "What would you do differently with more time?"**

> Turn on the wave-aware executor — independent MCP calls
> could run in parallel. Add streaming LLM responses to the
> GUI. Move from in-memory conversation store to SQLite so
> conversations survive restarts. Real Jira / ServiceNow
> connector instead of the mock.

**Q: "What's the biggest technical risk?"**

> Latency. Five MCP calls + RAG + LLM = a couple of seconds
> per request. Parallel dispatch (decision #3) helps. Caching
> the RAG index helps more. Pre-warming the MCP servers
> helps most.

**Q: "What if the alarm API goes down?"**

> The MCP server's retry policy handles transient 5xx +
> transport blips (decision #7). Persistent failures surface
> to the operator as a `last_error` card in the workspace
> column. The chat history still shows prior successful turns.

---

## The "ABB-specific" questions

**Q: "How does this fit an industrial context?"**

> The copilot sits between the operator and the alarm system.
> It doesn't replace the alarm system or the operator — it
> makes both faster. The approval gate and the audit log are
> the regulatory safety net.

**Q: "Why is the structured `Incident` shape important?"**

> It maps cleanly to the ticket-mock's projection, which
> maps cleanly to a real Jira / ServiceNow issue. The
> orchestrator's job is to fill that shape; the LLM's job is
> to narrate. Keeping those separate is what makes the
> downstream system integration deterministic.

**Q: "How would you scale this?"**

> Move from numpy to ChromaDB at production. Move from
> in-memory conversation store to Redis. Add a queue between
> the orchestrator and the LLM. Run multiple copilot-backend
> instances behind a load balancer. None of these change the
> 12-layer architecture — they're horizontal scale-out of
> existing layers.

---

## If you only have 30 seconds to prepare

The mental picture:

```
Operator → GUI → Orchestrator → MCP (live) + RAG (docs)
                → Incident draft → Approve → Ticket
```

The 8 hard constraints, in one breath:

> "MCP-only, both pillars, explicit approval, citations +
> trace, no secrets, injection defence, hermetic demo, no
> hard-coded answers."

The one number to remember:

> **471 tests, 88% coverage, 12 layers, 8 hard constraints.**

---

## Open questions for next time

- *What's the brief's § 7 scenario verbatim?* → `Assignment_Use_Case.md`.
- *What's the canonical question's exact phrasing?* → Doc 04.
- *What's a "wave" in `PlanStep.waves`?* → `apps/backend/orchestrator/plan.py`.
