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
	@echo "Placeholder -- wired in Story 2.2.1 once the simulator exists."

ingest:
	@echo "Placeholder -- wired in Story 4.1.2 once RAG lands."