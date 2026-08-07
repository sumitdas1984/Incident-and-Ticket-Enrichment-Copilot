"""Incident builder — template-based projection to ``core.domain.Incident``.

The orchestrator runs a chain that produces a
:class:`~apps.backend.orchestrator.chain.ChainResult` plus the
plan that drove it. The :class:`IncidentBuilder` projects the
chain's outputs into a typed :class:`~core.domain.Incident`
payload — the deliverable the GUI renders and the ticket draft
(Epic 6) derives from.

Why a template, not an LLM
---------------------------

The brief's workflow step 6 ("prepare a structured incident
draft") is a *projection* of data the orchestrator already has.
The LLM does not invent any new information — it would only
rephrase what's already in the chain's outputs. Template
projection is:

* **Deterministic.** Same input → same output. The acceptance
  test pins the exact phrasing.
* **Cheap.** No LLM call, no extra latency.
* **Auditable.** The reviewer can trace each field back to a
  source chain step.

The LLM-driven version is a one-line switch later (pass
``llm_client`` and override the ``title`` / ``summary`` /
``likely_cause`` fields).

How projection works
--------------------

* ``id`` and ``created_at`` are synthesised (``uuid4`` + ``now``).
* ``title`` is the intent's first sentence + " — " + the
  first RAG citation's section header (or the intent alone when
  the RAG step produced no citations).
* ``summary`` is the chain's composed answer.
* ``severity`` is the highest severity across the chain's
  ``summarize_alarms`` output; falls back to ``LOW``.
* ``likely_cause`` is the first RAG citation's section header
  + first 200 chars of its excerpt.
* ``recommended_actions`` is the ``recommend_actions`` MCP tool
  output's ``actions`` list.
* ``citations`` is the chain's aggregated RAG citations.
* ``similar_tickets`` is the list of ``TicketSummary`` ids
  projected from the ``search_similar_tickets`` step output.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from core.domain import Citation, Incident, Severity

from .answer import compose_answer
from .chain import ChainResult
from .plan import (
    OrchestrationPlan,
    PlanStepKind,
)


@dataclass(frozen=True)
class IncidentContext:
    """The bundle the builder projects into an :class:`Incident`."""

    intent: str
    request: str
    plan: OrchestrationPlan
    chain_result: ChainResult


def build_incident(ctx: IncidentContext) -> Incident | None:
    """Project the chain's outputs into a typed :class:`Incident`.

    Returns ``None`` when the chain did not produce an
    alarm-context (no asset_id / site / alarm_id slot was
    extracted). Casual chat requests return ``None`` and the
    orchestrator's response envelope omits the ``incident``
    field.

    The projection is *defensive* — missing optional inputs
    (no RAG citations, no similar tickets, no recommendations)
    fall back to empty / default values rather than raising.
    Partial-failure is the rule, not the exception.
    """
    if not _is_incident_shaped(ctx):
        return None

    severity = _highest_severity(ctx)
    citations = _collect_citations(ctx)
    similar_ticket_ids = _collect_similar_ticket_ids(ctx)
    recommended_actions = _collect_recommended_actions(ctx)
    title = _compose_title(ctx)
    summary = _compose_summary(ctx)
    likely_cause = _compose_likely_cause(ctx)

    return Incident(
        id=uuid.uuid4().hex,
        title=title,
        summary=summary,
        severity=severity,
        likely_cause=likely_cause,
        recommended_actions=recommended_actions,
        citations=citations,
        similar_tickets=similar_ticket_ids,
        created_at=datetime.now(tz=UTC),
    )


def _is_incident_shaped(ctx: IncidentContext) -> bool:
    """Return True when the chain ran with an alarm-context.

    The mock planner emits alarm-context steps only when the
    request extracts an asset_id or site. Casual chat requests
    (e.g. "what's the weather?") produce no alarm-related
    steps and ``build_incident`` returns ``None``.
    """
    return any(
        step.kind in {
            PlanStepKind.TOOL_CALL,
            PlanStepKind.SEARCH_SIMILAR_TICKETS,
        }
        for step in ctx.plan.steps
    )


def _highest_severity(ctx: IncidentContext) -> Severity:
    """Return the highest severity across the chain's alarm outputs.

    Falls back to ``LOW`` when the chain produces no
    severity-bearing output (e.g. tag-only retrieval).
    """
    severities: list[Severity] = []
    for _step_id, output in ctx.chain_result.prior_outputs.items():
        if not isinstance(output, dict):
            continue
        items = output.get("items") or output.get("data") or output.get("results")
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, dict):
                continue
            sev = item.get("severity")
            if isinstance(sev, str):
                try:
                    severities.append(Severity(sev.lower()))
                except ValueError:
                    continue
    if not severities:
        return Severity.LOW
    priority = {Severity.LOW: 0, Severity.MEDIUM: 1, Severity.HIGH: 2, Severity.CRITICAL: 3}
    return max(severities, key=lambda s: priority[s])


def _collect_citations(ctx: IncidentContext) -> list[Citation]:
    """Return the chain's aggregated RAG citations."""
    return list(ctx.chain_result.citations)


def _collect_similar_ticket_ids(ctx: IncidentContext) -> list[str]:
    """Return the list of ticket ids from the ``search_similar_tickets`` step."""
    ids: list[str] = []
    for ticket in ctx.chain_result.similar_tickets:
        if not isinstance(ticket, dict):
            continue
        ticket_id = ticket.get("id")
        if isinstance(ticket_id, str):
            ids.append(ticket_id)
    return ids


def _collect_recommended_actions(ctx: IncidentContext) -> list[str]:
    """Return the actions list from the ``recommend_actions`` step output."""
    for _step_id, output in ctx.chain_result.prior_outputs.items():
        if not isinstance(output, dict):
            continue
        if "actions" in output and isinstance(output["actions"], list):
            return [str(a) for a in output["actions"]]
    return []


def _compose_title(ctx: IncidentContext) -> str:
    """First sentence of intent + " — " + first RAG section header."""
    intent = ctx.intent.strip()
    first_sentence = intent.split(".")[0].strip()
    if not first_sentence:
        first_sentence = "Incident"
    if ctx.chain_result.citations:
        first = ctx.chain_result.citations[0]
        section = first.section or ""
        if section:
            return f"{first_sentence} — {section}"
    return first_sentence


def _compose_summary(ctx: IncidentContext) -> str:
    """The chain's composed answer (the existing text-form response)."""
    return compose_answer(
        intent=ctx.intent,
        prior_outputs=ctx.chain_result.prior_outputs,
        citations=ctx.chain_result.citations,
        rag_confidence=ctx.chain_result.rag_confidence,
        dropped_count=ctx.chain_result.dropped_count,
        trace_size=len(ctx.chain_result.trace),
    )


def _compose_likely_cause(ctx: IncidentContext) -> str | None:
    """First RAG citation's section header + first 200 chars of its excerpt."""
    if not ctx.chain_result.citations:
        return None
    first = ctx.chain_result.citations[0]
    section = first.section or "Unknown"
    excerpt = (first.excerpt or "").strip()
    if not excerpt:
        return section
    return f"{section}: {excerpt[:200]}"


__all__ = ["IncidentContext", "build_incident"]
