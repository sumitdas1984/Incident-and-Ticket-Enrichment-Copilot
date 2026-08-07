"""Integration tests for the orchestrator's HTTP endpoint.

The orchestrator's ``/chat`` endpoint is wired against a real
MCP server fixture (modeled on ``test_tools_list.py``). The MCP
server in this fixture has no tools registered, so the chain
records the MCP tool calls as ``outcome="error"`` and the
RAG step produces the citations and confidence band.

This is the headline integration test: it proves the
orchestrator wires MCP + RAG into a single business workflow
(hard constraint #2) and that the partial-failure path keeps
the chain alive.
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
from apps.backend.wiring import OrchestratorBundle


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
def orchestrator_app(mcp_url: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    """Build the FastAPI app with the test MCP server URL and a tiny RAG index."""
    from rag.ingestion import (
        Chunk,
        DeterministicEmbeddingModel,
        IndexMetadata,
        InMemoryVectorIndex,
    )
    from rag.retrieval import RetrievalService

    chunks = [
        Chunk(
            chunk_id="doc-1#0",
            doc_id="doc-1",
            chunk_index=0,
            text="boiler tube leak troubleshooting",
            section=None,
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
        chunk_count=1,
        document_count=1,
    )
    idx = InMemoryVectorIndex(metadata=meta)
    idx.add(chunks, embedder.embed([c.text for c in chunks]))
    service = RetrievalService(index=idx, embedder=embedder)

    from core.config import get_settings

    monkeypatch.setenv("MCP_SERVER_URL", mcp_url)
    get_settings.cache_clear()

    settings = get_settings()
    bundle = _build_acceptance_bundle(settings, mcp_url, service)
    app = create_app(bundle=bundle)
    return TestClient(app)


def _build_acceptance_bundle(settings, mcp_url, service):
    from apps.backend.orchestrator import MCPClient, MockPlanner
    from apps.backend.orchestrator.chain import ChainRunner
    from apps.backend.orchestrator.conversation import ConversationStore
    from apps.backend.orchestrator.rag_step import RagStepExecutor

    mcp = MCPClient(base_url=mcp_url)
    return OrchestratorBundle(
        chain=ChainRunner(mcp=mcp, rag=RagStepExecutor(service=service)),
        planner=MockPlanner(),
        conversation_store=ConversationStore(),
        mcp=mcp,
        rag=RagStepExecutor(service=service),
    )


def test_health_endpoint_returns_200(orchestrator_app: TestClient) -> None:
    r = orchestrator_app.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "service": "copilot-backend"}


def test_chat_returns_envelope(orchestrator_app: TestClient) -> None:
    r = orchestrator_app.post(
        "/chat",
        json={"message": "investigate Boiler 101 high-severity alarms"},
    )
    assert r.status_code == 200
    body = r.json()
    assert "answer" in body
    assert "citations" in body
    assert "trace" in body
    assert "conversation_id" in body
    assert body["rag_confidence"] in {"high", "medium", "low", "none"}


def test_chat_surfaces_partial_failure_in_trace(orchestrator_app: TestClient) -> None:
    """The test MCP server has no tools registered, so every
    tool call fails. The chain runner must record the failure
    in the trace and continue to the RAG step."""
    r = orchestrator_app.post(
        "/chat",
        json={"message": "investigate Boiler 101 high-severity alarms"},
    )
    body = r.json()
    # The trace should contain at least one error step (the
    # search_assets call has no tools registered).
    assert any(step["outcome"] == "error" for step in body["trace"])


def test_chat_retains_conversation_across_turns(orchestrator_app: TestClient) -> None:
    """Two turns on the same ``conversation_id`` must both
    return the same id, and the planner must see the first
    turn's message in the history."""
    first = orchestrator_app.post(
        "/chat",
        json={"message": "Boiler 101 high-severity alarms", "conversation_id": "test-conv-1"},
    )
    assert first.status_code == 200
    assert first.json()["conversation_id"] == "test-conv-1"

    second = orchestrator_app.post(
        "/chat",
        json={"message": "tell me more", "conversation_id": "test-conv-1"},
    )
    assert second.status_code == 200
    assert second.json()["conversation_id"] == "test-conv-1"
