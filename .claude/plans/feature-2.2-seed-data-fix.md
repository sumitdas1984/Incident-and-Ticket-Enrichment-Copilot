# Plan — Fix CHAIN-08 Motor Correlation seed-data gap

> **Context.** `make validate-api` runs the Alarm API simulator + both Postman collections via Newman. The chaining collection's CHAIN-08 (`GET /assets/search?query=motor&unit=Unit%205&limit=5`) expects ≥1 motor asset in Unit 5, but the seed has only 1 motor total (`asset-motor-m1`, Unit 5) and the search filter returns 0 results for that query. The Postman test asserts `r.length > 0`, so the chain fails with `expected +0 to be above +0`. The scenarios collection passes 15/15; chaining runs all 32 requests but with 1 test-script failure on CHAIN-08.
>
> This plan patches the seed so CHAIN-08 passes, leaves the search filter alone, and adds regression coverage so a future seed edit cannot re-break the chain.

---

## 1. Goal

`bash scripts/run_validate_api.sh` exits 0 — both collections pass — when run against the simulator on a clean checkout.

CHAIN-08 passes because the seed now produces ≥1 motor asset in `Unit 5` that the search endpoint surfaces.

## 2. Approach

Two files changed, plus regression coverage. No search-filter rewrite, no Postman collection change, no new Story.

### 2.1 `connectors/alarm_api/seed.py` — populate `metadata["unit"]` on every asset, and add two more motor assets in Unit 5

The store's `search_assets()` filter reads `a.metadata.get("unit") == unit` as its primary unit-match path. The fallback heuristic `a.name.endswith("Unit " + unit.split()[-1])` does not match `"Motor M1"` (the asset's name), so today's seed produces 0 hits. Fixing this at the search-filter level would also work, but it's the store's job to know what its own seed data is; the seed must be self-describing.

Two coordinated edits:

1. **Every existing `Asset(...)` gets `metadata={"unit": <unit-value>}`** so the primary unit filter in `search_assets` matches against the same value the seed declares top-level. This is the "make seed self-describing" half of the fix and unblocks any future chaining test that filters on `unit`.
2. **Add 2 more motor assets in `Unit 5`** (`asset-motor-m2`, `asset-motor-m3`) with matching alarms so CHAIN-08's assertion (`r.length > 0`) is robust against seed edits, and CHAIN-08's later chaining steps (Correlation → Summary Context) have multiple motor alarms to summarise. Names follow the existing convention (`Motor M2`, `Motor M3`). Each gets 1 alarm of mixed severity (`MEDIUM`, `LOW`) and acknowledgment state, to vary the Summary Context response.

Both edits keep the data deterministic: every alarm timestamp is fixed, every id is fixed. The Postman collection's `pm.collectionVariables.set('asset_id'/'asset_id_2'/'asset_id_3')` chain then resolves three real asset ids.

### 2.2 `tests/integration/alarm_api/test_seed.py` — new file, regression tests

Three tests, one per claim:

1. **`test_seed_has_three_motors_in_unit_5`** — loads the module-level `SEED_ASSETS`, asserts ≥3 assets where `asset_class == "motor"` AND `unit == "Unit 5"`. Locks in the data shape CHAIN-08 depends on.
2. **`test_seed_metadata_matches_top_level_unit`** — for every asset in `SEED_ASSETS`, asserts `metadata.get("unit") == unit` (or unit is `None`, in which case metadata may be empty). Locks in the "self-describing seed" invariant so a future developer can't add an asset without populating metadata.
3. **`test_search_motors_in_unit_5_returns_three`** — boots the FastAPI app via `TestClient`, calls `GET /assets/search?query=motor&unit=Unit%205&limit=5`, asserts the response has 3 results and all carry `unit == "Unit 5"`. This is the end-to-end check that mirrors the Postman assertion. Uses the existing `TestClient` + `ALARM_API_TOKEN` fixture pattern from `tests/integration/alarm_api/test_endpoints.py`.

### 2.3 No changes to `postman/` or the search filter

The Postman collection is the contract; it stays. The search filter is what it is — the seed must match its expectations. A separate cleanup Story can simplify the filter later if desired; not in scope here.

## 3. Non-goals

- Not rewriting `search_assets()` to read from `a.unit` instead of `a.metadata.get("unit")`. That's a separate refactor Story.
- Not changing the Postman collection (it's the contract).
- Not modifying the scenarios collection or its assertions.
- Not adding new endpoints or alarm-class fields.
- Not extending coverage to all 10 chains — only CHAIN-08's specific gap.

## 4. Critical files

- `connectors/alarm_api/seed.py` — populate `metadata` on all 5 existing assets; add `asset-motor-m2` and `asset-motor-m3` (with 2 new alarms).
- `tests/integration/alarm_api/test_seed.py` — new file, 3 tests.
- `connectors/alarm_api/store.py` — unchanged (read-only).
- `postman/chaining/Alarm-API-Chaining.postman_collection.json` — unchanged.

## 5. Verification

1. **Local sanity**: `uv run pytest -ra` → all tests pass (96 prior + 3 new = 99).
2. **End-to-end**:
   ```bash
   bash scripts/run_validate_api.sh
   ```
   Both collections must print PASS, and the simulator log must show CHAIN-08's three `/assets/search?query=motor&unit=Unit%205...` returning a 200 with a non-empty body.
3. **Lint + types**: `uv run ruff check . && uv run mypy apps rag connectors core` clean.
4. **Seed invariance**: `grep -c "asset-motor-m" connectors/alarm_api/seed.py` must report exactly 3 (asset id references + new assets).

## 6. Rollback

Trivial — `git revert` the commit. Seed is committed; no migrations, no persisted state, no API contract changes. The chaining collection reverts to its prior CHAIN-08 failure.

---

**Awaiting sign-off.** Reply "approved" to apply, or send edits.