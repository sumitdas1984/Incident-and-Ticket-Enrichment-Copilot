"""Unit tests for the orchestrator's ticket draft step (Feature 6.1)."""
from __future__ import annotations

import asyncio

import pytest

from apps.backend.orchestrator.plan import (
    CreateTicketDraftPayload,
    OrchestrationPlan,
    PlanStep,
    PlanStepKind,
)


def _make_plan(payload: CreateTicketDraftPayload) -> OrchestrationPlan:
    return OrchestrationPlan(
        plan_id="p1",
        intent="draft ticket",
        steps=[
            PlanStep(
                step_id="t1",
                kind=PlanStepKind.CREATE_TICKET_DRAFT,
                payload=payload,
            ),
        ],
    )


def test_create_ticket_draft_payload_carries_incident_and_approved() -> None:
    payload = CreateTicketDraftPayload(
        incident={"id": "INC-1", "title": "x", "severity": "high"},
        approved=True,
    )
    assert payload.kind == PlanStepKind.CREATE_TICKET_DRAFT
    assert payload.approved is True
    assert payload.incident["id"] == "INC-1"


def test_create_ticket_draft_payload_defaults_approved_false() -> None:
    payload = CreateTicketDraftPayload(incident={"id": "INC-1"})
    assert payload.approved is False


def test_create_ticket_draft_payload_frozen() -> None:
    """Pydantic v2 raises ``ValidationError`` (not Python's
    ``FrozenInstanceError``) when an assignment violates a frozen
    field. The test pins the contract: ``CreateTicketDraftPayload``
    is immutable; callers must use ``model_copy(update=...)``."""
    from pydantic import ValidationError

    payload = CreateTicketDraftPayload(incident={"id": "INC-1"})
    with pytest.raises(ValidationError):
        payload.approved = True  # type: ignore[misc]


def test_plan_dispatches_create_ticket_draft_via_chain() -> None:
    """Smoke test: the chain runner accepts a one-step plan with
    CREATE_TICKET_DRAFT. The call to the ticket MCP fails because
    no server is running, but the dispatch is wired."""

    async def runner() -> None:
        from unittest.mock import AsyncMock

        # Stub the ticket MCP so we don't hit a real network.
        from core.domain import TraceStep

        async def _fake_call(*, tool: str, args: dict) -> tuple:
            return (
                {"title": "x", "body": "y", "severity": "low", "ticket_id": "TKT-9001", "preview": False},
                TraceStep(
                    server="ticketing",
                    tool=tool,
                    args=args,
                    output={"title": "x", "body": "y", "severity": "low", "ticket_id": "TKT-9001", "preview": False},
                    duration_ms=10,
                    outcome="success",
                ),
            )

        fake = AsyncMock()
        fake.call = _fake_call

        from apps.backend.orchestrator.chain import ChainRunner
        from apps.backend.orchestrator.rag_step import RagStepExecutor
        from rag.ingestion import (
            Chunk,
            DeterministicEmbeddingModel,
            IndexMetadata,
            InMemoryVectorIndex,
        )
        from rag.retrieval import RetrievalService

        chunk = Chunk(
            chunk_id="x#0",
            doc_id="x",
            chunk_index=0,
            text="x",
            section=None,
            source_type="troubleshooting",
            asset_class=None,
            severity=None,
            tags=[],
        )
        embedder = DeterministicEmbeddingModel(dimension=64)
        meta = IndexMetadata(
            version=1,
            dimension=64,
            embedder_name="deterministic:64",
            chunk_count=1,
            document_count=1,
        )
        idx = InMemoryVectorIndex(metadata=meta)
        idx.add([chunk], embedder.embed(["x"]))
        service = RetrievalService(index=idx, embedder=embedder)
        rag = RagStepExecutor(service=service)

        chain = ChainRunner(
            mcp=AsyncMock(),
            rag=rag,
            ticket_mcp=fake,
        )
        plan = _make_plan(
            CreateTicketDraftPayload(
                incident={"id": "INC-1", "title": "x", "severity": "high"},
                approved=True,
            )
        )
        result = await chain.run(plan)

        assert len(result.prior_outputs["t1"]) > 0
        assert result.prior_outputs["t1"]["ticket_id"] == "TKT-9001"
        assert len(result.trace) == 1
        assert result.trace[0].tool == "create_ticket_draft"
        assert result.trace[0].outcome == "success"

    asyncio.run(runner())


def test_chain_records_error_when_ticket_mcp_not_configured() -> None:
    """When ``ticket_mcp=None``, the chain records a trace step
    with ``outcome="error"`` and an explanatory message."""

    async def runner() -> None:
        from unittest.mock import AsyncMock

        from apps.backend.orchestrator.chain import ChainRunner
        from apps.backend.orchestrator.rag_step import RagStepExecutor
        from rag.ingestion import (
            Chunk,
            DeterministicEmbeddingModel,
            IndexMetadata,
            InMemoryVectorIndex,
        )
        from rag.retrieval import RetrievalService

        chunk = Chunk(
            chunk_id="x#0",
            doc_id="x",
            chunk_index=0,
            text="x",
            section=None,
            source_type="troubleshooting",
            asset_class=None,
            severity=None,
            tags=[],
        )
        embedder = DeterministicEmbeddingModel(dimension=64)
        meta = IndexMetadata(
            version=1,
            dimension=64,
            embedder_name="deterministic:64",
            chunk_count=1,
            document_count=1,
        )
        idx = InMemoryVectorIndex(metadata=meta)
        idx.add([chunk], embedder.embed(["x"]))
        service = RetrievalService(index=idx, embedder=embedder)
        rag = RagStepExecutor(service=service)

        chain = ChainRunner(
            mcp=AsyncMock(),
            rag=rag,
            ticket_mcp=None,
        )
        plan = _make_plan(
            CreateTicketDraftPayload(
                incident={"id": "INC-1", "title": "x", "severity": "high"},
                approved=False,
            )
        )
        result = await chain.run(plan)
        assert result.trace[0].outcome == "error"
        assert "ticket" in result.trace[0].error.lower()

    asyncio.run(runner())
