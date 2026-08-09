"""Orchestrator-specific exceptions.

The orchestrator raises :class:`CopilotError` subclasses so the
FastAPI exception handler can map them all to a single wire
envelope. The specific types here distinguish between planner
failures (the LLM produced a malformed plan), chain failures
(tool calls failed mid-execution), and LLM failures (the LLM
provider returned an error or unparseable response).
"""
from __future__ import annotations

from core.exceptions import CopilotError, LLMError


class PlannerError(CopilotError):
    """The planner could not produce a valid plan.

    Covers the LLM returning malformed JSON, the JSON schema
    validator rejecting the plan, or the mock planner failing
    to extract the minimum slots required to build a plan.
    """


class ChainError(CopilotError):
    """The chain runner could not execute a plan.

    A single tool failure mid-chain is *not* a ChainError — it
    is recorded as ``TraceStep(outcome="error")`` and the chain
    continues. This exception is reserved for permanent failures
    (the MCP server is unreachable, the RAG service is broken,
    the plan itself is malformed).
    """


# Re-exported under an alias so the orchestrator's public surface
# names it without colliding with ``from core.exceptions import
# LLMError`` at the call site.
__all__ = ["ChainError", "LLMError", "PlannerError"]
