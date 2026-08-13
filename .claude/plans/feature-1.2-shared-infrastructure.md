# Feature 1.2 — Shared Infrastructure — Implementation Plan

> Feature: **#12** `[Feature 1.2]: Shared Infrastructure`
> Parent Epic: **#2** `[Epic 1]: Foundation & Infrastructure`
> Branch: `feature/feature-1.2-shared-infrastructure`
> Plan author: Claude
> Status: **DRAFT — awaiting user approval before any code changes**

---

## 0. Pre-work: Dockerfile MODULE_PATH regression

Before the 1.2 stories run, fix a regression from PR #73. Commit `ced2af2` ("fix: docker compose runtime -- missing service modules and port default") *claimed* a Dockerfile change in its message, but the actual diff did not include the Dockerfile. The repo currently has the older `SERVICE_NAME//-/_}` form, which still works because each service happens to use a hyphen-only service name that maps to a single underscore-separated module name. It's fragile though: the moment we add a service whose SERVICE_NAME doesn't map cleanly to its module path, the image breaks again. (See PR #73's runtime fix in commit `ced2af2` and the dev log "failed to parse stage name `python:-slim`" earlier.)

**Fix in this branch:** switch the Dockerfile from `SERVICE_NAME` to `MODULE_PATH` (dotted Python module path), the same change that was already applied to `docker-compose.yml`. The new value is per-service; the default keeps the existing copilot-backend behaviour.

```dockerfile
# Was
ARG SERVICE_NAME=app
ENV SERVICE_NAME=${SERVICE_NAME}
RUN uv pip install --no-deps .
# ...
CMD ["sh", "-c", "exec uv run python -m ${SERVICE_NAME//-/_}.__main__"]

# Becomes
ARG MODULE_PATH=apps.backend
ENV MODULE_PATH=${MODULE_PATH}
RUN uv pip install --no-deps .
# ...
CMD ["sh", "-c", "exec uv run python -m ${MODULE_PATH}.__main__"]
```

This is a one-line change in spirit. The Dockerfile's `MODULE_PATH` default matches the `apps.backend` default in `docker-compose.yml`; nothing else changes.

---

## 1. Goal

Land a `core/` package that every later Epic imports without divergence. After this feature merges:

- The backend, MCP server, RAG pipeline, and GUI all read configuration from one `core.config.Settings`.
- Logs are JSON-structured, with the observability fields from `Submission_and_Evaluation_Guidelines.md` § 16, and a context-binding helper that propagates them per request.
- Domain models (Asset, Alarm, AlarmSummary, OperatorRecommendation, Incident, TicketDraft, Citation, TraceStep) are defined once and round-trip through JSON.
- No `os.getenv` calls outside `core.config.Settings`. No duplicated type definitions across packages.

## 2. Acceptance criteria (mirrors GitHub Feature #12)

- [ ] Both stories (1.2.1, 1.2.2) are complete with their own AC met.
- [ ] All packages read config from the shared loader (no scattered `os.getenv` calls).
- [ ] Structured logs include the observability fields listed in § 16.
- [ ] Domain models cover Alarm, Asset, Incident, TicketDraft at minimum.
- [ ] **Bonus:** no `os.getenv` outside `core.config.Settings` — enforced by a repo-wide grep in CI (lightweight `grep` step in `.github/workflows/ci.yml`).

## 3. Hard constraints from `CLAUDE.md` that apply

- **#5** No secrets in code or commits. `core.config.Settings` must use `SecretStr` for any sensitive field; logger redaction helper for safety.
- **#6** Layer separation: `core/` is the auth + configuration + observability + domain-models layer; the orchestrator, MCP server, and RAG all depend on it, never the reverse.
- **#16** (Submission Guidelines) — observability fields must be present in every structured log line.

## 4. Stories → ordered implementation steps

### Story 1.2.1 — Implement configuration and logging framework

**Files to create:**

```
core/
  __init__.py
  config.py        # Settings (Pydantic v2 BaseSettings)
  logging.py       # get_logger(), bind_context(), JSON formatter
  exceptions.py    # base exception hierarchy
  utils.py         # now(), new_id(), TraceContext
tests/
  unit/
    core/
      __init__.py
      test_config.py
      test_logging.py
      test_exceptions.py
      test_utils.py
```

**`core/config.py`** — a single `Settings` class using `pydantic-settings.BaseSettings`:

```python
"""Centralised, env-driven configuration.

No code outside this module should call os.getenv. Every other package
imports get_settings() and reads typed fields.
"""
from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- Alarm API (Epic 2 + 3) ---
    alarm_api_base_url: str = "http://localhost:8000"
    alarm_api_token: SecretStr = SecretStr("replace-me")
    alarm_api_port: int = 8000

    # --- MCP server (Epic 3) ---
    mcp_server_url: str = "http://localhost:9000"
    mcp_server_port: int = 9000

    # --- LLM (Epic 5) ---
    llm_provider: Literal["openai", "anthropic", "mock"] = "mock"
    llm_api_key: SecretStr = SecretStr("replace-me")

    # --- Vector store (Epic 4) ---
    vector_store_url: str = "http://localhost:8002"
    vector_store_port: int = 8002
    document_path: str = "./rag/documents"

    # --- Ticketing (Epic 6) ---
    ticketing_api_url: str = "http://localhost:8003"
    ticketing_api_port: int = 8003

    # --- App ---
    backend_port: int = 8000
    frontend_port: int = 5173
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Singleton accessor. Tests can call get_settings.cache_clear()."""
    return Settings()
```

**`core/logging.py`** — structlog (already a transitive dep via pydantic-settings in some configurations, but we'll add it explicitly) with the 13 observability fields:

```python
"""Structured JSON logging with per-request context binding."""
from __future__ import annotations

import logging
import sys
from contextvars import ContextVar
from typing import Any

import structlog

# Observability fields from Submission § 16. Bound via structlog's
# contextvars so a single log call carries them all without manual
# plumbing.
_LOG_CONTEXT: ContextVar[dict[str, Any]] = ContextVar("log_context", default={})


def bind_context(**kwargs: Any) -> None:
    """Bind values that every subsequent log line in this context carries."""
    _LOG_CONTEXT.set({**_LOG_CONTEXT.get(), **kwargs})


def clear_context() -> None:
    _LOG_CONTEXT.set({})


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    if name is None:
        name = __name__
    return structlog.get_logger(name)


def _add_context(_, __, event_dict: dict[str, Any]) -> dict[str, Any]:
    for k, v in _LOG_CONTEXT.get().items():
        event_dict.setdefault(k, v)
    return event_dict


def configure_logging(level: str = "INFO") -> None:
    """Wire stdlib logging + structlog. Call once at app startup."""
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=getattr(logging, level),
    )
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            _add_context,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(getattr(logging, level)),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )
```

**`core/exceptions.py`** — base hierarchy:

```python
"""Project-wide exception hierarchy."""


class CopilotError(Exception):
    """Base for every exception this project raises."""


class ConfigError(CopilotError):
    """Configuration invalid or missing."""


class AlarmAPIError(CopilotError):
    """Alarm Management API returned an error or was unreachable."""


class MCPError(CopilotError):
    """MCP server returned an error or was unreachable."""


class RAGError(CopilotError):
    """Retrieval failed (low confidence, broken index, etc.)."""


class TicketApprovalRequired(CopilotError):
    """Write operation attempted without explicit user approval."""


class TicketError(CopilotError):
    """Ticket service returned an error or was unreachable."""
```

**`core/utils.py`** — time, ids, trace context:

```python
"""Small helpers used everywhere."""
from __future__ import annotations

import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone

from .logging import bind_context, clear_context


def now() -> datetime:
    return datetime.now(timezone.utc)


def new_id() -> str:
    return str(uuid.uuid4())


@dataclass
class TraceContext:
    request_id: str = field(default_factory=new_id)
    conversation_id: str | None = None
    trace_id: str | None = None
    extras: dict[str, str] = field(default_factory=dict)

    def bind(self) -> None:
        bind_context(
            request_id=self.request_id,
            conversation_id=self.conversation_id,
            trace_id=self.trace_id,
            **self.extras,
        )


@contextmanager
def trace_scope(ctx: TraceContext):
    ctx.bind()
    try:
        yield ctx
    finally:
        clear_context()
```

**Tests:**

- `tests/unit/core/test_config.py` — instantiation with no env file (defaults), with partial env (overrides), with a `SecretStr` (no plaintext leak in repr).
- `tests/unit/core/test_logging.py` — `configure_logging` then `get_logger().info(...)` produces JSON containing the § 16 fields when `bind_context` is active; `bind_context` and `clear_context` round-trip; **no secret value ever appears in a log line** (assert secret value isn't in any captured log).
- `tests/unit/core/test_exceptions.py` — every concrete exception is a `CopilotError` and a normal `Exception`.
- `tests/unit/core/test_utils.py` — `now()` is timezone-aware, `new_id()` is unique, `trace_scope` binds and clears.

### Story 1.2.2 — Configure shared domain models and utilities

**File:** `core/domain.py` (one file; split later if it grows).

```python
"""Shared Pydantic domain models. Imported by every other package."""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class Severity(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class Asset(BaseModel):
    model_config = ConfigDict(frozen=True)
    id: str
    name: str
    site: str
    asset_class: str | None = None
    metadata: dict[str, str] = Field(default_factory=dict)


class Alarm(BaseModel):
    model_config = ConfigDict(frozen=True)
    id: str
    asset_id: str
    severity: Severity
    message: str
    raised_at: datetime
    acknowledged: bool = False


class AlarmSummary(BaseModel):
    site: str | None = None
    asset_id: str | None = None
    severity: Severity | None = None
    since: datetime | None = None
    until: datetime | None = None
    items: list[Alarm] = Field(default_factory=list)
    total: int = 0


class OperatorRecommendation(BaseModel):
    alarm_id: str
    priority_score: int = Field(ge=0, le=100)
    actions: list[str] = Field(default_factory=list)
    rationale: str | None = None


class Citation(BaseModel):
    doc_id: str
    section: str | None = None
    page: int | None = None
    score: float | None = None
    excerpt: str | None = None


class Incident(BaseModel):
    id: str
    title: str
    summary: str
    severity: Severity
    likely_cause: str | None = None
    recommended_actions: list[str] = Field(default_factory=list)
    citations: list[Citation] = Field(default_factory=list)
    similar_tickets: list[str] = Field(default_factory=list)
    created_at: datetime


class TicketDraft(BaseModel):
    title: str
    body: str
    severity: Severity
    incident_id: str | None = None
    assignee: str | None = None
    labels: list[str] = Field(default_factory=list)


class TraceStep(BaseModel):
    """One row of the MCP execution trace surfaced in every response."""
    server: str
    tool: str
    args: dict[str, object] = Field(default_factory=dict)
    output: object | None = None
    duration_ms: int
    outcome: Literal["success", "error", "timeout"] = "success"
    error: str | None = None
    retry_count: int = 0
    api_status_code: int | None = None
```

`utils.py` already covers `now()` / `new_id()` / `TraceContext` from Story 1.2.1; Story 1.2.2 adds `TraceStep` which is technically a model rather than a util.

**Tests:**

- `tests/unit/core/test_domain.py` — every model round-trips through `model_dump_json()` / `__init__` (parse round-trip). Frozen models reject mutation. Severity enum values are the expected strings. Citation.score is optional.

### Cross-cutting: `pyproject.toml` and CI

- `pyproject.toml` `[project].dependencies` — add `pydantic-settings>=2.5` (already there from Feature 1.1) and `structlog>=24.4`.
- `pyproject.toml` `[tool.setuptools].packages` — add `core`.
- `.github/workflows/ci.yml` — add a lightweight `grep` step that fails if any `os.getenv` appears outside `core/`:

  ```yaml
        - name: Disallow os.getenv outside core/
          run: |
            if grep -rn 'os\.getenv' apps/ mcp-servers/ rag/ connectors/ tests/ 2>/dev/null; then
              echo "os.getenv is only allowed inside core/config.py" >&2
              exit 1
            fi
  ```

- `Makefile` `lint` — append `uv run python -c "from core.config import get_settings; get_settings()"` as a smoke check (catches import errors and missing required env at lint time without forcing a real env file).
- `Dockerfile` CMD — no change from pre-work; `MODULE_PATH` is already the right pattern.
- `docker-compose.yml` — no change.

## 5. File manifest (full)

```
modified  pyproject.toml                                  # add core to packages, structlog dep
modified  Makefile                                        # extend lint smoke check
modified  .github/workflows/ci.yml                        # grep guard + minor
modified  Dockerfile                                     # MODULE_PATH fix (pre-work)
modified  apps/backend/__main__.py                       # use get_settings() + configure_logging
modified  apps/frontend/__main__.py                      # use get_settings() + configure_logging
modified  apps/backend/__init__.py                       # docstring update
modified  apps/frontend/__init__.py                      # docstring update
modified  mcp-servers/alarm-management/__main__.py      # use get_settings() + configure_logging
modified  mcp-servers/alarm-management/__init__.py      # docstring update
modified  connectors/__main__.py                         # use get_settings() + configure_logging
modified  connectors/alarm_api/__main__.py               # use get_settings() + configure_logging
created   core/__init__.py
created   core/config.py
created   core/logging.py
created   core/exceptions.py
created   core/utils.py
created   core/domain.py
created   tests/unit/core/__init__.py
created   tests/unit/core/test_config.py
created   tests/unit/core/test_logging.py
created   tests/unit/core/test_exceptions.py
created   tests/unit/core/test_utils.py
created   tests/unit/core/test_domain.py
```

The placeholder `__main__.py` files in 5 services (apps/backend, apps/frontend, mcp-servers/alarm-management, connectors, connectors/alarm_api) get a one-liner upgrade so the docker compose healthcheck actually exercises the new logging:

```python
from core.config import get_settings
from core.logging import configure_logging

configure_logging(get_settings().log_level)
```

This is a smoke test for Story 1.2.1 inside the running stack.

## 6. Order of operations

1. **Pre-work (commit 1):** `fix(dockerfile): use MODULE_PATH arg, drop SERVICE_NAME//-/_ hack`. One commit, single line in Dockerfile plus a comment. Push.
2. **Story 1.2.1 (commit 2):** `feat(core): add configuration and logging framework` — `core/__init__.py`, `config.py`, `logging.py`, `exceptions.py`, `utils.py`; `tests/unit/core/test_*.py`; `pyproject.toml` deps + packages. `uv lock` to refresh.
3. **Story 1.2.2 (commit 3):** `feat(core): add shared domain models` — `core/domain.py` + tests.
4. **Cross-cutting (commit 4):** `chore(ci): disallow os.getenv outside core + smoke check in Makefile`. CI grep step + Makefile lint addition.
5. **Placeholder upgrade (commit 5):** `chore: smoke-test core in placeholder services` — five `__main__.py` files import `core.config` / `core.logging` and call `configure_logging`. Verifies the wiring on `docker compose up`.
6. Open PR → `developer`.

## 7. Verification (run after each commit; full pass before PR)

```bash
# Local
uv lock && uv sync
uv run ruff check .
uv run mypy apps rag connectors core

# Story 1.2.1
uv run pytest -ra tests/unit/core/test_config.py
uv run pytest -ra tests/unit/core/test_logging.py
uv run pytest -ra tests/unit/core/test_exceptions.py
uv run pytest -ra tests/unit/core/test_utils.py
uv run pytest -ra                                # full suite

# Story 1.2.2
uv run pytest -ra tests/unit/core/test_domain.py
uv run python -c "from core.domain import Incident, Citation, TraceStep; Incident.model_validate({'id':'i1','title':'t','summary':'s','severity':'high','created_at':'2026-08-07T10:00:00Z'})"

# CI guard
! grep -rn 'os\.getenv' apps/ mcp-servers/ rag/ connectors/ tests/  # should return 1 (no match)

# Docker smoke test
cp .env.example .env
docker compose up --build -d
sleep 8
docker compose logs --tail=20 copilot-backend | head -20   # JSON log line visible
docker compose ps                                              # all healthy
docker compose down -v
rm .env

# MyPy exclusions — mcp-servers/ stays excluded (hyphenated dir),
# apps/frontend, apps/backend, connectors, connectors/alarm_api are
# all in-scope since their packages are dotted.
```

## 8. Out of scope

- LLM, MCP, or DB-specific clients (Epic 4 / 5 / 6).
- Production observability (Prometheus exporter etc.) — that lives in Epic 9.
- Per-service log levels / sinks — single global level for now.

## 9. Risks & decisions

- **`core/` is a deviation from the prescribed layout** (`Submission_and_Evaluation_Guidelines.md` § 3 doesn't list it). Justified by the 12-layer architecture in § 6 (auth + configuration + observability + domain models are explicit layers). Will be called out in `docs/design-decisions.md` when Epic 9 lands.
- **structlog vs stdlib `logging`?** Going with structlog — its contextvars-based context binding fits the § 16 observability fields cleanly, and it renders to JSON out of the box. stdlib `logging` is left in place as the underlying engine (structlog's `make_filtering_bound_logger`).
- **Domain model file count.** Bundling all 8 models in `core/domain.py` for now. If the file grows past ~300 lines, split per model. At Story 1.2.2's scope it should be ~150.
- **Frozen models.** `Asset` and `Alarm` are frozen because they're emitted from the alarm API and shouldn't be mutated downstream. Other models are mutable for now; we can freeze `Incident` once the orchestrator is built (Epic 5).

---

**Awaiting your sign-off.** Reply "approved" to start, or send edits.