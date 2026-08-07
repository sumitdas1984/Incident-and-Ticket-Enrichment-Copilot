"""End-to-end acceptance test for the brief's example scenario.

The brief's mandatory E2E scenario is:

> "Investigate recurring high-severity alarms for asset X over
> the last 90 days. Identify likely contributing factors.
> Retrieve the relevant operating procedure and return
> recommended actions."

This test asserts the orchestrator's response envelope carries:
- a non-empty ``answer`` (the final composed response),
- a non-empty ``citations`` list (the RAG citations),
- a ``trace`` with at least one step (the MCP + RAG chain),
- a ``rag_confidence`` band.

The MCP server in this test has no tools registered, so the
MCP step is recorded as ``outcome="error"`` — the chain runner
must continue to the RAG step and produce a response.
"""
from __future__ import annotations

import asyncio
import socket
import threading
import time
from pathlib import Path

import pytest
import uvicorn
from fastapi.testclient import TestClient
from mcp.server.mcpserver import MCPServer

from apps.backend import create_app
from apps.backend.orchestrator import MCPClient


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def mcp_url(monkeypatch: pytest.MonkeyPatch) -> str:
    """Stand up a uvicorn MCP server on a free port."""
    from mcp_servers.alarm_management.health import register_health_routes
    from mcp_servers.alarm_management.lifespan import make_asgi_app

    monkeypatch.setenv("ALARM_API_BASE_URL", "http://127.0.0.1:1")
    monkeypatch.setenv("ALARM_API_TOKEN", "test-token")
    from core.config import get_settings

    get_settings.cache_clear()

    server = MCPServer(name="alarm-management", instructions="Alarm Management MCP server.")
    register_health_routes(server, version="test")
    app = make_asgi_app(server)

    port = _free_port()
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
    uv = uvicorn.Server(config)
    thread = threading.Thread(target=lambda: asyncio.run(uv.serve()), daemon=True)
    thread.start()

    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.1):
                break
        except OSError:
            time.sleep(0.05)
    else:
        raise RuntimeError(f"uvicorn did not bind on port {port} in 5s")

    yield f"http://127.0.0.1:{port}"

    uv.should_exit = True
    thread.join(timeout=5.0)
    get_settings.cache_clear()


@pytest.fixture
def acceptance_client(mcp_url: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    """Build the orchestrator's FastAPI app wired against the
    test MCP server and a tiny in-memory RAG index."""
    from rag.ingestion import (
        Chunk,
        DeterministicEmbeddingModel,
        IndexMetadata,
        InMemoryVectorIndex,
    )
    from rag.retrieval import RetrievalService

    chunks = [
        Chunk(
            chunk_id="boiler#0",
            doc_id="boiler-tube-leak-troubleshooting",
            chunk_index=0,
            text="boiler tube leak troubleshooting procedure",
            section="1. Immediate actions",
            source_type="troubleshooting",
            asset_class="boiler",
            severity="critical",
            tags=[],
        ),
        Chunk(
            chunk_id="boiler#1",
            doc_id="boiler-tube-leak-troubleshooting",
            chunk_index=1,
            text="boiler tube leak repair options",
            section="5. Repair options",
            source_type="troubleshooting",
            asset_class="boiler",
            severity="critical",
            tags=[],
        ),
    ]
    embedder = DeterministicEmbeddingModel(dimension=64)
    meta = IndexMetadata(
        version=1,
        dimension=64,
        embedder_name="deterministic:64",
        chunk_count=len(chunks),
        document_count=1,
    )
    idx = InMemoryVectorIndex(metadata=meta)
    idx.add(chunks, embedder.embed([c.text for c in chunks]))
    service = RetrievalService(index=idx, embedder=embedder)

    from apps.backend.orchestrator.chain import ChainRunner
    from apps.backend.orchestrator.conversation import ConversationStore
    from apps.backend.orchestrator.rag_step import RagStepExecutor
    from apps.backend.wiring import OrchestratorBundle
    from core.config import get_settings

    monkeypatch.setenv("MCP_SERVER_URL", mcp_url)
    get_settings.cache_clear()

    bundle = OrchestratorBundle(
        chain=ChainRunner(mcp=MCPClient(base_url=mcp_url), rag=RagStepExecutor(service=service)),
        planner=__import__("apps.backend.orchestrator", fromlist=["MockPlanner"]).MockPlanner(),
        conversation_store=ConversationStore(),
        mcp=MCPClient(base_url=mcp_url),
        rag=RagStepExecutor(service=service),
    )

    app = create_app(bundle=bundle)
    return TestClient(app)


def test_brief_e2e_scenario(acceptance_client: TestClient) -> None:
    """The brief's mandatory E2E acceptance scenario."""
    r = acceptance_client.post(
        "/chat",
        json={
            "message": "Investigate recurring high-severity alarms for "
            "Boiler Feed Pump 101 over the last 90 days. "
            "Identify likely contributing factors. Retrieve the relevant "
            "operating procedure and return recommended actions.",
        },
    )
    assert r.status_code == 200
    body = r.json()

    # Every required field is present.
    assert body["answer"]
    assert isinstance(body["citations"], list)
    assert isinstance(body["trace"], list)
    assert body["rag_confidence"] in {"high", "medium", "low", "none"}
    assert isinstance(body["dropped_count"], int)
    assert body["conversation_id"]

    # The citations are from the RAG step.
    assert len(body["citations"]) >= 1
    assert any(c["doc_id"] for c in body["citations"])

    # The trace has at least one step (the MCP tool call OR the RAG step).
    assert len(body["trace"]) >= 1

    # The answer carries the intent and the RAG confidence band.
    assert "Intent" in body["answer"]
    assert "Confidence" in body["answer"]
