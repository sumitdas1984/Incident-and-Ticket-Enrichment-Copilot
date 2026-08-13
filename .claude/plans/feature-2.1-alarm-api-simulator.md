# Feature 2.1 — Alarm API Simulator — Implementation Plan

> Feature: **#13** `[Feature 2.1]: Alarm API Simulator`
> Parent Epic: **#3** `[Epic 2]: Alarm Management Platform`
> Branch: `feature/feature-2.1-alarm-api-simulator`
> Plan author: Claude
> Status: **DRAFT — awaiting user approval before any code changes**

---

## 1. Goal

Replace the placeholder `alarm-api` service with a real, spec-compliant Alarm Management API simulator that honours every endpoint in the three Postman collections (`postman/Alarm-API-Simulator.postman_collection.json` + `chaining/` + `scenarios/`). After this feature merges, the MCP server (Epic 3) has a real backend to call and the Postman chaining flows pass end-to-end.

## 2. API surface (15 endpoints, derived from the Postman collections)

| # | Method | Path | Auth | Trace headers |
|---|---|---|---|---|
| 1 | GET | `/health` | no | no |
| 2 | GET | `/assets/search` | bearer | no |
| 3 | GET | `/assets/{asset_id}/metadata` | bearer | no |
| 4 | GET | `/alarms` | bearer | no |
| 5 | GET | `/alarms/{alarm_id}` | bearer | no |
| 6 | GET | `/analytics/kpi-definitions` | bearer | no |
| 7 | POST | `/alarms/summary` | bearer | yes |
| 8 | POST | `/alarms/trends` | bearer | no |
| 9 | POST | `/alarms/correlation` | bearer | yes |
| 10 | POST | `/alarms/flood-analysis` | bearer | no |
| 11 | POST | `/alarms/rationalization-candidates` | bearer | no |
| 12 | POST | `/alarms/priority-score` | bearer | no |
| 13 | POST | `/recommendations/operator-actions` | bearer | yes |
| 14 | POST | `/calculation-code/generate` | bearer | no |
| 15 | POST | `/calculation-code/execute` | bearer | yes |

Bearer token = `settings.alarm_api_token.get_secret_value()` (default `replace-me`, replaced by `ALARM_API_TOKEN` env var). For local dev with the Postman default, set `ALARM_API_TOKEN=demo-token` in `.env`.

Trace header names: `trace_id`, `x-client-id`, `x-metadata-tag` — when present, the simulator echoes them in the response.

## 3. Acceptance criteria (mirrors GitHub Feature #13)

- [ ] All 15 endpoints respond with the documented JSON shape.
- [ ] Missing/invalid auth → 401 with the standard error envelope.
- [ ] Trace headers round-trip (echoed back in response).
- [ ] Unknown alarm / asset → 404 with structured error body.
- [ ] Errors always carry `{code, message, trace_id, details}` shape.
- [ ] Synthetic data is deterministic (seeded — same seed → same response).
- [ ] `make run-alarm-api` starts the simulator outside Docker.
- [ ] All 10 chaining flows + 14 base E2E requests pass when the Postman collection is run against the simulator.

## 4. Hard constraints from `CLAUDE.md` that apply

- **#5** No secrets in code. The bearer token comes from `Settings.alarm_api_token` (SecretStr). Tests must use a non-default value via `monkeypatch.setenv`.
- **#6** Layer separation — the simulator is the *connector* layer. Nothing imports from MCP / RAG / apps. Only from `core/`.
- **#7** `docker compose up --build` continues to work — the Dockerfile needs no change (the alarm-api image already runs the new `__main__.py`).

## 5. Stories → ordered implementation steps

### Pre-work: nothing (no Dockerfile change)

The `Dockerfile` already runs `uv run python -m ${MODULE_PATH}.__main__` and `MODULE_PATH: connectors.alarm_api` is already in `docker-compose.yml`. The placeholder in `connectors/alarm_api/__main__.py` is the only thing standing between us and a real service.

### Story 2.1.1 — Implement Alarm Management API simulator

**Files to create (inside `connectors/alarm_api/`):**

```
connectors/alarm_api/
  app.py            # FastAPI app factory + router include
  store.py          # deterministic in-memory data
  seed.py           # seed data factory
  models.py         # Pydantic request / response schemas
  auth.py           # bearer-token dependency
  errors.py         # standard error envelope + exception → HTTP mapping
  routers/
    __init__.py
    health.py        # GET /health
    assets.py        # GET /assets/search, /assets/{id}/metadata
    alarms.py        # GET /alarms, /alarms/{id} + POST /alarms/{summary,trends,correlation,flood-analysis,rationalization-candidates,priority-score}
    recommendations.py
    calculations.py
    analytics.py
tests/integration/alarm_api/
  __init__.py
  test_endpoints.py  # all 15 endpoints, including auth and trace
tests/unit/alarm_api/
  __init__.py
  test_store.py      # deterministic-data invariants
```

**Files to modify:**

- `connectors/alarm_api/__main__.py` — replace the placeholder with the real FastAPI app entrypoint.
- `connectors/alarm_api/__init__.py` — re-export `app` and `store` for tests.
- `Makefile` — add `make run-alarm-api` target.
- `tests/unit/core/test_config.py` — no change, but the alarm_api_token is now actually used.

**`connectors/alarm_api/seed.py` — deterministic synthetic data**

```python
"""Generate a deterministic fixture of assets, alarms, and metadata.

A fixed seed produces the same data on every run so the Postman
chaining collection's asset_id / alarm_id / calculation_id variables
land on the same ids every time.
"""
from datetime import datetime, timezone, timedelta
from core.domain import Alarm, AlarmSummary, Asset, OperatorRecommendation, Severity


SEED_ASSETS: list[Asset] = [
    Asset(id="asset-bfp-101", name="Boiler Feed Pump 101", site="EastRefinery", unit="Unit 1", asset_class="pump"),
    Asset(id="asset-bfp-102", name="Boiler Feed Pump 102", site="EastRefinery", unit="Unit 1", asset_class="pump"),
    Asset(id="asset-comp-c1", name="Compressor C1", site="NorthPlant", unit="Unit 2", asset_class="compressor"),
    Asset(id="asset-motor-m1", name="Motor M1", site="SouthPlant", unit="Unit 5", asset_class="motor"),
    Asset(id="asset-bfp-201", name="Boiler Feed Pump 201", site="WestRefinery", unit="Unit 4", asset_class="pump"),
]
SEED_ALARMS: list[Alarm] = [
    Alarm(id="alarm-bfp-101-001", asset_id="asset-bfp-101", severity=Severity.CRITICAL, message="BFP high temp", raised_at=datetime(2026, 6, 15, 8, 0, tzinfo=timezone.utc), acknowledged=False),
    Alarm(id="alarm-bfp-101-002", asset_id="asset-bfp-101", severity=Severity.HIGH,     message="BFP low flow", raised_at=datetime(2026, 6, 15, 9, 0, tzinfo=timezone.utc), acknowledged=False),
    Alarm(id="alarm-bfp-101-003", asset_id="asset-bfp-101", severity=Severity.MEDIUM,   message="BFP vibration", raised_at=datetime(2026, 6, 16, 10, 0, tzinfo=timezone.utc), acknowledged=True),
    Alarm(id="alarm-comp-c1-001", asset_id="asset-comp-c1", severity=Severity.HIGH,   message="Compressor surge", raised_at=datetime(2026, 6, 17, 11, 0, tzinfo=timezone.utc), acknowledged=False),
    Alarm(id="alarm-comp-c1-002", asset_id="asset-comp-c1", severity=Severity.LOW,    message="Compressor minor leak", raised_at=datetime(2026, 6, 18, 12, 0, tzinfo=timezone.utc), acknowledged=True),
    Alarm(id="alarm-motor-m1-001", asset_id="asset-motor-m1", severity=Severity.MEDIUM,  message="Motor temp rising", raised_at=datetime(2026, 6, 19, 13, 0, tzinfo=timezone.utc), acknowledged=False),
    Alarm(id="alarm-bfp-201-001", asset_id="asset-bfp-201", severity=Severity.HIGH,   message="BFP vibration", raised_at=datetime(2026, 6, 20, 14, 0, tzinfo=timezone.utc), acknowledged=False),
    Alarm(id="alarm-bfp-201-002", asset_id="asset-bfp-201", severity=Severity.LOW,    message="BFP noise", raised_at=datetime(2026, 6, 21, 15, 0, tzinfo=timezone.utc), acknowledged=True),
]
```

(Same shape for the recommendations, calculations, and KPI defs.)

**`connectors/alarm_api/store.py`**

```python
"""Thread-safe in-memory store backed by the deterministic seed."""
from __future__ import annotations

from datetime import datetime
from typing import Iterable

from .seed import SEED_ALARMS, SEED_ASSETS, ...
from core.domain import Alarm, Asset


class AlarmStore:
    def __init__(self) -> None:
        self._assets: dict[str, Asset] = {a.id: a for a in SEED_ASSETS}
        self._alarms: dict[str, Alarm] = {a.id: a for a in SEED_ALARMS}
        # Calculations stored as a dict keyed by calculation_id
        self._calculations: dict[str, dict] = {}

    # --- assets ---
    def search_assets(self, query: str, limit: int = 10) -> list[Asset]:
        q = query.lower()
        matches = [a for a in self._assets.values() if q in a.name.lower() or q in a.site.lower()]
        return matches[:limit]

    def get_asset(self, asset_id: str) -> Asset | None:
        return self._assets.get(asset_id)

    # --- alarms ---
    def list_alarms(self, asset_id: str | None = None, unit: str | None = None, site: str | None = None,
                    status: str | None = None, severity: Severity | None = None,
                    start: datetime | None = None, end: datetime | None = None,
                    page: int = 1, page_size: int = 50, sort_by: str = "raised_at",
                    sort_order: str = "desc") -> tuple[list[Alarm], int]:
        # filter, sort, paginate; return (rows, total)
        ...

    def get_alarm(self, alarm_id: str) -> Alarm | None:
        return self._alarms.get(alarm_id)
```

**`connectors/alarm_api/auth.py`**

```python
"""Bearer-token dependency: 401 if missing/invalid, otherwise no-op."""
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from core.config import get_settings


_bearer = HTTPBearer(auto_error=False)


def require_bearer(creds: HTTPAuthorizationCredentials | None = Depends(_bearer)) -> None:
    expected = get_settings().alarm_api_token.get_secret_value()
    if creds is None or creds.scheme.lower() != "bearer" or creds.credentials != expected:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail={"code": "unauthorized", "message": "Missing or invalid bearer token"})
```

**`connectors/alarm_api/errors.py`**

```python
"""Standard error envelope and exception → HTTP mapping."""
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from core.logging import get_logger
from core.utils import new_id


class AlarmAPIError(Exception):
    def __init__(self, code: str, message: str, status_code: int = 500, details: dict | None = None) -> None:
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details or {}


def envelope(code: str, message: str, request: Request, details: dict | None = None) -> dict:
    trace_id = request.headers.get("trace_id") or new_id()
    return {"code": code, "message": message, "trace_id": trace_id, "details": details or {}}


def install_handlers(app: FastAPI) -> None:
    log = get_logger(__name__)

    @app.exception_handler(AlarmAPIError)
    async def _api_error(_: Request, exc: AlarmAPIError) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content={"code": exc.code, "message": exc.message, "trace_id": ..., "details": exc.details})

    @app.exception_handler(404)
    async def _not_found(request: Request, _exc) -> JSONResponse:
        return JSONResponse(status_code=404, content=envelope("not_found", "Resource not found", request))
```

**`connectors/alarm_api/routers/alarms.py`** (representative)

```python
"""Alarm list, by-id, summary, trends, correlation, flood, rationalization, priority-score."""
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, Query

from core.domain import Severity
from core.logging import bind_context
from .auth import require_bearer
from .store import AlarmStore
from .models import AlarmListResponse, AlarmOut, ...

router = APIRouter(prefix="/alarms", tags=["alarms"], dependencies=[Depends(require_bearer)])


@router.get("", response_model=AlarmListResponse)
def list_alarms(asset_id: str | None = None, ...,
                page: int = Query(1, ge=1), page_size: int = Query(50, ge=1, le=500),
                sort_by: str = "raised_at", sort_order: str = "desc") -> AlarmListResponse:
    store: AlarmStore = ...  # injected via app state
    rows, total = store.list_alarms(...)
    return AlarmListResponse(data=rows, page=page, page_size=page_size, total=total)
```

(Similar routers for the other resource groups.)

**`connectors/alarm_api/app.py`**

```python
"""FastAPI app factory."""
from fastapi import FastAPI

from core.config import get_settings
from core.logging import bind_context, configure_logging
from core.utils import TraceContext

from .errors import AlarmAPIError, install_handlers
from .routers import alarms, assets, analytics, calculations, health, recommendations
from .store import AlarmStore


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level)
    bind_context(mcp_server="alarm-api")  # renamed later; just tracks origin in logs

    app = FastAPI(title="Alarm Management API", version="0.1.0")
    app.state.store = AlarmStore()
    install_handlers(app)

    app.include_router(health.router)
    app.include_router(assets.router)
    app.include_router(alarms.router)
    app.include_router(recommendations.router)
    app.include_router(calculations.router)
    app.include_router(analytics.router)
    return app
```

**`connectors/alarm_api/__main__.py`** (replace placeholder)

```python
"""Entry point: run the alarm-api simulator via uvicorn."""
import uvicorn

from core.config import get_settings
from core.logging import configure_logging, get_logger

from .app import create_app


settings = get_settings()
configure_logging(settings.log_level)
log = get_logger(__name__)

app = create_app()


if __name__ == "__main__":
    log.info("starting", component="alarm-api", port=settings.alarm_api_port)
    uvicorn.run(app, host="0.0.0.0", port=8000)  # container port
```

**`Makefile`** — add target

```makefile
run-alarm-api:
	@ALARM_API_TOKEN=$${ALARM_API_TOKEN:-demo-token} uv run python -m connectors.alarm_api
```

**Tests (`tests/integration/alarm_api/test_endpoints.py`):**

```python
"""Test all 15 endpoints + auth + trace + error envelope using FastAPI TestClient."""
import pytest
from fastapi.testclient import TestClient
from connectors.alarm_api.app import create_app
from connectors.alarm_api.auth import ...


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("ALARM_API_TOKEN", "test-token")
    from core.config import get_settings
    get_settings.cache_clear()
    return TestClient(create_app())


def test_health_no_auth(client: TestClient) -> None:
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_search_assets_requires_auth(client: TestClient) -> None:
    assert client.get("/assets/search?query=Boiler").status_code == 401


def test_search_assets_with_token(client: TestClient) -> None:
    r = client.get("/assets/search?query=Boiler", headers={"Authorization": "Bearer test-token"})
    assert r.status_code == 200
    assert len(r.json()["results"]) > 0
    assert r.json()["results"][0]["asset_id"] == "asset-bfp-101"


def test_get_alarm_trace_echoed(client: TestClient) -> None:
    r = client.get("/alarms/alarm-bfp-101-001",
                   headers={"Authorization": "Bearer test-token", "trace_id": "trace-xyz"})
    assert r.status_code == 200
    assert r.headers.get("trace_id") == "trace-xyz"


def test_alarm_summary_uses_seed_data(client: TestClient) -> None:
    r = client.post("/alarms/summary",
                    json={"asset_ids": ["asset-bfp-101"], "time_range": {"start_time": "2026-05-01T00:00:00Z", "end_time": "2026-07-01T00:00:00Z"}, "kpis": ["alarm_count"]},
                    headers={"Authorization": "Bearer test-token"})
    assert r.status_code == 200
    body = r.json()
    assert "groups" in body and "kpis" in body


def test_priority_score_alarm_unknown(client: TestClient) -> None:
    r = client.post("/alarms/priority-score", json={"alarm_id": "alarm-doesnt-exist"},
                    headers={"Authorization": "Bearer test-token"})
    assert r.status_code == 404
    body = r.json()
    assert body["code"] == "not_found"
    assert "trace_id" in body
```

(Similar tests for every endpoint — ~15-20 tests total.)

**Tests (`tests/unit/alarm_api/test_store.py`):**

- `search_assets` returns deterministic results for the same query.
- `list_alarms` filters by asset_id, unit, site, status, severity, time range.
- `list_alarms` sorts by raised_at asc/desc.
- `list_alarms` paginates correctly.
- Calculation generate → execute roundtrip returns the stored result.

### Story 2.1.2 — Authentication, trace propagation, error handling

Already mostly covered by Story 2.1.1's design (`require_bearer`, `envelope`, trace-id echo). Story 2.1.2 adds the tests + one additional layer:

**Files to add:**

- `tests/integration/alarm_api/test_auth.py` — auth-specific tests (auth required on every endpoint except /health, wrong-token returns 401, missing-header returns 401, response uses envelope).
- `tests/integration/alarm_api/test_tracing.py` — trace header round-trips on POST endpoints that expect them.

**Test cases (Story 2.1.2):**

- `/health` requires no auth → 200.
- Every other endpoint without `Authorization: Bearer <token>` → 401.
- Wrong token → 401.
- Correct token → 200; response includes `trace_id` if request had one.
- Invalid alarm_id → 404 with `{code: "not_found", message, trace_id, details: {alarm_id}}`.
- Invalid body (e.g., missing required field) → 422 with the same envelope.

### Cross-cutting

- **`Makefile` lint target** — `uv run python -c "from connectors.alarm_api.app import create_app; create_app()"` as a smoke import. (Catches dependency-cycle or import-time errors.)

## 6. File manifest (full)

```
modified  connectors/alarm_api/__init__.py
modified  connectors/alarm_api/__main__.py
created   connectors/alarm_api/app.py
created   connectors/alarm_api/auth.py
created   connectors/alarm_api/errors.py
created   connectors/alarm_api/models.py
created   connectors/alarm_api/seed.py
created   connectors/alarm_api/store.py
created   connectors/alarm_api/routers/__init__.py
created   connectors/alarm_api/routers/health.py
created   connectors/alarm_api/routers/assets.py
created   connectors/alarm_api/routers/alarms.py
created   connectors/alarm_api/routers/recommendations.py
created   connectors/alarm_api/routers/calculations.py
created   connectors/alarm_api/routers/analytics.py
created   tests/integration/alarm_api/__init__.py
created   tests/integration/alarm_api/test_endpoints.py
created   tests/integration/alarm_api/test_auth.py
created   tests/integration/alarm_api/test_tracing.py
created   tests/unit/alarm_api/__init__.py
created   tests/unit/alarm_api/test_store.py
modified  Makefile
modified  pyproject.toml        # add pytest config if needed; mypy include tests
```

## 7. Order of operations

1. **Story 2.1.1 (commit 1):** `feat(alarm-api): implement all 15 endpoints from Postman collection`. `connectors/alarm_api/{app,auth,errors,models,seed,store}.py` + `routers/*` + `__main__.py` updated + `tests/integration/alarm_api/test_endpoints.py` + `tests/unit/alarm_api/test_store.py` + `Makefile` smoke. `uv lock` if any new dep added.
2. **Story 2.1.2 (commit 2):** `feat(alarm-api): enforce auth and trace propagation` — adds `tests/integration/alarm_api/test_auth.py` and `test_tracing.py`. Verifies the existing implementation, no source changes.
3. **Local smoke (manual, before push):** `cp .env.example .env && sed -i 's/^ALARM_API_TOKEN=.*/ALARM_API_TOKEN=demo-token/' .env && docker compose up --build -d && sleep 12 && for u in "8000 alarm-api" "9000 mcp-server" "5173 frontend"; do port=${u% *}; n=${u#* }; resp=$(curl -sf -o /dev/null -w "%{http_code}" "http://localhost:$port/health"); echo "$n ($port): $resp"; done && docker compose down -v && rm .env`. Also: run the Postman base collection via Newman (if available) — otherwise rely on the integration test suite.
4. Open PR → `developer`. Closes #13, #34, #35.

## 8. Verification

```bash
# Local
uv lock
uv sync
uv run ruff check .
uv run mypy apps rag connectors core connectors

# Story 2.1.1 + 2.1.2 tests
uv run pytest -ra tests/integration/alarm_api/
uv run pytest -ra tests/unit/alarm_api/
uv run pytest -ra  # full suite — earlier 37 tests must still pass

# Make target
make run-alarm-api  # in a separate terminal; Ctrl-C to stop
# In another terminal with .env configured:
curl -s -H "Authorization: Bearer demo-token" http://localhost:8000/assets/search?query=Boiler | head -c 200

# Docker smoke
cp .env.example .env && sed -i 's/^ALARM_API_TOKEN=.*/ALARM_API_TOKEN=demo-token/' .env
docker compose up --build -d
sleep 12
curl -s -H "Authorization: Bearer demo-token" http://localhost:8000/alarms/alarm-bfp-101-001 | head -c 200
curl -s -o /dev/null -w "%{http_code}\n" http://localhost:8000/health
docker compose down -v
rm .env

# Postman chaining (if Newman installed)
newman run postman/Alarm-API-Simulator.postman_collection.json --delay-request 50
newman run postman/chaining/Alarm-API-Chaining.postman_collection.json --delay-request 50
```

Expected:
- All unit + integration tests pass.
- `curl /health` returns 200 without auth.
- `curl /alarms/alarm-bfp-101-001` with bearer returns 200 + a valid JSON Alarm.
- `curl /alarms/alarm-bfp-101-001` without bearer returns 401.
- Newman runs the base collection (14 requests) and the chaining (10 flows) all green.

## 9. Out of scope

- Real industrial data (the simulator stands in).
- Authentication beyond the bearer token (no OAuth, SSO, key rotation).
- Persistent storage — the in-memory store resets on every restart. Acceptable for a simulator; the brief doesn't ask for it.
- Story 2.1.2's optional `make validate-api` is still a stub — Newman becomes the real validation step in Story 2.2.1.

## 10. Risks & decisions

- **Response shape for `POST` endpoints** — the Postman collection has chaining scripts that read specific fields (`body.results[0].asset_id`, `body.data[0].alarm_id`, `body.calculation_id`, `body.flood_windows`, etc.). The plan above pins those field names; the actual structure around them (`{groups: [...], kpis: {...}}` vs flat) is up to the implementation as long as the Postman test scripts find their fields.
- **`unit` and `site` filters on `/alarms`** — the chaining collection uses `?unit=` and `?site=` query params in some flows. The current root collection uses `?asset_id=`. Plan covers both via query parameters.
- **Calculation execution result** — the chaining flow's only test is `pm.response.to.have.status(200)`. We can return any JSON object as the result. Plan returns `{"calculation_id": ..., "result": {...}}` with a deterministic stub.
- **Mypy on `connectors/alarm_api/`** — first time we add non-`__main__` code in this package. May need additional `mypy_path` or per-module overrides if Pydantic generic resolution gets noisy. Plan assumes clean type-check; will adjust if not.
- **Test client state isolation** — `get_settings` is `lru_cache`d. Tests must call `get_settings.cache_clear()` after `monkeypatch.setenv("ALARM_API_TOKEN", ...)` so the new token takes effect. Covered in the fixture.

---

**Awaiting your sign-off.** Reply "approved" to start, or send edits.