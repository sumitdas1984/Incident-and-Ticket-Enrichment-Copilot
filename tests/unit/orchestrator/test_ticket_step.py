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


def test_chain_surfaces_approval_metadata_on_success() -> None:
    """Feature 6.2 — when the ticket MCP returns a successful
    creation with an ``approval`` block, the chain lifts
    ``approved_by`` and ``request_id`` to the top of the trace
    step's output so the reviewer doesn't have to drill in.
    """

    async def runner() -> None:
        from unittest.mock import AsyncMock

        from core.domain import TraceStep

        async def _fake_call(*, tool: str, args: dict) -> tuple:
            return (
                {
                    "title": "x",
                    "body": "y",
                    "severity": "low",
                    "ticket_id": "TKT-9001",
                    "preview": False,
                    "approval": {
                        "approved_by": "operator",
                        "approved_at": "2026-08-08T10:00:00+00:00",
                        "request_id": "req-abc",
                    },
                },
                TraceStep(
                    server="ticketing",
                    tool=tool,
                    args=args,
                    output={
                        "title": "x",
                        "body": "y",
                        "severity": "low",
                        "ticket_id": "TKT-9001",
                        "preview": False,
                        "approval": {
                            "approved_by": "operator",
                            "approved_at": "2026-08-08T10:00:00+00:00",
                            "request_id": "req-abc",
                        },
                    },
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

        # Trace step: success, with approval metadata lifted.
        ts = result.trace[0]
        assert ts.outcome == "success"
        assert isinstance(ts.output, dict)
        assert ts.output["approved_by"] == "operator"
        assert ts.output["request_id"] == "req-abc"
        assert ts.output["ticket_id"] == "TKT-9001"

        # The prior_outputs dict mirrors the same enrichment.
        assert result.prior_outputs["t1"]["approved_by"] == "operator"
        assert result.prior_outputs["t1"]["request_id"] == "req-abc"

    asyncio.run(runner())


def test_chain_records_error_when_mcp_returns_approval_required() -> None:
    """Feature 6.2 — when the ticket MCP returns the
    ``approval_required`` envelope (HTTP 403 → ``is_error=True``
    on the MCP transport), the chain records a trace step with
    ``outcome="error"`` and the rejection message in the
    ``error`` field. No ticket is persisted; no approval
    metadata is lifted.
    """

    async def runner() -> None:
        from unittest.mock import AsyncMock

        from core.domain import TraceStep

        async def _fake_call(*, tool: str, args: dict) -> tuple:
            return (
                None,
                TraceStep(
                    server="ticketing",
                    tool=tool,
                    args=args,
                    output=None,
                    duration_ms=5,
                    outcome="error",
                    error=(
                        "ticket creation requires explicit approval "
                        "(code=approval_required, request_id=req-1)"
                    ),
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
                approved=False,  # the gate rejects this at the service layer
            )
        )
        result = await chain.run(plan)

        assert len(result.trace) == 1
        assert result.trace[0].outcome == "error"
        assert "approval_required" in result.trace[0].error
        assert "ticket creation requires explicit approval" in result.trace[0].error

    asyncio.run(runner())


def test_chain_does_not_lift_approval_on_error_step() -> None:
    """Defensive: the approval-lifting branch only runs when
    ``ts.outcome == "success"``. An error trace step with a
    non-None output dict (e.g. raw error payload) is left
    untouched."""

    async def runner() -> None:
        from unittest.mock import AsyncMock

        from core.domain import TraceStep

        async def _fake_call(*, tool: str, args: dict) -> tuple:
            return (
                {"code": "approval_required", "message": "x", "request_id": "r"},
                TraceStep(
                    server="ticketing",
                    tool=tool,
                    args=args,
                    output={"code": "approval_required", "message": "x", "request_id": "r"},
                    duration_ms=5,
                    outcome="error",
                    error="ticket creation requires explicit approval",
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
        ts = result.trace[0]
        assert ts.outcome == "error"
        # Output is unchanged — no ``approved_by`` lift on error.
        assert isinstance(ts.output, dict)
        assert "approved_by" not in ts.output
        assert "approval" not in ts.output

    asyncio.run(runner())
