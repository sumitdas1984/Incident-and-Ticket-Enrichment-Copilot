# 05 — Hard constraints and how they're enforced

> **What this answers.** The brief lists 8 hard constraints.
> This doc maps each one to **the exact file, test, or CI
> guard** that enforces it. When the interviewer asks "how do
> you guarantee X", you answer with the file path, not a vague
> promise.

---

## The 8 hard constraints

These come from `Assignment_Use_Case.md` and
`Submission_and_Evaluation_Guidelines.md`. They're graded as
red flags if violated.

---

### Constraint #1 — MCP-only path to the alarm API

> The copilot must call the Alarm Management API exclusively
> through the MCP server. Direct API calls in the orchestration
> layer are a red flag. Direct calls are allowed only inside
> the MCP server's connector.

**Enforced in three places:**

1. **Architectural.** The orchestrator has zero direct calls
   to the alarm API. The only path from orchestrator → alarm
   API is: orchestrator → `mcp_client.invoke(...)` → alarm-MCP
   server → `alarm_api_client.py` (the connector) → HTTP.
2. **CI guard.** `.github/workflows/ci.yml` runs `grep -rn
   "httpx" apps/ mcp-servers/ rag/ connectors/` and fails if
   any orchestrator code touches `httpx` for the alarm URL.
3. **Verification.** `docs/submission-message.md` § 1.6 cites
   the grep output: the only `httpx` clients reaching the
   alarm-api live in `mcp-servers/alarm-management/alarm_api_client.py`
   and `connectors/alarm_api/`.

**How to talk about it:**

> "We enforce this architecturally and at CI time. The
> orchestrator literally doesn't have an HTTP client — only
> the MCP client. CI greps for `httpx` outside the MCP server
> and fails the build."

---

### Constraint #2 — MCP and RAG in the same workflow

> MCP and RAG must participate in the same end-to-end business
> workflow. A disconnected RAG demo or a disconnected MCP demo
> is grounds for rejection.

**Enforced in two places:**

1. **One `/chat` call exercises both paths.** The chain runner
   interleaves MCP steps and RAG steps inside the same plan.
   The operator never sees a "RAG-only" or "MCP-only" answer.
2. **One end-to-end test covers both.**
   `tests/e2e/test_full_workflow_mcp_rag.py` runs the brief's
   canonical scenario and asserts both pillars produced output:
   - non-empty `citations` (RAG produced)
   - non-empty `trace` (MCP produced)
   - structured `Incident` payload (LLM composed)

**How to talk about it:**

> "Every `/chat` call exercises both pillars. The chain runner
> interleaves MCP and RAG steps in the same plan, and our one
> e2e test asserts both paths produced output."

---

### Constraint #3 — Explicit ticket approval

> Ticket / issue creation is a write operation. It must require
> explicit user confirmation in the GUI before the MCP server
> is invoked.

**Enforced in three places:**

1. **GUI modal gate.** `apps/frontend/ui.py:_render_confirmation_modal`
   is an `st.dialog`. The Approve button is the *only* way to
   trigger a write. Below the fold — operator has to scroll to
   confirm.
2. **API-side gate.** `connectors/ticket_mock/routers/tickets.py`
   returns 403 unless `approved == true`. So even a forged
   client can't write without that flag.
3. **Audit trail.** Every approved write appends a row to
   `GET /tickets/audit` with `approved_by`, `approved_at`,
   `request_id`. Not removable.

**How to talk about it:**

> "Two layers of gating. The GUI requires a click in a modal —
> and that modal is below the fold. The connector enforces
> `approved == true` and returns 403 otherwise. Every approved
> write appends an immutable audit row."

---

### Constraint #4 — Citations + trace on every answer

> Every answer must carry source citations (RAG document refs)
> and an MCP execution trace (which tools ran, in what order,
> with what inputs/outputs).

**Enforced in three places:**

1. **Schema-enforced.** `core/domain.py:ChatResponse` makes
   `citations` and `trace` required, non-optional fields. The
   FastAPI response model rejects responses that omit them.
2. **Builder-enforced.** `apps/backend/orchestrator/answer.py`
   always populates both, even on failure paths (an empty list
   is the worst case, never a missing field).
3. **GUI-rendered.** The assistant message card always shows
   the citation count pill and the trace-step count pill. The
   workspace column shows the full lists below the fold.

**How to talk about it:**

> "Required fields in the response schema. Empty lists are
> allowed but missing keys aren't. The GUI surfaces the
> counts as pills on every answer."

---

### Constraint #5 — No secrets in code or commits

> Provide `.env.example` with placeholders. No real keys.

**Enforced in three places:**

1. **`.env.example`** has every secret as `replace-me`.
2. **CI guard.** `.github/workflows/ci.yml` runs `grep -rn
   os.getenv apps/ mcp-servers/ rag/ connectors/` and fails if
   any module outside `core/` reads the environment directly.
   All env access goes through `core.config.Settings`.
3. **Repo-wide grep.** `docs/submission-message.md` § 1.3 cites
   a zero-match grep for `sk-…`, `api_key=...` patterns, etc.

**How to talk about it:**

> "Two CI guards. One greps for real keys; the other blocks
> `os.getenv` outside `core/`. Every secret goes through
> `core.config.Settings`."

---

### Constraint #6 — RAG defends against prompt injection

> RAG must defend against prompt injection from retrieved
> documents and must handle no-result / low-confidence cases
> explicitly.

**Enforced in four places:**

1. **Blocklist.** `rag/retrieval/injection.py` carries a
   list of patterns ("ignore previous instructions", "you are
   now...", etc.) that drop a chunk before it reaches the LLM.
2. **Two seeded corpus documents** deliberately embed such
   patterns — so the defence is exercised in every demo and
   every test.
3. **`dropped_count`** is a first-class field on `ChatResponse`.
   The operator sees "2 document chunks were dropped by the
   prompt-injection blocklist" as a UI note.
4. **Low-confidence handling.** `rag/retrieval/low_confidence.py`
   checks the top score against a threshold. Below it, the
   response carries `rag_confidence: "low"` and the GUI shows
   a red `RAG · LOW` pill.

**How to talk about it:**

> "Three layers. Blocklist filter runs before chunks reach the
   prompt. Two seeded corpus docs exercise the filter so we know
   it works. The dropped count is surfaced to the operator as
   a transparency signal. And low-confidence answers are
   flagged, not hidden."

---

### Constraint #7 — Repository must run from a clean env

> The repository must run from a clean environment via
> `docker compose up --build`. Hidden setup steps are a red
> flag.

**Enforced in three places:**

1. **`docker-compose.yml`** defines 7 services: copilot-backend,
   frontend, alarm-api, alarm-management-mcp, ticketing-mcp,
   ticket-mock, vector-store. One command brings them all up.
2. **`Makefile`** wraps the common operations: `make install`,
   `make ingest`, `make up`, `make down`, `make test`,
   `make lint`.
3. **`docs/deployment-verification.md`** records the § 9.2.1
   verification: every service healthy within ~30 seconds on a
   clean clone.

**How to talk about it:**

> "`make install && make ingest && make up` brings the entire
> stack up. No hidden setup. CI verifies the same flow on a
> fresh runner."

---

### Constraint #8 — No hard-coded answers

> Hard-coded answers to the sample questions are a red flag.
> Intent detection / planning must be general, not scripted.

**Enforced in three places:**

1. **`MockPlanner`** is a general NL→slots extractor. It
   doesn't pattern-match "boiler" → "investigate_recurring_alarms".
   It tokenizes, looks for time windows, asset references,
   severity hints — and produces a `Plan` for any question
   with that shape, including ones the author never saw.
2. **The LLM planner path is the same shape.** Swapping
   `PLANNER_PROVIDER=mock` to `llm` swaps implementations
   without changing the orchestrator.
3. **Verification.** `docs/submission-message.md` § 20
   (Hard constraint #8) cites the canonical question being
   preserved verbatim through the planner, not matched against
   a fixed script.

**How to talk about it:**

> "The planner is an NL→slots extractor, not a regex. The
> canonical question is preserved verbatim through it. Swap to
> the LLM planner with a single config switch."

---

## How to remember all eight

Here's a memory hook — group them by *what they protect*:

| What it protects | Constraints |
|---|---|
| **The integration boundary** | #1 (MCP-only), #5 (no secrets) |
| **The output quality** | #2 (both pillars), #4 (citations + trace) |
| **The write authority** | #3 (explicit approval) |
| **The runtime correctness** | #6 (injection defence), #7 (clean env) |
| **The generalisability** | #8 (no hard-coded answers) |

Three pairs plus two singletons. The pairings help you
remember which constraints travel together.

---

## If asked in the interview

**Q: "How do you enforce that the orchestrator doesn't bypass
MCP?"**

> Architecturally — there's no `httpx` client in
> `apps/backend/orchestrator/`. And CI greps for any new
> `httpx` import outside the MCP server.

**Q: "How do you prevent prompt injection?"**

> A blocklist filter in `rag/retrieval/injection.py` runs
> before retrieved chunks reach the LLM. Two seeded corpus
> docs deliberately embed injection patterns, so the filter
> is exercised in every demo. Dropped chunks are counted and
> surfaced to the operator.

**Q: "What stops a forged client from writing a ticket?"**

> The ticket-mock returns 403 unless `approved == true`. So
> even if someone replays a `/tickets/draft` call directly,
> they can't bypass the approval flag. And every approved
> write appends an immutable audit row.

---

## Open questions for next time

- *What patterns are in the injection blocklist?* →
  `rag/retrieval/injection.py` source.
- *What's the exact threshold for low-confidence?* →
  `rag/retrieval/low_confidence.py` constants.
- *Can the audit log be tampered with?* →
  `connectors/ticket_mock/store.py` + decision #11.
