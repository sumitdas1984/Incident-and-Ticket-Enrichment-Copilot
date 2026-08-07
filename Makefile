.PHONY: help install lock sync build up down test lint validate-api ingest

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
	uv run mypy apps rag connectors

# Inside-docker variants — useful when reproducing CI parity
test-docker:
	docker compose run --rm copilot-backend uv run pytest -ra

lint-docker:
	docker compose run --rm copilot-backend uv run ruff check .
	docker compose run --rm copilot-backend uv run mypy apps rag connectors

# Stubbed — wired in later epics
validate-api:
	@echo "Placeholder -- wired in Story 2.2.1 once the simulator exists."

ingest:
	@echo "Placeholder -- wired in Story 4.1.2 once RAG lands."