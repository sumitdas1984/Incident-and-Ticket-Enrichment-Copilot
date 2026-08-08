"""Typed plan schema for the orchestrator.

The plan is the planner's output: a list of typed steps that
the chain runner executes. Each step has a ``kind`` field
that doubles as the Pydantic discriminator — every payload
type carries a ``kind`` literal so the discriminator can pick
the right model from the union.

Why a discriminated union
-------------------------

* The LLM-facing JSON schema has one clean ``oneOf`` per kind.
* The chain runner can ``match`` on ``step.kind`` with confidence
  that ``payload`` is the right type.
* Validation errors are scoped to the offending step, not the
  whole plan.

Why a list of plans, not a DAG
------------------------------

The chain runner is sequential in v1. A ``depends_on`` field is
carried so the runner can resolve waves later; it is parsed but
not enforced (every step is treated as independent).
"""
from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from rag.retrieval import RetrievalFilters


class PlanStepKind(StrEnum):
    """Step kind — drives the chain runner's dispatch."""

    TOOL_CALL = "tool_call"
    RAG_QUERY = "rag_query"
    SEARCH_SIMILAR_TICKETS = "search_similar_tickets"
    CREATE_TICKET_DRAFT = "create_ticket_draft"
    COMPOSE = "compose"


_BASE_PLAN_CONFIG = ConfigDict(extra="forbid", frozen=True)


class ToolCallPayload(BaseModel):
    """Invoke an MCP tool on the configured server."""

    model_config = _BASE_PLAN_CONFIG

    kind: Literal[PlanStepKind.TOOL_CALL] = PlanStepKind.TOOL_CALL
    server: str = "alarm-management"
    tool: str
    args: dict[str, Any] = Field(default_factory=dict)


class RagQueryPayload(BaseModel):
    """Query the RAG service with the given text."""

    model_config = _BASE_PLAN_CONFIG

    kind: Literal[PlanStepKind.RAG_QUERY] = PlanStepKind.RAG_QUERY
    query: str
    k: int = 5
    filters: RetrievalFilters | None = None


class SimilarTicketsPayload(BaseModel):
    """Search the alarm-api for past tickets matching the query.

    The handler invokes the alarm-management MCP server's
    ``search_similar_tickets`` tool. The result is a list of
    ticket summaries (id, title, status, similarity, resolution
    excerpt) that the incident builder threads into the
    ``Incident.similar_tickets`` field.
    """

    model_config = _BASE_PLAN_CONFIG

    kind: Literal[PlanStepKind.SEARCH_SIMILAR_TICKETS] = PlanStepKind.SEARCH_SIMILAR_TICKETS
    text: str
    site: str | None = None
    asset_class: str | None = None
    limit: int = 5


class ComposePayload(BaseModel):
    """Assemble the final answer from the prior step outputs."""

    model_config = _BASE_PLAN_CONFIG

    kind: Literal[PlanStepKind.COMPOSE] = PlanStepKind.COMPOSE
    template: Literal["answer_with_citations", "incident_summary"] = (
        "answer_with_citations"
    )


class CreateTicketDraftPayload(BaseModel):
    """Generate (and optionally persist) a ticket draft from an Incident.

    The handler invokes the ticketing MCP server's
    ``create_ticket_draft`` tool. The ``incident`` payload is the
    structured ``core.domain.Incident`` field-for-field; the MCP
    client serialises it via ``model_dump(mode="json")`` before
    sending. The ``approved`` flag is the explicit-user-confirmation
    gate (hard constraint #3): the orchestrator's chain sets it
    to ``True`` only when the user has confirmed the create.
    """

    model_config = _BASE_PLAN_CONFIG

    kind: Literal[PlanStepKind.CREATE_TICKET_DRAFT] = PlanStepKind.CREATE_TICKET_DRAFT
    incident: dict[str, Any] = Field(default_factory=dict)
    approved: bool = False


class PlanStep(BaseModel):
    """One typed step in the plan."""

    model_config = _BASE_PLAN_CONFIG

    step_id: str
    kind: PlanStepKind
    payload: ToolCallPayload | RagQueryPayload | SimilarTicketsPayload | CreateTicketDraftPayload | ComposePayload = Field(  # noqa: E501
        discriminator="kind",
    )
    depends_on: list[str] = Field(default_factory=list)


class OrchestrationPlan(BaseModel):
    """The planner's output. One plan per ``/chat`` request."""

    model_config = _BASE_PLAN_CONFIG

    plan_id: str
    intent: str
    steps: list[PlanStep]

    def step(self, step_id: str) -> PlanStep:
        """Return the step with the given ``step_id``.

        Raises ``ValueError`` if the step is not in the plan. The
        chain runner uses this to resolve ``depends_on`` references.
        """
        for s in self.steps:
            if s.step_id == step_id:
                return s
        raise ValueError(f"step {step_id!r} not in plan {self.plan_id!r}")


__all__ = [
    "ComposePayload",
    "CreateTicketDraftPayload",
    "OrchestrationPlan",
    "PlanStep",
    "PlanStepKind",
    "RagQueryPayload",
    "SimilarTicketsPayload",
    "ToolCallPayload",
]
