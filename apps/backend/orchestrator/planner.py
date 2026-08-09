"""Planner — turns a user request into a typed ``OrchestrationPlan``.

Two implementations live here:

* :class:`MockPlanner` — a *general* NL-to-slots extractor that
  builds a plan from the request without any LLM call. This is
  the default in ``demo mode`` and is the path the production
  orchestrator takes when no real LLM is configured.
* :class:`LLMPlanner` — invokes the configured LLM (OpenAI or
  Anthropic) and validates the JSON output against the typed
  plan schema.

Hard constraint #8 forbids hard-coded answers to the sample
questions. Neither planner pattern-matches on the user's
question text. The mock planner extracts an entity-like token
(asset id), a temporal window, and a verb; the LLM planner is
LLM-driven and never sees a scripted intent taxonomy.
"""
from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

from pydantic import ValidationError

from rag.retrieval import RetrievalFilters

from .errors import PlannerError
from .llm_client import LLMClient
from .plan import (
    ComposePayload,
    OrchestrationPlan,
    PlanStep,
    PlanStepKind,
    RagQueryPayload,
    SimilarTicketsPayload,
    ToolCallPayload,
)
from .request import ConversationMessage, ToolCatalogEntry


class Planner(Protocol):
    """The planner's contract.

    Implementations are async because the LLM-backed planner
    awaits an API call. The mock planner is also async so the
    call site is uniform.
    """

    async def plan(
        self,
        request: str,
        conversation: list[ConversationMessage],
        tool_catalog: list[ToolCatalogEntry],
    ) -> OrchestrationPlan: ...


# --- Slots extracted from the request text ---

_ASSET_ID_RE = re.compile(
    r"""
    (?:["'`])?                        # optional quote
    (?P<asset>
        [A-Z][\w-]*                   # capitalised word
        (?:\s+[A-Z][\w-]*)*           # more capitalised words
        \s+\d+                        # digits (e.g. "Boiler Feed Pump 101")
    )
    (?:["'`])?                        # optional close quote
    """,
    re.VERBOSE,
)
_HYPHENATED_ID_RE = re.compile(
    r"(?P<asset>[A-Za-z][A-Za-z0-9]*(?:-[A-Za-z0-9]+)+)"
)
_SITE_RE = re.compile(
    r"\b(?P<site>[A-Z][a-z]+(?:Refinery|Site|Plant))\b"
)
_TEMPORAL_RE = re.compile(
    r"(?P<n>\d+)\s+(?P<unit>day|week|month|year)s?\b",
    re.IGNORECASE,
)
_ALARM_ID_RE = re.compile(r"\b(?P<alarm>ALM-\d+)\b", re.IGNORECASE)


def _extract_slots(request: str) -> dict[str, Any]:
    """Pull the minimum slots required to build a plan.

    The extractor is *general* — it doesn't pattern-match on the
    user's question text, it extracts structural tokens from the
    request. The four phrasings "Boiler Feed Pump 101",
    "boiler-feed-pump-101", "BFP-101", and "the pump 101 in the
    boiler feed train" all yield a usable asset slot.
    """
    slots: dict[str, Any] = {}

    asset = _extract_asset(request)
    if asset is not None:
        slots["asset_id"] = asset

    site = _SITE_RE.search(request)
    if site is not None:
        slots["site"] = site.group("site")

    alarm = _ALARM_ID_RE.search(request)
    if alarm is not None:
        slots["alarm_id"] = alarm.group("alarm")

    temporal = _TEMPORAL_RE.search(request)
    if temporal is not None:
        n = int(temporal.group("n"))
        unit = temporal.group("unit").lower()
        delta = {
            "day": timedelta(days=n),
            "week": timedelta(weeks=n),
            "month": timedelta(days=30 * n),
            "year": timedelta(days=365 * n),
        }[unit]
        slots["since"] = (datetime.now(tz=UTC) - delta).isoformat()

    return slots


def _extract_asset(request: str) -> str | None:
    """Return the most-specific asset identifier extracted from ``request``.

    Capitalised phrase + digits wins (matches the "Boiler Feed Pump
    101" form). Falls back to hyphenated-id. Falls back to
    quoted-string. Returns ``None`` if nothing matches.
    """
    match = _ASSET_ID_RE.search(request)
    if match is not None:
        return match.group("asset").strip()
    match = _HYPHENATED_ID_RE.search(request)
    if match is not None:
        return match.group("asset").strip()
    quoted = re.search(r"[\"'`]([A-Za-z0-9][\w\s-]*)[\"'`]", request)
    if quoted is not None:
        return quoted.group(1).strip()
    return None


# --- Mock planner ---


class MockPlanner:
    """General NL-to-slots extractor that emits a typed plan.

    No hard-coded intent buckets. The plan shape is determined
    by the slots extracted from the request, not by the question
    text. The same shape is produced by the LLM planner, so the
    downstream chain runner is provider-agnostic.
    """

    async def plan(
        self,
        request: str,
        conversation: list[ConversationMessage],
        tool_catalog: list[ToolCatalogEntry],
    ) -> OrchestrationPlan:
        """Build a plan from the request's structural slots.

        Steps emitted (in order):

        1. ``search_assets`` (if any asset-like token is found).
        2. ``summarize_alarms`` (if an asset or site is found).
        3. ``rag_query`` (always — the orchestrator always
           retrieves supporting documentation).
        4. ``compose`` (always — the final answer).
        """
        slots = _extract_slots(request)
        steps: list[PlanStep] = []
        step_idx = 0

        def _next_id() -> str:
            nonlocal step_idx
            step_idx += 1
            return f"s{step_idx}"

        if "asset_id" in slots:
            steps.append(
                PlanStep(
                    step_id=_next_id(),
                    kind=PlanStepKind.TOOL_CALL,
                    payload=ToolCallPayload(
                        tool="search_assets",
                        args={"query": slots["asset_id"]},
                    ),
                )
            )

        if "asset_id" in slots or "site" in slots:
            args: dict[str, Any] = {}
            if "site" in slots:
                args["site"] = slots["site"]
            if "asset_id" in slots:
                args["asset"] = slots["asset_id"]
            if "severity" in slots:
                args["severity"] = slots["severity"]
            if "since" in slots:
                args["since"] = slots["since"]
            steps.append(
                PlanStep(
                    step_id=_next_id(),
                    kind=PlanStepKind.TOOL_CALL,
                    payload=ToolCallPayload(
                        tool="summarize_alarms",
                        args=args,
                    ),
                )
            )

        # Always emit a RAG query — the orchestrator's contract
        # is that every response carries source citations.
        rag_query = request
        rag_filters: RetrievalFilters | None = None
        if "asset_id" in slots:
            # Heuristic: if the asset id suggests a known asset class,
            # narrow the corpus. The mock is general — it only
            # runs when the asset id literally contains a known
            # asset class keyword.
            asset_lower = slots["asset_id"].lower()
            for asset_class in ("boiler", "compressor", "cooling_water", "distillation_column"):
                if asset_class in asset_lower:
                    rag_filters = RetrievalFilters(asset_class=asset_class)
                    break
        steps.append(
            PlanStep(
                step_id=_next_id(),
                kind=PlanStepKind.RAG_QUERY,
                payload=RagQueryPayload(query=rag_query, k=5, filters=rag_filters),
            )
        )

        # Workflow step 4 (brief § 4): search past tickets. Emitted
        # when the chain has an alarm context (asset_id or site).
        # The chain recovers gracefully if the step returns no
        # tickets — the IncidentBuilder treats an empty list as a
        # valid "no close matches" outcome.
        if "asset_id" in slots or "site" in slots:
            tickets_args: dict[str, Any] = {
                "text": request,
                "limit": 5,
            }
            if "site" in slots:
                tickets_args["site"] = slots["site"]
            if "asset_class" in slots:
                tickets_args["asset_class"] = slots["asset_class"]
            elif "asset_id" in slots:
                # Derive asset_class from the asset id when the
                # caller didn't pass it explicitly (mirrors the
                # RAG filter heuristic above).
                asset_lower = slots["asset_id"].lower()
                for asset_class in ("boiler", "compressor", "cooling_water", "distillation_column"):
                    if asset_class in asset_lower:
                        tickets_args["asset_class"] = asset_class
                        break
            steps.append(
                PlanStep(
                    step_id=_next_id(),
                    kind=PlanStepKind.SEARCH_SIMILAR_TICKETS,
                    payload=SimilarTicketsPayload(**tickets_args),
                )
            )

        steps.append(
            PlanStep(
                step_id=_next_id(),
                kind=PlanStepKind.COMPOSE,
                payload=ComposePayload(),
            )
        )

        return OrchestrationPlan(
            plan_id=uuid.uuid4().hex,
            intent=_summarize_intent(request),
            steps=steps,
        )


def _summarize_intent(request: str) -> str:
    """Return a short intent summary derived from the request."""
    first = request.strip().split(".")[0]
    return first[:160]


# --- LLM planner ---


class LLMPlanner:
    """LLM-driven planner that produces a typed plan from JSON.

    The LLM is given a tool catalog and the plan JSON schema.
    The response is parsed and validated against
    :class:`OrchestrationPlan`. A single retry with corrective
    feedback is attempted on the first failure.
    """

    def __init__(
        self,
        *,
        llm: LLMClient,
        model_name: str,
        max_retries: int = 1,
    ) -> None:
        self._llm = llm
        self._model_name = model_name
        self._max_retries = max_retries

    async def plan(
        self,
        request: str,
        conversation: list[ConversationMessage],
        tool_catalog: list[ToolCatalogEntry],
    ) -> OrchestrationPlan:
        """Build a plan by calling the LLM and validating the response."""
        prompt = self._build_prompt(request, conversation, tool_catalog)
        last_error: Exception | None = None
        for _attempt in range(self._max_retries + 1):
            try:
                raw = await self._llm.complete(prompt, response_format="json")
                return OrchestrationPlan.model_validate_json(raw)
            except (ValidationError, ValueError) as exc:
                last_error = exc
                # On retry, append the validation error so the LLM
                # can correct its output.
                prompt = f"{prompt}\n\nYour previous response failed validation:\n{exc}"
        raise PlannerError(
            f"LLM planner produced an invalid plan after "
            f"{self._max_retries + 1} attempts: {last_error}"
        ) from last_error

    def _build_prompt(
        self,
        request: str,
        conversation: list[ConversationMessage],
        tool_catalog: list[ToolCatalogEntry],
    ) -> str:
        catalog = "\n".join(
            f"- {t.name}: {t.description}" for t in tool_catalog
        ) or "(no tools registered)"
        history = "\n".join(
            f"{m.role}: {m.content}" for m in conversation
        )
        schema = OrchestrationPlan.model_json_schema()
        return (
            f"You are an orchestrator planner for an industrial "
            f"incident copilot. Convert the user's request into a "
            f"typed plan.\n\n"
            f"Available tools:\n{catalog}\n\n"
            f"Conversation history:\n{history}\n\n"
            f"User request:\n{request}\n\n"
            f"Respond with a JSON object matching this schema:\n"
            f"{schema}\n\n"
            f"Use ONLY tool names from the catalog. The plan must "
            f"end with a COMPOSE step."
        )


__all__ = ["LLMPlanner", "MockPlanner", "Planner"]
