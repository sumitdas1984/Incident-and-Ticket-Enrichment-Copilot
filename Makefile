.PHONY: help install lock sync build up down test lint validate-api ingest run-alarm-api

help:
	@echo "Targets: install | lock | sync | build | up | down | test | lint | validate-api | ingest"

# --- Local Python via uv ---
install:
	uv python install 3.13
	uv sync

lock:
	uv lock

sync:
	uv sync

# --- Docker stack ---
build:
	docker compose build

up:
	docker compose up --build -d
	@echo "Stack started. Tail logs with: docker compose logs -f"

down:
	docker compose down -v

# Local checks (via uv). Inside-docker variants below reproduce CI parity.
test:
	uv run pytest -ra

lint:
	uv run ruff check .
	uv run mypy apps rag connectors core
	@echo "Smoke check: core.config loads without a real .env"
	uv run python -c "from core.config import get_settings; s = get_settings(); print('Settings OK, alarm_api_base_url=' + s.alarm_api_base_url)"

# Inside-docker variants — useful when reproducing CI parity
test-docker:
	docker compose run --rm copilot-backend uv run pytest -ra

lint-docker:
	docker compose run --rm copilot-backend uv run ruff check .
	docker compose run --rm copilot-backend uv run mypy apps rag connectors

# Story 2.2.1 — boot the Alarm API simulator, run both Postman collections
# against it via Newman, exit 0 on green. See scripts/validate_api.py.
#
# 1. Pick a free port (default 18000 to avoid clashing with other dev services).
# 2. `npm install` if node_modules is missing (first run).
# 3. Spawn the simulator in the background, capture its PID.
# 4. Poll /health until 200.
# 5. Run the orchestrator against both collections.
# 6. Kill the simulator on exit (success or failure).
validate-api:
	@command -v node >/dev/null 2>&1 || { echo "Node.js required (>=18). Install from https://nodejs.org"; exit 1; }
	@if [ ! -d node_modules ]; then echo "→ npm install (first run)"; npm install --no-audit --no-fund; fi
	@bash scripts/run_validate_api.sh

# Run the orchestrator directly (assumes a simulator is already running on
# ALARM_API_VALIDATE_PORT). Useful when iterating on the collections without
# spawning a fresh simulator each time.
validate-api-only:
	@uv run python scripts/validate_api.py \
		--collection postman/chaining/Alarm-API-Chaining.postman_collection.json \
		--collection postman/scenarios/Alarm-API-Scenarios.postman_collection.json \
		--base-url http://localhost:$${ALARM_API_VALIDATE_PORT:-18000} \
		--token $${ALARM_API_TOKEN:-demo-token} \
		--report-dir newman-report

ingest:
	uv run python -m rag.ingestion --corpus rag/documents --index var/index/v1.pkl

run-alarm-api:
	@ALARM_API_TOKEN=$${ALARM_API_TOKEN:-demo-token} uv run python -m connectors.alarm_api