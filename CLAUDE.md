# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repo is

Assignment package for the **Incident and Ticket Enrichment Copilot** use case. The repo currently contains only the brief, evaluation guidelines, and the reference API specification — implementation is not yet present. Authoritative requirements live in:

- `Assignment_Use_Case.md` — objective, mandatory technical scope, business scenario, acceptance scenario, deliverables.
- `Submission_and_Evaluation_Guidelines.md` — repo layout, MCP/RAG documentation requirements, packaging, CI, security, scoring weights, red flags.
- `postman/` — reference Postman collections that define the Alarm Management API contract. Implement the Alarm API simulator from these, then wire the MCP server to it.
- `pyproject.toml` — Python ≥ 3.13, project name `incident-and-ticket-enrichment-copilot`. Dependencies are intentionally empty; add them as components are introduced.

## Hard constraints (must not be violated)

These are enforced by the brief and the evaluation. Treat them as acceptance criteria, not suggestions.

1. **The copilot must call the Alarm Management API exclusively through the MCP server.** Direct API calls in the orchestration layer are a red flag. Direct calls are allowed only inside the MCP server's connector.
2. **MCP and RAG must participate in the same end-to-end business workflow.** A disconnected RAG demo or a disconnected MCP demo is grounds for rejection.
3. **Ticket / issue creation is a write operation.** It must require explicit user confirmation in the GUI before the MCP server is invoked.
4. **Every answer must carry source citations** (RAG document refs) **and an MCP execution trace** (which tools ran, in what order, with what inputs/outputs).
5. **No secrets in code or commits.** Provide `.env.example` with placeholders. The brief lists: `ALARM_API_BASE_URL`, `ALARM_API_TOKEN`, `MCP_SERVER_URL`, `LLM_PROVIDER`, `LLM_API_KEY`, `VECTOR_STORE_URL`, `DOCUMENT_PATH`, `TICKETING_API_URL`.
6. **RAG must defend against prompt injection** from retrieved documents and must handle no-result / low-confidence cases explicitly.
7. **The repository must run from a clean environment** via `docker compose up --build` (or equivalent documented path). Hidden setup steps are a red flag.
8. **Hard-coded answers to the sample questions are a red flag.** Intent detection / planning must be general, not scripted.

## Mandated architecture boundaries

The brief requires clean separation between these layers — keep them as distinct modules/packages:

- GUI (frontend)
- Copilot orchestration (intent + planning + multi-step chaining)
- MCP client / tool registry
- Candidate-developed MCP server (one for Alarm Management; optional second for ticketing)
- API / source-system connectors (inside the MCP server)
- RAG ingestion pipeline
- Retrieval service + index
- Domain models
- Auth + configuration
- Observability (request ID, conversation ID, trace ID, MCP tool, tool duration, retrieval score, etc.)
- Persistence (only where used)

## Expected repository layout

The guidelines prescribe this shape; deviations are acceptable only when documented in the README.

```
apps/{backend,frontend}
mcp-servers/{alarm-management,optional-secondary-server}
rag/{ingestion,retrieval,documents,tests}
connectors/
tests/{unit,integration,e2e}
test-data/
scripts/
docs/{architecture.md, architecture-diagram.png, mcp-tool-catalog.md,
      rag-design.md, api-integration.md, design-decisions.md, known-limitations.md}
.github/workflows/ci.yml
.env.example  Dockerfile  docker-compose.yml  Makefile  LICENSE
```

## Mandatory documentation deliverables

- `docs/mcp-tool-catalog.md` — for every MCP tool: name, purpose, input/output schema, auth behavior, source-system operation, error/timeout behavior, example invocation + response.
- `docs/rag-design.md` — source types, ingestion, extraction, chunking + metadata, embedding/retrieval method, index store, ranking/reranking, filters, citation construction, low-confidence handling, prompt-injection defenses, index refresh.
- `docs/architecture.md` + `docs/architecture-diagram.png` — must explicitly show both the MCP path and the RAG path, plus auth boundaries and observability.

## Mandatory testing surface

At minimum, automated tests must cover:

- Unit (payload construction, validation, parsing, tool selection, citation formatting, retrieval filtering)
- MCP server (registration, discovery, schema validation, auth headers, pagination, timeouts, retries, error mapping, trace propagation)
- MCP client (connectivity, discovery, invocation, invalid args, missing tools, partial failure)
- RAG (ingestion, chunking, metadata, relevance, citation correctness, no-result, prompt-injection)
- Orchestration (multi-step MCP chains, MCP output piped into next tool, RAG within the same workflow, partial source failure, conflicting evidence)
- **One end-to-end test that combines MCP + RAG** in a single scenario.

CI (`.github/workflows/ci.yml`) must run formatting, linting, static analysis, all test layers, build validation, and dependency checks.

## Mandatory E2E acceptance scenario

A scenario similar to: investigate recurring high-severity alarms for a specific asset over the last 90 days, identify likely contributing factors, retrieve the relevant operating procedure, and return recommended actions with source evidence. The demo must show: asset resolution via MCP, multi-step Alarm API chaining via MCP, RAG retrieval, combined reasoning, citations, GUI output, MCP execution trace, and automated e2e test evidence.

## Operational notes

- Use the Postman collections under `postman/` (root collection plus `chaining/` and `scenarios/`) as the API contract when implementing the Alarm API simulator — including auth header, trace header, pagination, and chaining semantics.
- Ticketing can be real (Jira / Azure DevOps / ServiceNow / GitHub Issues) or a candidate-built mock; the MCP exposure is what matters.
- Sample document corpus should include troubleshooting guides, support knowledge articles, historical resolution notes, and escalation procedures. Commit synthetic/public samples with realistic structure; do not commit restricted documents.
- Demo evidence: screenshots or short recordings of MCP tool discovery, MCP execution trace, RAG citations, one successful and one failure/degraded scenario, plus a linked demo video (≤ 10 minutes).
- Commit messages should follow conventional-commit prefixes (`feat:`, `test:`, `docs:`, `fix:`, `chore:`). At least one pull request is expected.
- Suggested time box is 10–14 hours; a smaller fully-integrated MCP+RAG slice is preferred over a broad-but-incomplete implementation.

## What is deliberately not in this file

- Source-code commands (none yet exist; will be added once the layout above is in place).
- Per-component file listings (discoverable via `ls`).
- Generic engineering advice not tied to this assignment's evaluation criteria.