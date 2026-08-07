"""Chain runner — executes a plan against the MCP client and RAG.

The chain runner walks the plan's steps in order, dispatching
each step to the right executor. It captures:

* ``output`` per step (in ``ChainResult.prior_outputs``).
* ``trace`` per MCP step (in ``ChainResult.trace``).
* ``citations`` from every RAG step (in ``ChainResult.citations``).
* ``rag_confidence`` and ``dropped_count`` from the last RAG step.

A single MCP tool failure is *not* fatal — the step is recorded
with ``outcome="error"`` and the chain continues. Only permanent
failures (the MCP server is unreachable, the RAG service is
broken) raise :class:`ChainError`.

Why wave-aware but sequential in v1
-----------------------------------

The runner exposes :meth:`_resolve_waves` so a future parallel
executor can group independent steps. In v1 the resolver
returns ``[plan.steps]`` (one wave = the whole plan). The
executor iterates waves and runs each step in the wave
sequentially with ``asyncio.gather`` (one item per wave in v1).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from core.domain import Citation, TraceStep
from rag.retrieval import RetrievalFilters

from .answer import compose_answer
from .citations import to_domain_citation
from .errors import ChainError
from .mcp_client import MCPClient
from .plan import (
    ComposePayload,
    OrchestrationPlan,
    PlanStep,
    PlanStepKind,
    RagQueryPayload,
    ToolCallPayload,
)
from .rag_step import RagStepExecutor


@dataclass
class ChainResult:
    """The output of one chain run.

    Attributes
    ----------
    answer:
        The final composed answer (rendered from the chain's
        outputs by ``compose_answer``).
    intent:
        The planner's intent string.
    citations:
        Aggregated citations from every RAG step.
    trace:
        One :class:`TraceStep` per MCP step (failed steps included).
    rag_confidence:
        The last RAG step's confidence band (``"high"`` /
        ``"medium"`` / ``"low"`` / ``"none"``).
    dropped_count:
        The number of chunks dropped by the RAG injection blocklist.
    prior_outputs:
        Per-step output dict keyed by ``step_id``. The compose step
        reads from this to assemble the final answer.
    """

    answer: str
    intent: str
    citations: list[Citation] = field(default_factory=list)
    trace: list[TraceStep] = field(default_factory=list)
    rag_confidence: str = "none"
    dropped_count: int = 0
    prior_outputs: dict[str, Any] = field(default_factory=dict)


class ChainRunner:
    """Execute a plan; capture the trace and citations."""

    def __init__(
        self,
        *,
        mcp: MCPClient,
        rag: RagStepExecutor,
    ) -> None:
        self._mcp = mcp
        self._rag = rag

    async def run(self, plan: OrchestrationPlan) -> ChainResult:
        """Execute ``plan`` and return the :class:`ChainResult`."""
        waves = self._resolve_waves(plan)
        prior_outputs: dict[str, Any] = {}
        trace: list[TraceStep] = []
        citations: list[Citation] = []
        rag_confidence = "none"
        dropped_count = 0

        for wave in waves:
            for step in wave:
                if step.kind == PlanStepKind.TOOL_CALL:
                    payload = step.payload
                    if not isinstance(payload, ToolCallPayload):
                        raise ChainError(f"step {step.step_id} kind=tool_call but payload is {type(payload).__name__}")
                    try:
                        output, ts = await self._mcp.call(
                            tool=payload.tool, args=payload.args,
                        )
                    except Exception as exc:  # noqa: BLE001 — surface partial failure as trace step
                        output = None
                        ts = TraceStep(
                            server=payload.server,
                            tool=payload.tool,
                            args=payload.args,
                            output=None,
                            duration_ms=0,
                            outcome="error",
                            error=str(exc),
                        )
                    prior_outputs[step.step_id] = output
                    trace.append(ts)
                elif step.kind == PlanStepKind.RAG_QUERY:
                    payload = step.payload
                    if not isinstance(payload, RagQueryPayload):
                        raise ChainError(f"step {step.step_id} kind=rag_query but payload is {type(payload).__name__}")
                    # Re-apply the optional filters via the executor — the
                    # server-side retrieval service is the source of truth.

                    rag_filters = payload.filters
                    if rag_filters is not None:
                        # The RagStepExecutor.retrieve supports filters
                        # via the underlying service. Pass them through.
                        rag_result = self._execute_rag_with_filters(
                            query=payload.query,
                            k=payload.k,
                            filters=rag_filters,
                        )
                    else:
                        rag_result = await self._rag.execute(query=payload.query, k=payload.k)
                    prior_outputs[step.step_id] = rag_result
                    citations.extend(to_domain_citation(c) for c in rag_result.citations)
                    rag_confidence = rag_result.confidence
                    dropped_count = rag_result.dropped_count
                else:  # COMPOSE
                    payload = step.payload
                    if not isinstance(payload, ComposePayload):
                        raise ChainError(f"step {step.step_id} kind=compose but payload is {type(payload).__name__}")
                    answer = compose_answer(
                        intent=plan.intent,
                        prior_outputs=prior_outputs,
                        citations=citations,
                        rag_confidence=rag_confidence,
                        dropped_count=dropped_count,
                        trace_size=len(trace) + 1,
                    )
                    prior_outputs[step.step_id] = answer

        answer = _final_answer(prior_outputs, plan)
        return ChainResult(
            answer=answer,
            intent=plan.intent,
            citations=citations,
            trace=trace,
            rag_confidence=rag_confidence,
            dropped_count=dropped_count,
            prior_outputs=prior_outputs,
        )

    def _execute_rag_with_filters(
        self, *, query: str, k: int, filters: RetrievalFilters,
    ):
        """Forward ``filters`` to the retrieval service.

        The :class:`RagStepExecutor` does not expose ``filters``
        directly because the chain runner normally decides
        whether to use them. This internal helper keeps the
        public surface tight.
        """
        # Reach through to the service's underlying index/embedder.
        service = self._rag._service  # noqa: SLF001 — internal call
        return service.retrieve(query, k=k, filters=filters)

    def _resolve_waves(self, plan: OrchestrationPlan) -> list[list[PlanStep]]:
        """Group steps into waves for parallel execution.

        v1: every step is independent (``depends_on`` is parsed
        but not enforced). The result is one wave containing
        every step in plan order. Future versions will topologically
        sort steps by ``depends_on`` and return multiple waves.
        """
        return [plan.steps]


def _final_answer(prior_outputs: dict[str, Any], plan: OrchestrationPlan) -> str:
    """Return the final answer string from the chain's outputs.

    If the last step is a COMPOSE step, its output is the answer.
    Otherwise, fall back to the dict's last value (or empty).
    """
    for step in reversed(plan.steps):
        if step.kind == PlanStepKind.COMPOSE and step.step_id in prior_outputs:
            return str(prior_outputs[step.step_id])
    if plan.steps and plan.steps[-1].step_id in prior_outputs:
        return str(prior_outputs[plan.steps[-1].step_id])
    return ""


__all__ = ["ChainResult", "ChainRunner"]
