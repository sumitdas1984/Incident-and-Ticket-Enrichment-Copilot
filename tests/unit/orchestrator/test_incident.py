"""Unit tests for the IncidentBuilder (Feature 5.2.1)."""
from __future__ import annotations

from typing import Any

from apps.backend.orchestrator.chain import ChainResult
from apps.backend.orchestrator.incident import IncidentContext, build_incident
from apps.backend.orchestrator.plan import (
    ComposePayload,
    OrchestrationPlan,
    PlanStep,
    PlanStepKind,
    RagQueryPayload,
    SimilarTicketsPayload,
    ToolCallPayload,
)
from core.domain import Citation, Severity, TraceStep


def _make_plan(*steps: PlanStep) -> OrchestrationPlan:
    return OrchestrationPlan(
        plan_id="p1",
        intent="Investigate Boiler Feed Pump 101 high-severity alarms",
        steps=list(steps),
    )


def _make_chain_result(
    *,
    prior_outputs: dict[str, Any] | None = None,
    citations: list[Citation] | None = None,
    similar_tickets: list[dict[str, Any]] | None = None,
    trace: list[TraceStep] | None = None,
) -> ChainResult:
    return ChainResult(
        answer="OK",
        intent="Investigate Boiler Feed Pump 101 high-severity alarms",
        citations=citations or [],
        trace=trace or [],
        rag_confidence="low",
        dropped_count=0,
        prior_outputs=prior_outputs or {},
        similar_tickets=similar_tickets or [],
    )


def test_build_incident_returns_none_without_alarm_context() -> None:
    """A casual chat request (no asset_id, no site) returns ``None``."""
    plan = _make_plan(
        PlanStep(
            step_id="s1",
            kind=PlanStepKind.RAG_QUERY,
            payload=RagQueryPayload(query="what's the weather"),
        ),
        PlanStep(
            step_id="s2",
            kind=PlanStepKind.COMPOSE,
            payload=ComposePayload(),
        ),
    )
    ctx = IncidentContext(
        intent="what's the weather",
        request="what's the weather",
        plan=plan,
        chain_result=_make_chain_result(),
    )
    assert build_incident(ctx) is None


def test_build_incident_returns_typed_payload() -> None:
    """A chain with alarm context produces a fully-populated Incident."""
    plan = _make_plan(
        PlanStep(
            step_id="s1",
            kind=PlanStepKind.TOOL_CALL,
            payload=ToolCallPayload(tool="search_assets", args={"query": "Boiler"}),
        ),
        PlanStep(
            step_id="s2",
            kind=PlanStepKind.SEARCH_SIMILAR_TICKETS,
            payload=SimilarTicketsPayload(text="boiler leak", limit=3),
        ),
        PlanStep(
            step_id="s3",
            kind=PlanStepKind.RAG_QUERY,
            payload=RagQueryPayload(query="boiler leak"),
        ),
        PlanStep(
            step_id="s4",
            kind=PlanStepKind.COMPOSE,
            payload=ComposePayload(),
        ),
    )
    citations = [
        Citation(
            doc_id="boiler-tube-leak-troubleshooting",
            section="1. Immediate actions",
            page=None,
            score=0.42,
            excerpt="Bring the boiler offline if pressure rises above 5.0 barg.",
        ),
    ]
    similar_tickets = [
        {"id": "TKT-1042", "title": "BFP high temp trip"},
        {"id": "TKT-1108", "title": "BFP low flow"},
    ]
    chain_result = _make_chain_result(
        prior_outputs={
            "s1": {"results": [{"id": "asset-bfp-101", "severity": "critical"}]},
            "s2": {"items": [{"id": "TKT-1042"}, {"id": "TKT-1108"}]},
            "s3": {
                "items": [
                    {"id": "alarm-bfp-101-001", "severity": "critical"},
                    {"id": "alarm-bfp-101-002", "severity": "high"},
                ],
            },
        },
        citations=citations,
        similar_tickets=similar_tickets,
    )
    ctx = IncidentContext(
        intent="Investigate Boiler Feed Pump 101 high-severity alarms",
        request="Investigate Boiler Feed Pump 101 high-severity alarms",
        plan=plan,
        chain_result=chain_result,
    )

    incident = build_incident(ctx)

    assert incident is not None
    assert incident.id
    assert incident.title.startswith("Investigate Boiler Feed Pump 101")
    # The summary is the chained answer's compose_output rendered
    # with the chain's citations + intent. We don't pin the exact
    # text (it's a template projection), but we assert the intent
    # is in there and a citation is referenced.
    assert "Investigate Boiler Feed Pump 101" in incident.summary
    assert "boiler-tube-leak-troubleshooting" in incident.summary
    assert incident.severity == Severity.CRITICAL
    assert incident.likely_cause  # has a value
    assert incident.recommended_actions == []
    assert len(incident.citations) == 1
    assert incident.similar_tickets == ["TKT-1042", "TKT-1108"]
    assert incident.created_at is not None


def test_build_incident_severity_falls_back_to_low() -> None:
    """No severity-bearing output → severity is LOW."""
    plan = _make_plan(
        PlanStep(
            step_id="s1",
            kind=PlanStepKind.TOOL_CALL,
            payload=ToolCallPayload(tool="search_assets"),
        ),
        PlanStep(
            step_id="s2",
            kind=PlanStepKind.COMPOSE,
            payload=ComposePayload(),
        ),
    )
    chain_result = _make_chain_result(
        prior_outputs={"s1": {"results": []}},  # no severity
    )
    ctx = IncidentContext(
        intent="x",
        request="x",
        plan=plan,
        chain_result=chain_result,
    )
    incident = build_incident(ctx)
    assert incident is not None
    assert incident.severity == Severity.LOW


def test_build_incident_picks_highest_severity() -> None:
    """Multiple severities → CRITICAL wins."""
    plan = _make_plan(
        PlanStep(
            step_id="s1",
            kind=PlanStepKind.TOOL_CALL,
            payload=ToolCallPayload(tool="summarize_alarms"),
        ),
        PlanStep(
            step_id="s2",
            kind=PlanStepKind.COMPOSE,
            payload=ComposePayload(),
        ),
    )
    chain_result = _make_chain_result(
        prior_outputs={
            "s1": {
                "items": [
                    {"id": "a", "severity": "low"},
                    {"id": "b", "severity": "critical"},
                    {"id": "c", "severity": "medium"},
                ],
            },
        },
    )
    ctx = IncidentContext(
        intent="x",
        request="x",
        plan=plan,
        chain_result=chain_result,
    )
    incident = build_incident(ctx)
    assert incident is not None
    assert incident.severity == Severity.CRITICAL


def test_build_incident_pulls_recommended_actions() -> None:
    """The ``recommend_actions`` MCP tool output drives the actions list."""
    plan = _make_plan(
        PlanStep(
            step_id="s1",
            kind=PlanStepKind.TOOL_CALL,
            payload=ToolCallPayload(tool="recommend_actions"),
        ),
        PlanStep(
            step_id="s2",
            kind=PlanStepKind.COMPOSE,
            payload=ComposePayload(),
        ),
    )
    chain_result = _make_chain_result(
        prior_outputs={
            "s1": {
                "actions": [
                    "Reduce feed rate to 50%.",
                    "Notify shift supervisor.",
                ],
            },
        },
    )
    ctx = IncidentContext(
        intent="x",
        request="x",
        plan=plan,
        chain_result=chain_result,
    )
    incident = build_incident(ctx)
    assert incident is not None
    assert incident.recommended_actions == [
        "Reduce feed rate to 50%.",
        "Notify shift supervisor.",
    ]


def test_build_incident_likely_cause_falls_back_to_section_only() -> None:
    """Citation with no excerpt → likely_cause is the section header alone."""
    plan = _make_plan(
        PlanStep(
            step_id="s1",
            kind=PlanStepKind.TOOL_CALL,
            payload=ToolCallPayload(tool="search_assets"),
        ),
        PlanStep(
            step_id="s2",
            kind=PlanStepKind.COMPOSE,
            payload=ComposePayload(),
        ),
    )
    citations = [
        Citation(
            doc_id="x",
            section="Header",
            page=None,
            score=0.5,
            excerpt="",
        ),
    ]
    ctx = IncidentContext(
        intent="x",
        request="x",
        plan=plan,
        chain_result=_make_chain_result(citations=citations),
    )
    incident = build_incident(ctx)
    assert incident is not None
    assert incident.likely_cause == "Header"


def test_build_incident_handles_missing_citations() -> None:
    """No RAG citations → likely_cause and title fall back cleanly."""
    plan = _make_plan(
        PlanStep(
            step_id="s1",
            kind=PlanStepKind.TOOL_CALL,
            payload=ToolCallPayload(tool="search_assets"),
        ),
        PlanStep(
            step_id="s2",
            kind=PlanStepKind.COMPOSE,
            payload=ComposePayload(),
        ),
    )
    ctx = IncidentContext(
        intent="Investigate X",
        request="Investigate X",
        plan=plan,
        chain_result=_make_chain_result(citations=[]),
    )
    incident = build_incident(ctx)
    assert incident is not None
    assert incident.title == "Investigate X"
    assert incident.likely_cause is None
    assert incident.citations == []


def test_build_incident_handles_empty_similar_tickets() -> None:
    """No similar tickets → empty list, not ``None``."""
    plan = _make_plan(
        PlanStep(
            step_id="s1",
            kind=PlanStepKind.SEARCH_SIMILAR_TICKETS,
            payload=SimilarTicketsPayload(text="x"),
        ),
        PlanStep(
            step_id="s2",
            kind=PlanStepKind.COMPOSE,
            payload=ComposePayload(),
        ),
    )
    ctx = IncidentContext(
        intent="x",
        request="x",
        plan=plan,
        chain_result=_make_chain_result(similar_tickets=[]),
    )
    incident = build_incident(ctx)
    assert incident is not None
    assert incident.similar_tickets == []


def test_build_incident_id_is_unique() -> None:
    """Two incidents from the same chain have different ids."""
    plan = _make_plan(
        PlanStep(
            step_id="s1",
            kind=PlanStepKind.TOOL_CALL,
            payload=ToolCallPayload(tool="search_assets"),
        ),
        PlanStep(
            step_id="s2",
            kind=PlanStepKind.COMPOSE,
            payload=ComposePayload(),
        ),
    )
    chain_result = _make_chain_result()
    ctx_a = IncidentContext(intent="x", request="x", plan=plan, chain_result=chain_result)
    ctx_b = IncidentContext(intent="x", request="x", plan=plan, chain_result=chain_result)
    assert build_incident(ctx_a).id != build_incident(ctx_b).id
