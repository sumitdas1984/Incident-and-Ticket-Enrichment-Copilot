# Feature 8.1 — Testing

> **Context.** Feature 8.1 (issue #26) is the testing epic's
> capstone. The brief (`Submission_and_Evaluation_Guidelines.md`
> § 13) requires automated tests at every layer — unit, MCP server,
> MCP client, RAG, orchestration, and at least one end-to-end
> scenario combining MCP and RAG. § 15 requires CI to run all of
> them. The acceptance criteria include "Coverage ≥ 80 % on the
> core packages."
>
> Issue #26 has four sub-issues (#61, #62, #63, #64) corresponding
> to Stories 8.1.1-8.1.4. Required by Feature 9.2 (submission
> requires green CI).
>
> **Outcome.** A single PR that:
> 1. Lands a real `tests/e2e/` MCP+RAG scenario (the only test
>    gap against the brief).
> 2. Wires `pytest-cov` into CI so every push produces a coverage
>    report (Story 8.1.1's "≥ 80 %" signal).
> 3. Commits a baseline coverage snapshot to `docs/coverage-baseline.md`
>    so a regression is easy to spot.

---

## Why this plan is small

By the time Feature 8.1 starts, the test surface is already
**471 passing tests** (was 442 before Feature 7.1 + 18 from
Feature 7.2 + 11 from Feature 7.2 PR 1). Stories 8.1.1 (unit),
8.1.2 (MCP), and 8.1.3 (RAG) are met by the existing tests —
they were added incrementally under each preceding feature
(Stories 5.x, 6.x, 7.x each came with their own unit +
integration tests, as documented in the brief's § 13 TDD
expectation).

What's actually missing:

* **Story 8.1.4** — "`pytest tests/e2e` exercises the § 7 E2E
  scenario." `tests/e2e/` is empty today. The brief's
  mandatory scenario is exercised by
  `tests/integration/test_orchestrator_e2e_acceptance.py` but
  that lives under `tests/integration/`, not `tests/e2e/`. The
  story's acceptance criterion names the `tests/e2e` path
  explicitly.
* **Story 8.1.1** — coverage is at 87 % overall but there is no
  coverage signal in CI. `pytest-cov` is in `pyproject.toml` but
  not invoked. The brief's § 13 says "Coverage report is generated
  and committed."

The rest of the Feature 8.1 stories (8.1.2, 8.1.3) have already
been delivered as part of Epics 3, 4, and 5. CI runs every test
layer on every push, satisfying § 15.

---

## File-by-file plan

### 1. `tests/e2e/test_full_workflow_mcp_rag.py` (NEW)

A real end-to-end test that:

* Boots an in-process uvicorn MCP server with three canned tools
  (`search_assets`, `summarize_alarms`, `search_similar_tickets`)
  on a free port. Each tool returns deterministic canned data.
* Builds an in-memory RAG index with three chunks covering the
  boiler asset.
* Wires a real `OrchestratorBundle` (ChainRunner + MockPlanner +
  ConversationStore) pointing at both the test MCP server and the
  test RAG index.
* Posts the brief's mandatory scenario to `POST /chat` and
  asserts:
  - Non-empty `answer` (the composed response).
  - Non-empty `citations` carrying the expected `doc_id`.
  - `trace` contains an MCP step with `outcome='success'`
    (this is the key new signal — the existing acceptance test
    only saw `outcome='error'` because its MCP server had no
    tools registered).
  - `rag_confidence` band present.
  - Structured `Incident` payload populated.
  - `conversation_id` echoed back.

The test reuses the `mcp_url` / `mcp_server` fixture pattern
from `tests/integration/test_orchestrator_e2e_acceptance.py`,
adapted to register real tools via `MCPServer.tool(...)`.

### 2. `docs/coverage-baseline.md` (NEW)

A committed snapshot of the current per-package coverage
numbers, the thresholds below which the team should treat the
signal as actionable, and a "Known gaps (deliberate)" section
documenting the modules below threshold and why.

### 3. `.github/workflows/ci.yml` (MODIFY)

The pytest command gains `--cov=apps --cov=rag --cov=connectors
--cov=mcp_servers --cov=core`. A follow-up `Upload coverage
artifact` step saves the `.coverage` file under
`coverage-artifact/` for inspection.

The slow_embeddings exclusion is unchanged from PR 88.

### 4. No code-side changes

The application source is unchanged. Feature 8.1 is purely a
test surface + CI surface change.

---

## Tests

| File | New | Notes |
|---|---|---|
| `tests/e2e/test_full_workflow_mcp_rag.py` | 1 | New scenario. |

### Per-package coverage expectations (baseline)

Per `docs/coverage-baseline.md`:

| Package | Min |
|---|---|
| `core/` | 95 % |
| `rag/` (excluding `__main__.py`) | 80 % |
| `apps/backend/` (excluding `__main__.py`) | 70 % |
| `apps/frontend/` (excluding `__main__.py`) | 80 % |
| `connectors/` (excluding `__main__.py`) | 80 % |
| `mcp-servers/` | 80 % |

Baseline today: **87 % overall**, every package at or above
its threshold (some deliberately below — see the baseline doc's
"Known gaps" section).

---

## Verification

```
uv run ruff check .
uv run mypy --explicit-package-bases apps rag connectors core
uv run pytest -ra -m "not slow_embeddings" \
  --cov=apps --cov=rag --cov=connectors \
  --cov=mcp_servers --cov=core
```

Expected: 471 → 472 tests pass, coverage report generated, no
regression vs the baseline numbers in `docs/coverage-baseline.md`.

The CI runner (`/jobs/basic`) picks up the new `--cov` flags
automatically. A failure in the e2e test fails the build.

---

## What this plan deliberately does NOT do

* No new runtime dependencies. `pytest-cov` is already in
  `pyproject.toml`'s dev extras (added in Feature 1.1's
  scaffolding); we're just invoking it.
* No new MCP or RAG code. The canned tools return canned data
  by design — the test asserts that MCP + RAG *together*
  produce the brief's required response shape.
* No changes to existing test files. The acceptance test under
  `tests/integration/test_orchestrator_e2e_acceptance.py` stays
  in place; it tests a different scenario (empty MCP server,
  partial-failure chain) which the brief's "MCP + RAG working
  together" requirement complements.

---

## Rollback

* Delete `tests/e2e/test_full_workflow_mcp_rag.py` — no
  production code is affected.
* Revert `.github/workflows/ci.yml` to remove the `--cov` flags
  and the artifact upload step.
* Delete `docs/coverage-baseline.md`.

The remaining 471 tests stay green either way.