"""FastAPI routes for the orchestration backend.

Mounted by :func:`apps.backend.create_app`. The ``/chat``
endpoint accepts a typed request envelope, runs the chain,
and returns the response envelope with the answer,
citations, and trace.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from core.exceptions import CopilotError, MCPError, RAGError
from core.logging import bind_context, clear_context, get_logger

from .orchestrator.errors import PlannerError
from .orchestrator.request import ChatRequest, ChatResponse, ConversationMessage

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


__all__ = ["router"]
