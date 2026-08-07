"""Copilot orchestrator (Feature 5.1).

Package layout:

* :mod:`.request` — HTTP envelope typed models.
* :mod:`.plan` — typed plan schema with discriminator payloads.
* :mod:`.planner` — Planner protocol, MockPlanner, LLMPlanner.
* :mod:`.mcp_client` — facade over the MCP Streamable HTTP transport.
* :mod:`.chain` — ChainRunner that executes a plan against the MCP
  client and RAG service.
* :mod:`.rag_step` — RAG step executor (Feature 4.2 wiring).
* :mod:`.llm_client` — LLMClient protocol + adapters.
* :mod:`.conversation` — in-memory conversation store.
* :mod:`.citations` — adapter between ``rag.retrieval.Citation`` and
  ``core.domain.Citation``.
* :mod:`.answer` — final-answer composer.
* :mod:`.errors` — orchestration-specific exceptions.

Public re-exports expose the orchestrator's facade only. The
internal modules are organized so each one can be unit-tested
without a running MCP server or LLM client.
"""
from __future__ import annotations

from .chain import ChainResult, ChainRunner
from .citations import to_domain_citation
from .conversation import ConversationHistory, ConversationMessage, ConversationStore
from .errors import ChainError, PlannerError
from .errors import LLMError as OrchestratorLLMError
from .llm_client import LLMClient, MockLLMClient
from .mcp_client import MCPClient, ToolCatalogEntry
from .plan import (
    ComposePayload,
    OrchestrationPlan,
    PlanStep,
    PlanStepKind,
    RagQueryPayload,
    ToolCallPayload,
)
from .planner import LLMPlanner, MockPlanner, Planner
from .rag_step import RagStepExecutor
from .request import ChatRequest, ChatResponse

__all__ = [
    # Chain
    "ChainResult",
    "ChainRunner",
    # Citations
    "to_domain_citation",
    # Conversation
    "ConversationHistory",
    "ConversationMessage",
    "ConversationStore",
    # Errors
    "ChainError",
    "OrchestratorLLMError",
    "PlannerError",
    # LLM
    "LLMClient",
    "MockLLMClient",
    # MCP
    "MCPClient",
    "ToolCatalogEntry",
    # Plan
    "ComposePayload",
    "OrchestrationPlan",
    "PlanStep",
    "PlanStepKind",
    "RagQueryPayload",
    "ToolCallPayload",
    # Planner
    "LLMPlanner",
    "MockPlanner",
    "Planner",
    # RAG
    "RagStepExecutor",
    # Request / response
    "ChatRequest",
    "ChatResponse",
]
