# Plan — Feature 2.2 (Story 2.2.1): API Validation via Postman/Newman

> **Context.** The Alarm API simulator (Feature 2.1, now on `origin/developer`) is the simulated source system. The Postman collections under `postman/` are the contract. Story 2.2.1 says: run every request in `postman/chaining/` and `postman/scenarios/` against the running simulator and confirm green via a repeatable `make validate-api` target. Without a working runner the simulator is "looks right" but not "behaves right" — and the MCP server's connector (Feature 3.1) will be wired against the same simulator, so we want failures here, not there.

---

## 1. Goal

`make validate-api`, run from a clean clone with `make install` previously executed, must:

1. install Newman (Node CLI runner for Postman collections) into a local `node_modules/` if missing,
2. start the alarm-api simulator on a free port with a known bearer token,
3. wait for `/health` to come up,
4. run `postman/chaining/Alarm-API-Chaining.postman_collection.json` end-to-end,
5. run `postman/scenarios/Alarm-API-Scenarios.postman_collection.json` end-to-end,
6. exit 0 only if both collections report 0 failures; non-zero (and a clear banner) on any failure.

## 2. Approach

### 2.1 Add a Newman runner script in `scripts/`

- `scripts/validate_api.py` — Python orchestrator (uses `subprocess` + `requests`); works on Windows (the dev environment) and Linux (CI). Avoids a hard dependency on bash semantics that diverge across GitHub Actions runners.
- Responsibilities:
  - Take `--collection`, `--base-url`, `--token`, `--report-dir` flags.
  - Invoke `npx --no-install newman run <collection> --env-var baseUrl=<…> --env-var auth_token=<…> --reporters cli,htmlextra --reporter-htmlextra-export <report-dir>/<name>.html`.
  - Map Newman's exit code to ours: `0` → pass; anything else → fail with a 1-line summary of failed assertions.
  - Stream Newman stdout to the user's terminal so failures are visible in CI logs.

A single Python script is preferred over a Node script because:

- The repo is Python-first; mixing concerns (Postman runs in Node, but the orchestrator should be the same language as the rest of the test infra).
- CI will run `python scripts/validate_api.py ...` from the same `uv` env that already has `requests` and `pyyaml` available.

### 2.2 Add a Newman bootstrap in `package.json`

- Top-level `package.json` (git-ignored `node_modules/`):
  - `devDependencies`: `newman`, `newman-reporter-htmlextra`.
  - `scripts.install`: `npm install` (idempotent).
- This is the handoff point for CI: `make validate-api` reads `package.json` and runs `npm ci` (or `npm install` on first run) before invoking Newman.

### 2.3 Wire the Makefile target

Replace the existing stub:

```make
validate-api:
    @echo "Placeholder -- wired in Story 2.2.1 once the simulator exists."
```

With a real target that:

```text
validate-api:    # boots the simulator, runs both collections, exits 0 on green
    1. ensure newman is installed: npm install (if node_modules missing)
    2. pick a free port: 8000 (default) or $ALARM_API_VALIDATE_PORT
    3. spawn the simulator: ALARM_API_TOKEN=demo-token ALARM_API_PORT=<port> \
       uv run python -m connectors.alarm_api in background, capture PID
    4. wait for /health (5s timeout, poll every 200ms)
    5. run python scripts/validate_api.py against both collections
    6. on exit, kill the simulator (trap on EXIT)
    7. propagate the validate_api.py exit code
```

Free-port strategy with `socket.SO_REUSEADDR` and a polling wait rather than a fixed port, so parallel CI runs don't collide. (If the user later adds a Dockerised variant, the orchestration approach is the same — only the spawn step changes.)

### 2.4 CI hook (optional but cheap)

Add a `validate-api` job to `.github/workflows/ci.yml` once that workflow exists. Out of scope for this commit because the CI workflow file does not yet exist on `developer` (Feature 1.1 didn't ship one). Story 2.2.1 is accepted when `make validate-api` exits 0 locally.

## 3. Non-goals

- Not adding a Dockerised validate-api run. (The copilot ships `docker compose up --build`; that path is the same simulator + Newman.)
- Not installing Newman as a global tool. (Local + CI both use `npm install` to keep things reproducible.)
- Not changing the Alarm API simulator. (Story 2.2.1 is validation only; if validation turns up a real bug, that's a separate fix-it branch.)
- Not generating the chaining collection from `docs/api_chaining_catalog.json`. (The Postman collections are the contract; we run what's there.)

## 4. Critical files

| File | Purpose |
|---|---|
| `scripts/validate_api.py` | Python orchestrator wrapping Newman |
| `package.json` | Newman + htmlextra as devDependencies |
| `package-lock.json` | Pinned versions for reproducible CI |
| `Makefile` | Replace `validate-api` stub with real target |
| `tests/validation/test_validate_api.py` | Unit test: script maps Newman exit codes correctly |
| `.gitignore` | Add `node_modules/`, `newman-report/` |

## 5. Verification

1. `make install` (already produces a working `uv` env).
2. `make validate-api`:
   - Reports `npm install` (first run) or `npm ci` (subsequent runs).
   - Boots simulator and reports `health OK`.
   - Runs `Alarm-API-Chaining` (10 chained scenarios) and `Alarm-API-Scenarios` (15 single-endpoint E2E requests).
   - Prints `PASS` / `FAIL` summary.
   - `echo $?` → 0.
3. HTML reports land in `newman-report/`; not committed (gitignored).
4. `uv run pytest -ra` → all existing tests still pass (we add 1 validation test for the orchestrator's exit-code mapping).
5. `uv run ruff check .` → clean.
6. `uv run mypy apps rag connectors core` → clean.

## 6. Rollback

`validate-api` is a single Makefile target and a new script. To roll back: `git revert` the merge commit. The simulator, MCP server, and rest of the repo are untouched.

---

**Awaiting sign-off.** Reply "approved" to apply, or send edits.
