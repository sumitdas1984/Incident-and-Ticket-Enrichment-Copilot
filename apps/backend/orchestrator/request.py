"""HTTP request / response envelope for the orchestration endpoint.

The shapes are Pydantic-typed and ``frozen=True`` so the
response envelope is trivially serialisable. FastAPI uses these
types directly via ``response_model=ChatResponse``.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from core.domain import Citation, Incident, TraceStep


class ConversationMessage(BaseModel):
    """One turn in the conversation history."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    role: str  # "user" | "assistant" | "system"
    content: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class ToolCatalogEntry(BaseModel):
    """One entry in the tool catalog the planner sees.

    Captures the minimum the planner needs: the tool's name and
    a one-line description. The full ``input_schema`` is held by
    the MCP client but not exposed to the planner (the schema is
    too verbose for the LLM's prompt).
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str
    description: str


class ChatRequest(BaseModel):
    """The HTTP request body for ``POST /chat``.

    Attributes
    ----------
    conversation_id:
        Optional. Omit (or send ``None``) to start a new
        conversation; the response carries the generated id.
    message:
        The natural-language user request.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    conversation_id: str | None = None
    message: str


class ChatResponse(BaseModel):
    """The HTTP response body for ``POST /chat``.

    Carries the LLM-generated answer, the MCP execution trace,
    the RAG citations, and the conversation id. The trace is
    a list of typed rows so the GUI can render it as a table.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    conversation_id: str
    answer: str
    citations: list[Citation] = Field(default_factory=list)
    trace: list[TraceStep] = Field(default_factory=list)
    rag_confidence: str = "none"
    dropped_count: int = 0
    intent: str = ""
    raw_payload: dict[str, Any] = Field(default_factory=dict)
    incident: Incident | None = None


class TicketDraftRequest(BaseModel):
    """The HTTP request body for ``POST /tickets/draft``.

    Carries the structured ``Incident`` payload (the same shape
    returned by ``/chat`` in the ``incident`` field) and the
    explicit-user-confirmation flag. When ``approved=True`` the
    ticket-mock persists the ticket and the response carries
    the assigned ``ticket_id``. When ``False`` the response is
    a preview draft with ``preview=true`` and no ``ticket_id``.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    incident: dict[str, Any]
    approved: bool = False


class TicketDraftResponse(BaseModel):
    """The HTTP response body for ``POST /tickets/draft``.

    Mirrors the ticket-mock's :class:`TicketDraftResponse` shape
    so the wire envelope never has to widen. The
    ``conversation_id`` is the orchestrator's id for this turn
    (audit trail).
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    conversation_id: str
    title: str
    body: str
    severity: str
    assignee: str | None = None
    labels: list[str] = Field(default_factory=list)
    ticket_id: str | None = None
    preview: bool = True
    trace: list[TraceStep] = Field(default_factory=list)


__all__ = [
    "ChatRequest",
    "ChatResponse",
    "ConversationMessage",
    "TicketDraftRequest",
    "TicketDraftResponse",
    "ToolCatalogEntry",
]
