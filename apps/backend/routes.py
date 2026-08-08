"""FastAPI routes for the orchestration backend.

Mounted by :func:`apps.backend.create_app`. The ``/chat``
endpoint accepts a typed request envelope, runs the chain,
and returns the response envelope with the answer,
citations, and trace. The ``/tickets/draft`` endpoint accepts
an ``Incident`` payload and returns a ticket draft (or a
persisted ticket, when ``approved=True``).
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, Request

from core.exceptions import CopilotError, MCPError, RAGError
from core.logging import bind_context, clear_context, get_logger

from .orchestrator.errors import PlannerError
from .orchestrator.incident import IncidentContext, build_incident
from .orchestrator.plan import (
    CreateTicketDraftPayload,
    OrchestrationPlan,
    PlanStep,
    PlanStepKind,
)
from .orchestrator.request import (
    ChatRequest,
    ChatResponse,
    ConversationMessage,
    TicketDraftRequest,
    TicketDraftResponse,
)

log = get_logger(__name__)

router = APIRouter()


@router.get("/health")
def health() -> dict[str, str]:
    """Liveness probe — returns 200 if the process is up."""
    return {"status": "ok", "service": "copilot-backend"}


@router.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest, request: Request) -> ChatResponse:
    """Handle a single orchestration request.

    Steps:
    1. Resolve the conversation (existing or new).
    2. Plan the chain.
    3. Run the chain.
    4. Append the user / assistant turns to the conversation.
    5. Return the response envelope.
    """
    bundle = request.app.state.orchestrator
    trace_id = request.headers.get("x-trace-id") or ""
    if trace_id:
        bind_context(trace_id=trace_id)
    try:
        history = bundle.conversation_store.get_or_create(req.conversation_id)
        bind_context(conversation_id=history.id)

        plan = await bundle.planner.plan(
            req.message,
            conversation=list(history.messages),
            tool_catalog=[],
        )
        log.info(
            "plan.generated",
            plan_id=plan.plan_id,
            step_count=len(plan.steps),
            intent=plan.intent,
        )

        result = await bundle.chain.run(plan)

        incident = build_incident(
            IncidentContext(
                intent=result.intent,
                request=req.message,
                plan=plan,
                chain_result=result,
            )
        )

        bundle.conversation_store.append(
            history.id,
            ConversationMessage(role="user", content=req.message),
        )
        bundle.conversation_store.append(
            history.id,
            ConversationMessage(role="assistant", content=result.answer),
        )

        return ChatResponse(
            conversation_id=history.id,
            answer=result.answer,
            citations=result.citations,
            trace=result.trace,
            rag_confidence=result.rag_confidence,
            dropped_count=result.dropped_count,
            intent=result.intent,
            incident=incident,
            raw_payload={
                "plan_id": plan.plan_id,
                "step_count": len(plan.steps),
            },
        )
    except PlannerError as exc:
        log.warning("plan.failed", error=str(exc))
        raise HTTPException(status_code=422, detail={"code": "planner_error", "message": str(exc)}) from exc
    except MCPError as exc:
        log.warning("mcp.failed", error=str(exc))
        raise HTTPException(status_code=502, detail={"code": "mcp_error", "message": str(exc)}) from exc
    except RAGError as exc:
        log.warning("rag.failed", error=str(exc))
        raise HTTPException(status_code=502, detail={"code": "rag_error", "message": str(exc)}) from exc
    except CopilotError as exc:
        log.warning("orchestrator.failed", error=str(exc))
        raise HTTPException(status_code=500, detail={"code": "orchestrator_error", "message": str(exc)}) from exc
    finally:
        clear_context()


@router.post("/tickets/draft", response_model=TicketDraftResponse)
async def ticket_draft(req: TicketDraftRequest, request: Request) -> TicketDraftResponse:
    """Generate a ticket draft from an incident payload.

    Builds a one-step ``OrchestrationPlan`` with a single
    ``CREATE_TICKET_DRAFT`` step and runs it through the chain.
    The orchestrator's chain runner routes the step to the
    ticketing MCP server's ``create_ticket_draft`` tool. The
    response carries the ticket-mock's draft (preview mode
    when ``approved=False``, persisted ticket id when ``True``).

    The endpoint also appends a ``user``/``assistant`` turn pair
    to the conversation for the audit trail. The ``assistant``
    turn records the draft text + the ticket id (or the preview
    flag) so the conversation history mirrors the chain's
    output.
    """
    bundle = request.app.state.orchestrator
    trace_id = request.headers.get("x-trace-id") or ""
    if trace_id:
        bind_context(trace_id=trace_id)
    try:
        history = bundle.conversation_store.get_or_create(None)
        bind_context(conversation_id=history.id)

        intent = str(req.incident.get("title") or "ticket draft")
        plan = OrchestrationPlan(
            plan_id=uuid.uuid4().hex,
            intent=intent,
            steps=[
                PlanStep(
                    step_id="t1",
                    kind=PlanStepKind.CREATE_TICKET_DRAFT,
                    payload=CreateTicketDraftPayload(
                        incident=req.incident,
                        approved=req.approved,
                    ),
                ),
            ],
        )
        log.info(
            "ticket_draft.plan",
            plan_id=plan.plan_id,
            approved=req.approved,
        )

        result = await bundle.chain.run(plan)

        # The chain captured the ticket-mock's response in
        # ``prior_outputs["t1"]``. The response shape is
        # {title, body, severity, assignee, labels, ticket_id, preview}.
        draft = result.prior_outputs.get("t1") or {}
        if not isinstance(draft, dict):
            raise HTTPException(
                status_code=502,
                detail={"code": "ticket_draft_failed", "message": "No ticket draft returned"},
            )

        bundle.conversation_store.append(
            history.id,
            ConversationMessage(role="user", content=f"draft ticket: {intent}"),
        )
        bundle.conversation_store.append(
            history.id,
            ConversationMessage(
                role="assistant",
                content=(
                    f"ticket_id={draft.get('ticket_id')} preview={draft.get('preview')}"
                ),
            ),
        )

        return TicketDraftResponse(
            conversation_id=history.id,
            title=str(draft.get("title") or ""),
            body=str(draft.get("body") or ""),
            severity=str(draft.get("severity") or "medium"),
            assignee=draft.get("assignee"),
            labels=list(draft.get("labels") or []),
            ticket_id=draft.get("ticket_id"),
            preview=bool(draft.get("preview", True)),
            trace=result.trace,
        )
    except MCPError as exc:
        log.warning("ticket_mcp.failed", error=str(exc))
        raise HTTPException(status_code=502, detail={"code": "ticket_mcp_error", "message": str(exc)}) from exc
    except CopilotError as exc:
        log.warning("ticket_draft.failed", error=str(exc))
        raise HTTPException(status_code=500, detail={"code": "orchestrator_error", "message": str(exc)}) from exc
    finally:
        clear_context()


__all__ = ["router"]
