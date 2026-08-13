# 07 — Testing strategy

> **What this answers.** 471 tests is a lot. What does each
> layer test? What's the one test that covers everything?
> What's the CI guard, and what does it actually do?

---

## The numbers

```
471 tests passed
 1 test deselected (slow_embeddings — downloads a HF model on first run)
88% coverage overall
```

Per package, coverage is held at or above its baseline
threshold (see `docs/coverage-baseline.md`).

---

## The three test layers

The project follows the standard **unit / integration / e2e**
pyramid:

```
            ┌───────┐
            │  e2e  │ 1 test
            └───────┘
         ┌─────────────┐
         │ integration │ 167 tests
         └─────────────┘
     ┌───────────────────┐
     │       unit        │ 303 tests
     └───────────────────┘
```

### Unit (303 tests)

What's tested at this layer: **single-function behaviour** in
isolation, with no I/O.

| Package | What's tested |
|---|---|
| `core/` | config singleton, domain models, logging contextvars, exception types, utility helpers |
| `apps/backend/orchestrator/` | planner NL→slots, chain runner step ordering, answer composition, citation formatting, conversation store, LLM client (mock), incident builder, rag step, ticket step |
| `apps/frontend/` | chat client + ticket client (request construction, response parsing, error mapping), UI smoke tests via `AppTest`, workspace column smoke tests |
| `rag/` | loader (markdown parse), chunker (size + overlap), embedder (deterministic), index (persist/load), retrieval service (search + ranking + filtering), citation formatter, low-confidence threshold, prompt-injection defence, retrieval corpus, orchestrator-rag glue, full pipeline |
| `connectors/ticket_mock/` | audit append, draft builder, search, in-memory store |

The frontend unit tests use `streamlit.testing.v1.AppTest`
which boots the Streamlit script headlessly. That's how
`test_sidebar_suggested_prompt_dispatches_chat` (added in PR
#97) drives a real click and asserts the chat client was
called.

### Integration (167 tests)

What's tested at this layer: **module interactions over real
HTTP, but with in-process servers**.

| Suite | What it covers |
|---|---|
| `integration/alarm_api/` | auth header propagation, the 15 endpoints against the in-process simulator, the seed data is what we expect, the ticket endpoints compose correctly, the trace header round-trips |
| `integration/mcp_server/` | MCP server health, tool registration against the manifest, retry policy on transient 5xx + transport blips, every tool returns valid JSON, `tools/list` enumeration |
| `integration/mcp_server_ticketing/` | the 2 ticketing tools |
| `integration/orchestrator/` | the brief's § 7 e2e scenario, ticket e2e |
| `integration/ticket_preview/` | the read-only draft projection endpoint |
| `integration/ticket_mock/` | the in-process ticket service |
| `integration/scripts/` | the Newman-driven Postman collection runner |

These spin up the FastAPI apps in-process and exercise them
via `httpx.AsyncClient`. No Docker required.

### End-to-end (1 test)

`tests/e2e/test_full_workflow_mcp_rag.py` — the one test that
the brief explicitly requires.

It runs the canonical scenario end-to-end and asserts:

- `answer` is non-empty
- `citations` is non-empty (RAG produced)
- `trace` is non-empty (MCP produced)
- `incident` is a fully-populated structured payload

If any of these fail, the brief's hard constraints #2 and #4
have been violated.

---

## What's NOT in the test suite

Things deliberately left untested:

- **The full Docker Compose stack** — covered separately by
  `docs/deployment-verification.md` (the § 9.2.1 verification
  record). Putting this in pytest would require Docker-in-
  Docker and slow CI.
- **LLM quality** — the mock LLM returns canned answers, so
  the assertion is "the mock's output reached the GUI", not
  "the answer is good". Quality measurement is out of scope
  for the demo.
- **Real industrial data** — the brief forbids it (constraint
  #7). All test data is synthetic.

---

## The CI guard (the test that isn't a test)

`.github/workflows/ci.yml` has a step that isn't a pytest run
but is just as critical:

```yaml
- name: Enforce MCP-only alarm path
  run: |
    ! grep -rn "httpx" apps/ mcp-servers/ rag/ connectors/ \
      | grep -v "mcp-servers/alarm-management/" \
      | grep -v "connectors/alarm_api/"
```

If any module outside the MCP server or its connector adds an
`httpx` import, CI fails. That's how hard constraint #1 stays
enforced.

There's also:

```yaml
- name: Enforce config via core/
  run: |
    ! grep -rn "os.getenv" apps/ mcp-servers/ rag/ connectors/ \
      | grep -v "core/"
```

If anything outside `core/` reads an environment variable
directly, CI fails. That's how hard constraint #5 stays
enforced.

---

## Why this pyramid shape

- **Lots of unit tests** — they're fast, deterministic, and
  isolate regressions. ~50ms per test on average.
- **Medium integration count** — they catch wiring bugs that
  unit tests can't (auth header propagation, retry on
  real FastAPI middleware, etc.).
- **One e2e test** — the brief requires it, and one is enough
  to verify the happy path. More e2e tests would be flaky
  and slow.

---

## The brief's mandate vs what's tested

The brief lists specific surfaces:

| Brief requirement | Where it's tested |
|---|---|
| Unit: payload construction, validation, parsing, tool selection, citation formatting, retrieval filtering | covered across `tests/unit/` |
| MCP server: registration, discovery, schema validation, auth headers, pagination, timeouts, retries, error mapping, trace propagation | `tests/integration/mcp_server/` + `tests/integration/alarm_api/` |
| MCP client: connectivity, discovery, invocation, invalid args, missing tools, partial failure | `tests/integration/orchestrator/` |
| RAG: ingestion, chunking, metadata, relevance, citation correctness, no-result, prompt-injection | `tests/unit/rag/` |
| Orchestration: multi-step MCP chains, MCP output piped into next tool, RAG within the same workflow, partial source failure, conflicting evidence | `tests/integration/orchestrator/` + `tests/e2e/` |
| One end-to-end test combining MCP + RAG | `tests/e2e/test_full_workflow_mcp_rag.py` |

All bases covered.

---

## If asked in the interview

**Q: "How do you test the system end-to-end?"**

> One e2e test runs the canonical scenario through the real
> orchestrator, MCP servers, and RAG service. It asserts both
> pillars produced output and the incident payload is complete.
> Plus 167 integration tests cover the modules, and 303 unit
> tests cover the functions.

**Q: "How do you enforce the MCP-only path?"**

> Two ways. The orchestrator has no HTTP client — only the MCP
> client. And CI greps for `httpx` imports outside the MCP
> server and fails the build if any appear.

**Q: "What's your test pyramid?"**

> 303 unit, 167 integration, 1 e2e. The shape reflects what
> each layer is good at catching: units for regressions,
> integration for wiring bugs, e2e for the happy path through
> the full system.

---

## Open questions for next time

- *How long does the e2e test take?* → it's marked slow and
  runs in CI but not locally by default.
- *What's the coverage floor per package?* →
  `docs/coverage-baseline.md`.
- *What's the retry policy tested in `test_retry.py`?* → that
  file, plus decision #7 in `docs/design-decisions.md`.
