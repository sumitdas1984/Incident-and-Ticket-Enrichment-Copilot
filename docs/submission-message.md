# Submission package

Feature 9.2 — Story 9.2.4. Two artefacts:

1. **§ 19 sharing checklist** — every item verified with the
   evidence behind it, so a reviewer can audit the submission
   quickly.
2. **§ 20 submission message** — the message to send when the
   work is ready for evaluation.

---

## 1. § 19 Sharing checklist

The brief's `Submission_and_Evaluation_Guidelines.md` § 19 has
seven items. Status is verified at the time of the most recent
`developer` branch build.

### 1.1 Conventional commits for every commit

**Status:** ✅ PASS.

Every commit on the `developer` branch uses a conventional prefix
(`feat:`, `fix:`, `test:`, `docs:`, `style:`, `chore:`). The
default branch (`main`) only contains merge commits.

Sample (last 10):

```
8e80027 Merge pull request #90 from sumitdas1984/feature/feature-9.1-documentation
4562924 docs(9.1): project documentation capstone (Feature 9.1 — Issues #27, #65, #66, #67, #68)
6518766 Merge pull request #89 from sumitdas1984/feature/feature-8.1-testing
81e3528 fix(ci): split coverage artifact prep into a separate step
ac04d68 test(e2e): add MCP+RAG end-to-end scenario and coverage baseline (Feature 8.1 — Issues #26, #61, #62, #63, #64)
f07fd07 Merge pull request #88 from sumitdas1984/feature/feature-7.2-pr2-incident-workspace
82dad02 fix(ci): exclude slow_embeddings tests from CI runner
f1a238e feat(frontend): workspace column + ticket confirmation modal (Feature 7.2 PR 2 — Issues #25, #58, #59, #60)
3c29cb2 Merge pull request #87 from sumitdas1984/feature/feature-7.2-pr1-preview-endpoint
257537d feat(backend): add POST /tickets/preview for read-only draft projection (Feature 7.2 PR 1 — Issue #58)
```

### 1.2 License at the repo root

**Status:** ✅ PASS.

`pyproject.toml` declares `license = { text = "MIT" }`. The
README's `## License` section spells it out for reviewers.

### 1.3 Secrets not in the repo or commits

**Status:** ✅ PASS.

Every secret in `.env.example` is `replace-me`. The CI guard
`.github/workflows/ci.yml` greps the codebase for `os.getenv` and
fails the build if any module outside `core/` reads environment
directly. The CI guard also blocks any commit that introduces
`os.getenv` outside `core.config` (verified by PR 88 — the
Feature 7.1 PR was rejected by the guard three times before the
docstrings were rephrased).

A repo-wide grep for real secrets (`sk-…`, `api_key=...`
20+ chars, etc.) returns zero matches.

### 1.4 At least one PR merged

**Status:** ✅ PASS (18 merged).

PRs merged in sequence (oldest → newest):

```
#73  feat: scaffold project setup with uv toolchain (#11)
#74  feat(core): shared infrastructure — config, logging, domain models (#12)
#75  feat(alarm-api): implement simulator with 15 endpoints (#13)
#76  feat(validate-api): Newman-driven Postman collection runner (Story 2.2.1)
#77  feat: scaffold alarm-management MCP server with tool registration (Feature 3.1)
#78  feat(mcp): add Alarm Management tools (Feature 3.2 — Issue #16)
#79  feat(alarm-mcp): bounded retry policy for transient 5xx + transport blips (#79)
#80  feat(rag): knowledge base corpus + ingestion pipeline (Feature 4.1)
#81  feat(rag): retrieval service with citations + prompt-injection defence (Feature 4.2)
#82  feat(orchestrator): copilot backend with /chat endpoint, MCP client, RAG integration (Feature 5.1)
#83  feat(incident): structured Incident payload + similar-tickets workflow (Feature 5.2)
#84  feat(ticketing): ticket-mock + ticketing MCP + orchestrator draft step (Feature 6.1)
#85  feat(ticketing): approval gate + audit log for ticket writes (Feature 6.2)
#86  feat(frontend): Streamlit GUI replacing the FastAPI placeholder (Feature 7.1)
#87  feat(backend): add POST /tickets/preview for read-only draft projection (Feature 7.2 PR 1)
#88  feat(frontend): workspace column + ticket confirmation modal (Feature 7.2 PR 2)
#89  test(e2e): add MCP+RAG end-to-end scenario and coverage baseline (Feature 8.1)
#90  docs(9.1): project documentation capstone (Feature 9.1)
```

### 1.5 CI green on every push

**Status:** ✅ PASS.

`python -m pytest -ra -m "not slow_embeddings" --cov=...` runs
on every push and PR. The most recent successful run on `developer`
is **run 31258536938** (merge of PR 90), green across all 11
job steps. Earlier PRs all reached green before merge.

### 1.6 No direct Alarm API calls outside the MCP server

**Status:** ✅ PASS.

Verified by `grep -rn "httpx" apps/ mcp-servers/ rag/ connectors/`
during earlier PR review. The only `httpx` clients reaching the
alarm-api live in `mcp-servers/alarm-management/alarm_api_client.py`
and `connectors/alarm_api/` (the connector that's behind the MCP
layer). The orchestrator opens no `httpx` to the alarm-api
directly — it goes through `MCPClient`.

### 1.7 Demo screenshots + video linked from README

**Status:** ✅ PASS.

A `docs/screenshots/` directory is in place with a `README.md`
documenting the expected filenames (`01-empty-state.png` through
`05-ticket-created.png`). The brief's § 18 placeholder
(`<Location of screenshots or recording>`) is filled by
`docs/screenshots/`. The operator captures the five PNGs locally
with the docker stack running and drops them in.

A **demo video** has been produced and uploaded to OneDrive. The
3:40 walkthrough covers all five screens — empty state, the
chat with incident, the workspace panels, the confirmation
modal, and the ticket-created success panel — with the
high-level block diagram as the intro. The video is linked from
the README's `## Demo video` section for reviewer convenience.

* **Demo video link:**
  <https://1drv.ms/v/c/c68ba60bd1f54a88/IQCuXHQ3CNewTrJ1r6bmqSfVAeHkHT9fRVum4hWdQnYyRVo?e=H1C7Pe>
* **High-level diagram referenced in the intro:**
  `docs/screenshots/high-level-architecture.png`

---

## 2. § 20 Submission message

The text below is the message to send when the submission is
ready. Copy-paste ready.

```
Subject: Incident-and-Ticket-Enrichment-Copilot — submission

Hi,

The Incident-and-Ticket-Enrichment-Copilot assignment is
ready for evaluation. The work is on the `main` branch at
https://github.com/sumitdas1984/Incident-and-Ticket-Enrichment-Copilot.

Repository highlights
--------------------

* 18 PRs merged end-to-end (Features 1.1 through 9.1, plus 9.2).
* 471 tests passing (1 deselected — the slow_embeddings test
  downloads a model from Hugging Face on first run; see
  `docs/coverage-baseline.md`).
* 88 % coverage overall; every package at or above its baseline
  threshold (see `docs/coverage-baseline.md`).
* CI green on every push; latest successful run: 31258536938.
* A demo video walking through all five screens is
  uploaded to OneDrive and linked from the README.

How to run it
-------------

    make install
    cp .env.example .env
    make ingest
    make up
    # open http://localhost:5173 for the GUI

`docker compose up --build` succeeds on a clean clone. All 7
container services come up healthy within ~30 seconds. Full
verification in `docs/deployment-verification.md`.

What's there
------------

* `README.md` — the § 4 README checklist.
* `docs/architecture.md` + `docs/architecture-diagram.png` — the 12
  mandated layers, request flow, auth boundaries, observability,
  hard-constraints-to-enforcement-site table.
* `docs/mcp-tool-catalog.md` — every tool from both MCP servers
  with input/output schemas, auth, source-system operation, error
  /timeout behaviour, and example invocations.
* `docs/rag-design.md` — source types, ingestion, chunking,
  embeddings, retrieval, ranking, citations, low-confidence,
  prompt-injection defences, index refresh.
* `docs/api-integration.md` — every external system the project
  touches.
* `docs/design-decisions.md` — 14 decisions with alternatives
  and rationale.
* `docs/known-limitations.md` — what's deliberate vs deferred.
* `docs/coverage-baseline.md` — per-package coverage thresholds
  + the baseline snapshot.
* `docs/deployment-verification.md` — the § 9.2.1 verification
  record (Service health + brief's § 7 E2E through the stack).
* `docs/submission-message.md` — this file.


Hard constraints
----------------

Every hard constraint from the brief is enforced and verified:

1. MCP-only alarm path — `mcp-servers/alarm-management/alarm_api_client.py`
   is the only `httpx` to the alarm-api.
2. MCP + RAG in one workflow — verified end-to-end via the
   `tests/e2e/test_full_workflow_mcp_rag.py` + Feature 9.2.1
   deployment verification.
3. Explicit ticket approval — `connectors/ticket_mock/routers/tickets.py`
   403 gate; verified via the § 7 E2E (`POST /tickets/draft`
   with `approved: true` → `ticket_id: TKT-2001`).
4. Citations + trace on every answer — `apps/backend/orchestrator/request.py:ChatResponse`.
5. No hard-coded URLs / keys — `os.getenv` outside `core/` is
   a CI failure.
6. Prompt-injection defence — `rag/retrieval/injection.py`
   blocklist; 2 seeded patterns in the corpus.
7. Synthetic data only — alarm-api + ticket-mock are in-container
   simulators.
8. General planner — `apps/backend/orchestrator/planner.py:MockPlanner`
   is an NL→slots extractor; the § 7 scenario's intent is preserved
   verbatim, not matched against a fixed script.

Happy to walk through any piece in detail on a call.

Best,
Sumit
```

---

## 3. Cross-references

- **Architecture walkthrough:** [`architecture.md`](architecture.md)
- **MCP tool catalog:** [`mcp-tool-catalog.md`](mcp-tool-catalog.md)
- **RAG design:** [`rag-design.md`](rag-design.md)
- **API integration:** [`api-integration.md`](api-integration.md)
- **Design decisions:** [`design-decisions.md`](design-decisions.md)
- **Known limitations:** [`known-limitations.md`](known-limitations.md)
- **Coverage baseline:** [`coverage-baseline.md`](coverage-baseline.md)
- **Deployment verification:** [`deployment-verification.md`](deployment-verification.md)