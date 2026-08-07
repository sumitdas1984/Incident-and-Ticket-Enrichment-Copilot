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