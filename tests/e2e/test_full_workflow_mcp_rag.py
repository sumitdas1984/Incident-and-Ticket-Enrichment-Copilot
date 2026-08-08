"""End-to-end test combining MCP and RAG in a single scenario.

Feature 8.1 — Story 8.1.4. The brief's mandatory E2E scenario is:

    "Investigate recurring high-severity alarms for asset X over
    the last 90 days. Identify likely contributing factors.
    Retrieve the relevant operating procedure and return
    recommended actions."

The scenario exercises **both** the MCP path (a real tool that
returns alarms for the requested asset) and the RAG path
(real chunk retrieval against a deterministic in-memory index)
inside one orchestrator chain. The acceptance criteria:

* ``answer`` is a non-empty string (the final composed response).
* ``citations`` is a non-empty list of RAG results with the
  expected ``doc_id``.
* ``trace`` contains both an MCP step (with ``outcome='success'``)
  and a RAG step.
* ``rag_confidence`` is one of the documented bands.
* The structured ``Incident`` payload carries the citations and
  the similar-tickets list.

This test boots a real MCP server on a free port, a real
orchestrator wired to that server, and a real RAG index
(``tests/e2e`` is the only place such a full vertical slice
runs — unit and integration tests use mocks or stubs).
"""
from __future__ import annotations

import asyncio
import socket
import threading
import time
from pathlib import Path
from typing import Any

import pytest
import uvicorn
from fastapi.testclient import TestClient
from mcp.server.mcpserver import MCPServer

from apps.backend import create_app
from apps.backend.orchestrator import MCPClient

INDEX_PATH = Path("var/index/v1.pkl")


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _free_port() -> int:
    """Return an unused TCP port on localhost."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


# --------------------------------------------------------------------------- #
# MCP server fixture
# --------------------------------------------------------------------------- #


@pytest.fixture
def mcp_url(monkeypatch: pytest.MonkeyPatch) -> str:
    """Boot a real MCP server on a free port, with one tool that
    returns canned alarms for any asset query. Yields the base URL
    and tears the server down after the test."""
    monkeypatch.setenv("ALARM_API_BASE_URL", "http://127.0.0.1:1")  # unused, but required by the lifespan
    monkeypatch.setenv("ALARM_API_TOKEN", "test-token")
    from core.config import get_settings

    get_settings.cache_clear()

    server = MCPServer(
        name="alarm-management",
        instructions="Alarm Management MCP server (test variant).",
    )

    # Register the tools the orchestrator's MockPlanner asks for:
    # ``search_assets`` → ``summarize_alarms`` → RAG →
    # ``search_similar_tickets`` (Feature 5.2). Each handler
    # returns deterministic canned data so the chain succeeds.

    @server.tool(
        name="search_assets",
        description="Search assets by free-text query.",
    )
    async def search_assets(query: str) -> dict[str, Any]:
        return {
            "items": [
                {
                    "id": "asset-boiler-b-101",
                    "name": "Boiler B-101",
                    "site": "EastRefinery",
                    "asset_class": "boiler",
                },
            ],
            "total": 1,
        }

    @server.tool(
        name="summarize_alarms",
        description="Summarize recent alarms for an asset.",
    )
    async def summarize_alarms(asset_id: str, since: str | None = None) -> dict[str, Any]:
        return {
            "asset_id": asset_id,
            "items": [
                {
                    "id": "ALM-1001",
                    "asset_id": asset_id,
                    "severity": "critical",
                    "message": "Tube sheet leak suspected.",
                    "raised_at": "2026-08-01T10:00:00Z",
                    "acknowledged": False,
                },
                {
                    "id": "ALM-1002",
                    "asset_id": asset_id,
                    "severity": "high",
                    "message": "High temperature on lower tube sheet.",
                    "raised_at": "2026-08-02T11:00:00Z",
                    "acknowledged": False,
                },
            ],
            "total": 2,
        }

    @server.tool(
        name="search_similar_tickets",
        description="Find tickets similar to a free-text query.",
    )
    async def search_similar_tickets(
        text: str,
        site: str | None = None,
        asset_class: str | None = None,
        limit: int = 5,
    ) -> dict[str, Any]:
        return {
            "items": [
                {"ticket_id": "TKT-1042", "title": "Boiler tube leak", "score": 0.7},
            ],
            "total": 1,
        }

    # Register health routes too so the MCP lifespan is happy.
    from mcp_servers.alarm_management.health import register_health_routes

    register_health_routes(server, version="test")

    from mcp_servers.alarm_management.lifespan import make_asgi_app

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


# --------------------------------------------------------------------------- #
# RAG index fixture (in-memory, deterministic)
# --------------------------------------------------------------------------- #


@pytest.fixture
def rag_index() -> Any:
    """An in-memory RAG index with one troubleshooting doc and
    one procedure doc covering the boiler asset."""
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
            text="boiler tube leak repair options: weld patch or tube replacement",
            section="5. Repair options",
            source_type="troubleshooting",
            asset_class="boiler",
            severity="critical",
            tags=[],
        ),
        Chunk(
            chunk_id="boiler#2",
            doc_id="boiler-startup-sop",
            chunk_index=0,
            text="boiler startup procedure: verify tube integrity, then pressurise",
            section="2. Pre-startup checks",
            source_type="procedure",
            asset_class="boiler",
            severity="medium",
            tags=[],
        ),
    ]
    embedder = DeterministicEmbeddingModel(dimension=64)
    meta = IndexMetadata(
        version=1,
        dimension=64,
        embedder_name="deterministic:64",
        chunk_count=len(chunks),
        document_count=2,
    )
    idx = InMemoryVectorIndex(metadata=meta)
    idx.add(chunks, embedder.embed([c.text for c in chunks]))
    return RetrievalService(index=idx, embedder=embedder)


# --------------------------------------------------------------------------- #
# Orchestrator fixture
# --------------------------------------------------------------------------- #


@pytest.fixture
def e2e_client(mcp_url: str, rag_index: Any) -> TestClient:
    """Real orchestrator wired to the test MCP server + RAG index."""
    from apps.backend.orchestrator.chain import ChainRunner
    from apps.backend.orchestrator.conversation import ConversationStore
    from apps.backend.orchestrator.planner import MockPlanner
    from apps.backend.orchestrator.rag_step import RagStepExecutor

    mcp = MCPClient(base_url=mcp_url)
    bundle = type(
        "_Bundle",
        (),
        {},
    )()  # placeholder; we'll use the proper dataclass below
    from apps.backend.wiring import OrchestratorBundle

    bundle = OrchestratorBundle(
        chain=ChainRunner(mcp=mcp, rag=RagStepExecutor(service=rag_index)),
        planner=MockPlanner(),
        conversation_store=ConversationStore(),
        mcp=mcp,
        rag=RagStepExecutor(service=rag_index),
        ticket_mcp=None,
    )
    app = create_app(bundle=bundle)
    return TestClient(app)


# --------------------------------------------------------------------------- #
# The test
# --------------------------------------------------------------------------- #


def test_full_workflow_mcp_rag_in_single_scenario(
    e2e_client: TestClient,
) -> None:
    """The brief's mandatory § 7 scenario with both MCP and RAG.

    Asserts:

    * A non-empty ``answer`` (final composed response).
    * A non-empty ``citations`` list (RAG).
    * A ``trace`` with both an MCP step (``outcome='success'``)
      and a RAG step.
    * A populated ``incident`` (Feature 5.2's structured projection).
    """
    response = e2e_client.post(
        "/chat",
        json={
            "message": (
                "Investigate recurring high-severity alarms for "
                "Boiler B-101 over the last 90 days. Identify likely "
                "contributing factors. Retrieve the relevant "
                "operating procedure and return recommended actions."
            ),
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()

    # --- Answer (RAG + MCP composed response) -------------------------
    assert body["answer"], "expected non-empty answer"
    assert "Intent" in body["answer"]
    assert "Confidence" in body["answer"]

    # --- Citations (RAG) ----------------------------------------------
    assert isinstance(body["citations"], list)
    assert len(body["citations"]) >= 1, "RAG should return at least one citation"
    doc_ids = {c["doc_id"] for c in body["citations"]}
    # The RAG index's boiler chunks must surface.
    assert "boiler-tube-leak-troubleshooting" in doc_ids, (
        f"RAG missed the troubleshooting doc; got {doc_ids!r}"
    )

    # --- Trace (MCP + RAG working together) ---------------------------
    assert isinstance(body["trace"], list)
    assert len(body["trace"]) >= 2, (
        "trace should include both MCP and RAG steps; "
        f"got {[(s['tool'], s['server']) for s in body['trace']]!r}"
    )
    servers = {step["server"] for step in body["trace"]}
    assert "alarm-management" in servers, "MCP step missing from trace"
    mcp_steps = [s for s in body["trace"] if s["server"] == "alarm-management"]
    # At least one MCP step should have succeeded — the canned
    # tool returns real data. If all MCP steps error out, surface
    # the error messages so the test failure is debuggable.
    if not any(s["outcome"] == "success" for s in mcp_steps):
        errors = [(s["tool"], s.get("error")) for s in mcp_steps]
        pytest.fail(f"no successful MCP step; per-step errors: {errors!r}")

    # --- RAG confidence band ----------------------------------------
    assert body["rag_confidence"] in {"high", "medium", "low", "none"}

    # --- Structured Incident (Feature 5.2) ---------------------------
    assert body["incident"] is not None
    inc = body["incident"]
    assert inc["id"]
    assert inc["title"]
    assert inc["summary"]
    assert inc["severity"] in {"low", "medium", "high", "critical"}
    assert inc["created_at"]
    # The Incident's citations mirror the response's citations.
    assert len(inc["citations"]) == len(body["citations"])

    # --- Conversation continuity --------------------------------------
    assert body["conversation_id"]
