"""Unit tests for the orchestrator plan schema."""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from apps.backend.orchestrator.plan import (
    ComposePayload,
    OrchestrationPlan,
    PlanStep,
    PlanStepKind,
    RagQueryPayload,
    ToolCallPayload,
)
from rag.retrieval import RetrievalFilters


def test_tool_call_payload_requires_tool_name() -> None:
    with pytest.raises(ValidationError):
        ToolCallPayload()


def test_tool_call_payload_defaults_server_and_args() -> None:
    payload = ToolCallPayload(tool="search_assets")
    assert payload.kind == PlanStepKind.TOOL_CALL
    assert payload.server == "alarm-management"
    assert payload.args == {}


def test_rag_query_payload_carries_filters() -> None:
    payload = RagQueryPayload(query="boiler leak", k=3, filters=RetrievalFilters(asset_class="boiler"))
    assert payload.kind == PlanStepKind.RAG_QUERY
    assert payload.k == 3
    assert payload.filters == RetrievalFilters(asset_class="boiler")


def test_compose_payload_default_template() -> None:
    payload = ComposePayload()
    assert payload.kind == PlanStepKind.COMPOSE
    assert payload.template == "answer_with_citations"


def test_plan_step_dispatches_payload_by_kind() -> None:
    step = PlanStep(
        step_id="s1",
        kind=PlanStepKind.TOOL_CALL,
        payload=ToolCallPayload(tool="search_assets"),
    )
    assert isinstance(step.payload, ToolCallPayload)


def test_plan_rejects_unknown_field() -> None:
    with pytest.raises(ValidationError):
        OrchestrationPlan(
            plan_id="p1",
            intent="test",
            steps=[],
            bogus_field=1,  # type: ignore[call-arg]
        )


def test_plan_step_lookup() -> None:
    plan = OrchestrationPlan(
        plan_id="p1",
        intent="test",
        steps=[
            PlanStep(step_id="s1", kind=PlanStepKind.TOOL_CALL, payload=ToolCallPayload(tool="search_assets")),
            PlanStep(step_id="s2", kind=PlanStepKind.COMPOSE, payload=ComposePayload()),
        ],
    )
    assert plan.step("s1").kind == PlanStepKind.TOOL_CALL
    with pytest.raises(ValueError, match="not in plan"):
        plan.step("missing")


def test_plan_payload_kind_must_match_discriminator() -> None:
    # The payload's discriminator field is the payload's own ``kind``
    # literal, not the parent step's ``kind``. A RagQueryPayload is
    # only valid when the discriminator on the payload resolves to
    # ``"rag_query"``. Constructing a payload missing the kind
    # discriminator field (or with the wrong value) fails validation.
    with pytest.raises(ValidationError):
        # type: ignore[call-arg] — int is not a valid kind discriminator
        RagQueryPayload(query="x", kind=42)  # type: ignore[arg-type]


def test_plan_serializes_to_json_schema_with_oneof() -> None:
    schema = OrchestrationPlan.model_json_schema()
    # The schema must include a oneOf for the discriminated payload.
    payload_schema = schema["$defs"]["PlanStep"]["properties"]["payload"]
    assert "oneOf" in payload_schema or "anyOf" in payload_schema
