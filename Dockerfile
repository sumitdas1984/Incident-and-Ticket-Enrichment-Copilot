# syntax=docker/dockerfile:1.7

# ---- Pull uv binary in isolation ----
FROM ghcr.io/astral-sh/uv:0.5.11 AS uv

# ---- Runtime image ----
# ARGs declared outside any FROM are 'between stages' and get blanked
# unless re-declared inside the next stage. The :--3.13 fallback
# covers both cases: --build-arg PYTHON_VERSION=... or default 3.13.
ARG PYTHON_VERSION=3.13

FROM python:${PYTHON_VERSION:-3.13}-slim AS base

# Re-declare so any ${PYTHON_VERSION} reference later in this stage
# resolves correctly under BuildKit's strict scoping rules.
ARG PYTHON_VERSION
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /app

RUN apt-get update \
 && apt-get install -y --no-install-recommends curl ca-certificates \
 && rm -rf /var/lib/apt/lists/*

# Install uv
COPY --from=uv /uv /uvx /usr/local/bin/

# Install dependencies first (better layer caching)
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project --no-group dev

# Copy source
COPY apps/ ./apps/
COPY mcp-servers/ ./mcp-servers/
COPY rag/ ./rag/
COPY connectors/ ./connectors/

# Install the project itself (no deps -- already resolved above)
ARG SERVICE_NAME=app
ENV SERVICE_NAME=${SERVICE_NAME}
RUN uv pip install --no-deps .

EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=3s --start-period=10s --retries=3 \
    CMD curl --fail http://localhost:${PORT:-8000}/health || exit 1

CMD ["sh", "-c", "exec uv run python -m ${SERVICE_NAME//-/_}.__main__"]