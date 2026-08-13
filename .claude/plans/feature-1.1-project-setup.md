# Feature 1.1 — Project Setup — Implementation Plan

> Feature: **#11** `[Feature 1.1]: Project Setup`
> Parent Epic: **#2** `[Epic 1]: Foundation & Infrastructure`
> Branch: `feature/feature-1.1-project-setup`
> Plan author: Claude
> Status: **DRAFT — awaiting user approval before any code changes**

---

## 1. Goal

Land a greenfield repository that any reviewer can clone and immediately start with `docker compose up --build`. After this feature merges, every later Epic (Alarm API, MCP, RAG, Copilot, GUI, Tests, Docs) can drop its code into the right directory without fighting the build.

## 2. Acceptance criteria (mirrors GitHub Feature #11)

- [ ] All three stories (1.1.1, 1.1.2, 1.1.3) are complete with their own AC met.
- [ ] `docker compose up --build` succeeds from a clean clone.
- [ ] `.env.example` lists all eight required placeholders: `ALARM_API_BASE_URL`, `ALARM_API_TOKEN`, `MCP_SERVER_URL`, `LLM_PROVIDER`, `LLM_API_KEY`, `VECTOR_STORE_URL`, `DOCUMENT_PATH`, `TICKETING_API_URL`.
- [ ] No secrets are committed.
- [ ] `pyproject.toml` declares Python ≥ 3.13 and project name `incident-and-ticket-enrichment-copilot`.
- [ ] `Makefile` exposes at minimum `build`, `test`, `lint`, `up`, `down`.

## 3. Hard constraints from `CLAUDE.md` that apply

- **#5 — No secrets in code or commits.** `.env.example` ships placeholders only; `.gitignore` excludes `.env`.
- **#7 — `docker compose up --build` from a clean environment.** The default `make up` (or `docker compose up`) must succeed on a fresh clone with no manual steps besides `cp .env.example .env`.
- Conventional-commit prefixes will be used once commits happen (`chore:` for this scaffolding).

## 4. Stories → ordered implementation steps

### Story 1.1.1 — Initialize repository and project structure

Create the directory tree mandated by `Submission_and_Evaluation_Guidelines.md` § 3 and extend `.gitignore`. Existing files (`README.md`, `ASSIGNMENT_BRIEF.md`, `Assignment_Use_Case.md`, `Submission_and_Evaluation_Guidelines.md`, `docs/`, `.claude/`, `postman/`) must be preserved.

**Files / dirs to create:**

```
apps/
  backend/        __init__.py  +  __main__.py (placeholder health server)
  frontend/       __init__.py  +  README.md     (placeholder — actual GUI is Epic 7)
mcp-servers/
  alarm-management/         __init__.py +  __main__.py (placeholder)
  optional-secondary-server/__init__.py +  README.md
rag/
  ingestion/      __init__.py
  retrieval/      __init__.py
  documents/      .gitkeep        (empty corpus lands later)
  tests/          __init__.py
connectors/
  __init__.py
tests/
  unit/           __init__.py
  integration/    __init__.py
  e2e/            __init__.py
test-data/        .gitkeep
scripts/          .gitkeep
.github/
  workflows/      ci.yml          (minimal scaffold — authored in Story 1.1.3)
```

**Extend `.gitignore`** (currently has Python + .venv + .claude). Add:

```gitignore
# Test + lint caches
.pytest_cache/
.mypy_cache/
.ruff_cache/
.coverage
htmlcov/
coverage.xml

# OS / IDE
.DS_Store
Thumbs.db
.idea/
.vscode/
*.swp

# Secrets / local env
.env
.env.*
!.env.example
```

### Story 1.1.2 — Configure Python environment and dependencies

Rewrite `pyproject.toml` so it's actually usable (right now `dependencies = []`).

**`pyproject.toml` content:**

```toml
[project]
name = "incident-and-ticket-enrichment-copilot"
version = "0.1.0"
description = "AI copilot that enriches industrial incidents via MCP + RAG."
readme = "README.md"
requires-python = ">=3.13"
license = { text = "MIT" }
authors = [{ name = "Sumit Das" }]
dependencies = [
    "fastapi>=0.115",
    "uvicorn[standard]>=0.30",
    "pydantic-settings>=2.5",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "pytest-cov>=5.0",
    "ruff>=0.6",
    "mypy>=1.10",
]

[build-system]
requires = ["setuptools>=68", "wheel"]
build-backend = "setuptools.build_meta"

[tool.setuptools]
packages = [
    "apps",
    "apps.backend",
    "apps.frontend",
    "mcp_servers",
    "mcp_servers.alarm_management",
    "mcp_servers.optional_secondary_server",
    "rag",
    "rag.ingestion",
    "rag.retrieval",
    "rag.tests",
    "connectors",
]

[tool.setuptools.package-dir]
"mcp_servers" = "mcp-servers"
"mcp_servers.alarm_management" = "mcp-servers/alarm-management"
"mcp_servers.optional_secondary_server" = "mcp-servers/optional-secondary-server"

[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "-ra --strict-markers --strict-config"
pythonpath = ["."]
markers = [
    "integration: requires running docker-compose stack",
    "e2e: full end-to-end scenario, slow",
]

[tool.ruff]
line-length = 100
target-version = "py313"

[tool.ruff.lint]
select = ["E", "F", "W", "I", "B", "UP", "N"]
ignore = ["E501"]

[tool.mypy]
python_version = "3.13"
strict = false
ignore_missing_imports = true
```

**Why these three runtime deps:** each placeholder `__main__.py` needs a real web framework so Docker healthchecks can hit `/health`. Adding them now avoids revisiting `pyproject.toml` in every later Epic that ships an HTTP service.

**`apps/backend/__main__.py`** (placeholder):

```python
"""Placeholder backend; real implementation lands in Epic 5."""
import os

from fastapi import FastAPI

app = FastAPI(title="copilot-backend (placeholder)")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "copilot-backend"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", "8000")))
```

`mcp-servers/alarm-management/__main__.py` is identical in shape with `title="alarm-management MCP server (placeholder)"` and `service: "alarm-management-mcp"`.

### Story 1.1.3 — Configure Docker Compose and environment variables

Single parameterized `Dockerfile` at the repo root that all services share; `docker-compose.yml` declares six stub services; `.env.example` ships the eight required placeholders; `Makefile` exposes the five required targets plus helper ones; `.github/workflows/ci.yml` is the minimal CI scaffold.

**`Dockerfile`** (single file, parameterized by `SERVICE_NAME` build arg):

```dockerfile
# syntax=docker/dockerfile:1.7
ARG PYTHON_VERSION=3.13

FROM python:${PYTHON_VERSION}-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*
COPY pyproject.toml ./
ARG SERVICE_NAME=app
ENV SERVICE_NAME=${SERVICE_NAME}
COPY apps/ ./apps/
COPY mcp-servers/ ./mcp-servers/
COPY rag/ ./rag/
COPY connectors/ ./connectors/
RUN pip install --no-cache-dir ".[dev]"
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=3s --start-period=10s --retries=3 \
    CMD curl --fail http://localhost:${PORT:-8000}/health || exit 1
CMD ["sh", "-c", "exec python -m ${SERVICE_NAME//-/_}.__main__"]
```

**`docker-compose.yml`** — six services, each with a healthcheck so `docker compose up` blocks until everything is healthy:

```yaml
name: incident-and-ticket-enrichment-copilot

services:
  alarm-api:
    build: { context: ., args: { SERVICE_NAME: alarm-api-simulator } }
    container_name: alarm-api
    env_file: .env
    ports: ["${ALARM_API_PORT:-8000}:8000"]
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/health"]
      interval: 10s
      timeout: 3s
      retries: 5

  mcp-server:
    build: { context: ., args: { SERVICE_NAME: mcp-server-alarm-management } }
    container_name: mcp-server
    depends_on:
      alarm-api: { condition: service_healthy }
    env_file: .env
    ports: ["${MCP_SERVER_PORT:-9000}:9000"]

  copilot-backend:
    build: { context: ., args: { SERVICE_NAME: apps-backend } }
    container_name: copilot-backend
    depends_on:
      mcp-server: { condition: service_healthy }
    env_file: .env
    ports: ["${BACKEND_PORT:-8001}:8000"]

  frontend:
    build: { context: ., args: { SERVICE_NAME: apps-frontend } }
    container_name: frontend
    depends_on:
      copilot-backend: { condition: service_healthy }
    env_file: .env
    ports: ["${FRONTEND_PORT:-5173}:5173"]

  vector-store:
    image: chromadb/chroma:latest
    container_name: vector-store
    env_file: .env
    volumes: ["./.chroma:/chroma/chroma"]
    ports: ["${VECTOR_STORE_PORT:-8002}:8000"]
    healthcheck:
      test: ["CMD-SHELL", "curl -f http://localhost:8000/api/v1/heartbeat || exit 1"]
      interval: 10s
      timeout: 3s
      retries: 5

  ticket-mock:
    build: { context: ., args: { SERVICE_NAME: connectors } }
    container_name: ticket-mock
    env_file: .env
    ports: ["${TICKETING_API_PORT:-8003}:8000"]
```

**`.env.example`** — the eight required placeholders plus port overrides:

```bash
# --- Required placeholders (Submission_and_Evaluation_Guidelines.md § 10) ---

ALARM_API_BASE_URL=http://localhost:8000
ALARM_API_TOKEN=replace-me

MCP_SERVER_URL=http://localhost:9000

LLM_PROVIDER=openai
LLM_API_KEY=replace-me

VECTOR_STORE_URL=http://localhost:8002
DOCUMENT_PATH=./rag/documents

TICKETING_API_URL=http://localhost:8003

# --- Port overrides (optional) ---
ALARM_API_PORT=8000
MCP_SERVER_PORT=9000
BACKEND_PORT=8001
FRONTEND_PORT=5173
VECTOR_STORE_PORT=8002
TICKETING_API_PORT=8003
```

**`Makefile`** (placed at repo root):

```makefile
.PHONY: build up down test lint validate-api ingest help

help:
	@echo "Targets: build | up | down | test | lint | validate-api | ingest"

build:
	docker compose build

up:
	docker compose up --build -d
	@echo "Stack started. Tail logs with: docker compose logs -f"

down:
	docker compose down -v

test:
	docker compose run --rm copilot-backend pytest -ra

lint:
	docker compose run --rm copilot-backend ruff check .
	docker compose run --rm copilot-backend mypy apps mcp_servers rag connectors

validate-api:
	@echo "Placeholder — wired in Story 2.2.1 once the simulator exists."

ingest:
	@echo "Placeholder — wired in Story 4.1.2 once RAG lands."
```

**`.github/workflows/ci.yml`** — minimal scaffold that runs formatting, lint, and unit tests on every push:

```yaml
name: ci
on: [push, pull_request]
jobs:
  basic:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.13" }
      - run: pip install -e ".[dev]"
      - run: ruff check .
      - run: mypy apps mcp_servers rag connectors
      - run: pytest -ra
```

## 5. File manifest (full)

```
modified  pyproject.toml
modified  .gitignore
created   apps/backend/__init__.py
created   apps/backend/__main__.py
created   apps/frontend/__init__.py
created   apps/frontend/README.md
created   mcp-servers/alarm-management/__init__.py
created   mcp-servers/alarm-management/__main__.py
created   mcp-servers/optional-secondary-server/__init__.py
created   mcp-servers/optional-secondary-server/README.md
created   rag/ingestion/__init__.py
created   rag/retrieval/__init__.py
created   rag/documents/.gitkeep
created   rag/tests/__init__.py
created   connectors/__init__.py
created   tests/unit/__init__.py
created   tests/integration/__init__.py
created   tests/e2e/__init__.py
created   test-data/.gitkeep
created   scripts/.gitkeep
created   .github/workflows/ci.yml
created   Dockerfile
created   docker-compose.yml
created   .env.example
created   Makefile
```

`apps/backend/__main__.py` and `mcp-servers/alarm-management/__main__.py` are the only Python files beyond `__init__.py` stubs — they exist solely so Docker Compose can build, run, and pass healthchecks today.

## 6. Order of operations (one PR-friendly sequence)

1. Story 1.1.1 — directories + `.gitignore` + placeholder files. Verify `git status` shows the new tree.
2. Story 1.1.2 — rewrite `pyproject.toml`. Verify `pip install -e ".[dev]"` works locally on Python 3.13 and `pytest --collect-only` returns zero errors.
3. Story 1.1.3 — Dockerfile + docker-compose.yml + .env.example + Makefile + CI workflow. Verify `docker compose config` validates and `docker compose up --build` brings up healthy containers.
4. Self-review against Feature #11 AC.
5. Commit as three atomic commits, one per story, using `chore:` prefix. Merge into `developer` via PR.

## 7. Risks & open questions

- **`mcp-servers/` directory name vs Python `mcp_servers` package name:** handled by explicit `[tool.setuptools.package-dir]` mapping. The directory stays `mcp-servers/` per the brief; Python imports use `mcp_servers.*`.
- **Single shared Dockerfile vs per-service Dockerfile:** plan uses one parameterized Dockerfile. Avoids 6 near-identical files.
- **Chroma as the stub vector store:** swap the service image if you've decided on FAISS / Qdrant / Weaviate.
- **CI scope:** the workflow only runs format + lint + unit tests. Full CI from § 15 (build validation, integration tests, E2E) is added in Epic 8.

## 8. Verification plan

**Local checks (run before each commit and before opening the PR):**

```bash
# Tree sanity
ls apps/{backend,frontend} mcp-servers/{alarm-management,optional-secondary-server} \
   rag/{ingestion,retrieval,documents,tests} connectors tests/{unit,integration,e2e}

# Python env
python -m venv .venv && source .venv/bin/activate  # or .venv\Scripts\activate on Windows
pip install -e ".[dev]"
pytest --collect-only

# Lint
ruff check .
mypy apps mcp_servers rag connectors

# Docker
cp .env.example .env
docker compose config                  # validates compose file
docker compose up --build -d           # starts the stack
docker compose ps                      # all services "healthy" within ~30s
curl -sf http://localhost:8000/health  # alarm-api health
curl -sf http://localhost:9000/health  # mcp-server health (port from compose)
docker compose down -v
```

**GitHub-side checks (after pushing the branch):**

- `pull_request` workflow runs and turns green.
- Three commits visible on the branch.
- PR description references Issue #11 + Stories #29, #30, #31.

## 9. Out of scope

- Any implementation of the alarm API, MCP server tools, RAG ingestion, orchestrator, GUI, ticket service, or tests beyond placeholders. Those land in Epics 2–9.
- CI matrices, coverage thresholds, security scanners. Added in Epic 8.
- A populated `rag/documents/` corpus. Added in Epic 4.

---

**Awaiting your sign-off.** Reply with "approved" (or any edits you want first) and I'll start at Story 1.1.1.