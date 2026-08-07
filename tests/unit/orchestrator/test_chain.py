"""Unit tests for the chain runner."""
from __future__ import annotations

import asyncio
from typing import Any

from apps.backend.orchestrator.chain import ChainRunner
from apps.backend.orchestrator.plan import (
    ComposePayload,
    OrchestrationPlan,
    PlanStep,
    PlanStepKind,
    RagQueryPayload,
    ToolCallPayload,
)
from apps.backend.orchestrator.rag_step import RagStepExecutor
from rag.ingestion import (
    Chunk,
    DeterministicEmbeddingModel,
    IndexMetadata,
    InMemoryVectorIndex,
)
from rag.retrieval import RetrievalService

# --- Test doubles ---


class _FakeMCP:
    """Records invocations and returns canned output."""

    def __init__(self, output: Any = None, raise_on: str | None = None) -> None:
        if output is None:
            output = {"results": []}
        self.calls: list[dict[str, Any]] = []
        self.output = output
        self.raise_on = raise_on

    async def call(self, *, tool: str, args: dict[str, Any]) -> tuple[Any, Any]:
        from core.domain import TraceStep

        self.calls.append({"tool": tool, "args": args})
        if self.raise_on and tool == self.raise_on:
            raise RuntimeError("simulated failure")
        ts = TraceStep(
            server="alarm-management",
            tool=tool,
            args=args,
            output=self.output,
            duration_ms=5,
            outcome="success",
        )
        return self.output, ts


def _build_rag() -> RagStepExecutor:
    chunks = [
        Chunk(
            chunk_id="doc-1#0",
            doc_id="doc-1",
            chunk_index=0,
            text="x",
            section=None,
            source_type="troubleshooting",
            asset_class=None,
            severity=None,
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
    idx.add(chunks, embedder.embed(["x"]))
    service = RetrievalService(index=idx, embedder=embedder)
    return RagStepExecutor(service=service)


# --- Tests ---


def test_chain_runs_3_step_plan() -> None:
    async def runner() -> None:
        mcp = _FakeMCP(output={"results": [{"id": "a"}]})
        chain = ChainRunner(mcp=mcp, rag=_build_rag())
        plan = OrchestrationPlan(
            plan_id="p1",
            intent="test",
            steps=[
                PlanStep(step_id="s1", kind=PlanStepKind.TOOL_CALL, payload=ToolCallPayload(tool="search_assets")),
                PlanStep(step_id="s2", kind=PlanStepKind.RAG_QUERY, payload=RagQueryPayload(query="x")),
                PlanStep(step_id="s3", kind=PlanStepKind.COMPOSE, payload=ComposePayload()),
            ],
        )
        result = await chain.run(plan)
        assert result.answer
        assert len(result.trace) == 1
        assert len(result.citations) == 1

    asyncio.run(runner())


def test_chain_continues_after_partial_tool_failure() -> None:
    async def runner() -> None:
        mcp = _FakeMCP(output={"results": []}, raise_on="search_assets")
        chain = ChainRunner(mcp=mcp, rag=_build_rag())
        plan = OrchestrationPlan(
            plan_id="p1",
            intent="test",
            steps=[
                PlanStep(step_id="s1", kind=PlanStepKind.TOOL_CALL, payload=ToolCallPayload(tool="search_assets")),
                PlanStep(step_id="s2", kind=PlanStepKind.RAG_QUERY, payload=RagQueryPayload(query="x")),
                PlanStep(step_id="s3", kind=PlanStepKind.COMPOSE, payload=ComposePayload()),
            ],
        )
        result = await chain.run(plan)
        # The first tool step failed but the chain still produced an answer.
        assert result.trace[0].outcome == "error"
        assert result.answer

    asyncio.run(runner())


def test_chain_aggregates_citations_across_rag_steps() -> None:
    async def runner() -> None:
        mcp = _FakeMCP()
        chain = ChainRunner(mcp=mcp, rag=_build_rag())
        plan = OrchestrationPlan(
            plan_id="p1",
            intent="test",
            steps=[
                PlanStep(step_id="s1", kind=PlanStepKind.RAG_QUERY, payload=RagQueryPayload(query="x")),
                PlanStep(step_id="s2", kind=PlanStepKind.RAG_QUERY, payload=RagQueryPayload(query="y")),
                PlanStep(step_id="s3", kind=PlanStepKind.COMPOSE, payload=ComposePayload()),
            ],
        )
        result = await chain.run(plan)
        assert len(result.citations) >= 2

    asyncio.run(runner())


def test_chain_resolve_waves_returns_one_wave_for_v1() -> None:
    plan = OrchestrationPlan(
        plan_id="p1",
        intent="test",
        steps=[
            PlanStep(step_id="s1", kind=PlanStepKind.TOOL_CALL, payload=ToolCallPayload(tool="x")),
            PlanStep(step_id="s2", kind=PlanStepKind.COMPOSE, payload=ComposePayload()),
        ],
    )
    chain = ChainRunner(mcp=_FakeMCP(), rag=_build_rag())
    waves = chain._resolve_waves(plan)  # noqa: SLF001
    assert len(waves) == 1
    assert {s.step_id for s in waves[0]} == {"s1", "s2"}


def test_chain_final_answer_uses_compose_step_output() -> None:
    async def runner() -> None:
        mcp = _FakeMCP()
        chain = ChainRunner(mcp=mcp, rag=_build_rag())
        plan = OrchestrationPlan(
            plan_id="p1",
            intent="test",
            steps=[
                PlanStep(step_id="s1", kind=PlanStepKind.COMPOSE, payload=ComposePayload()),
            ],
        )
        result = await chain.run(plan)
        assert "Intent" in result.answer

    asyncio.run(runner())
