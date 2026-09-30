"""Dependency wiring for the orchestrator.

The wiring layer centralises the construction of the
:class:`ChainRunner`, MCP clients, RAG service, conversation
store, and planner. The FastAPI app factory calls
:func:`build_orchestrator` exactly once at startup and
attaches the result to ``app.state``.

Why a wiring module
-------------------

* The same dependency graph is used by the FastAPI app and
  the integration tests. Tests build the chain with
  mocks; the app uses the real wiring.
* The factory is the boundary against which the
  orchestrator's "no direct httpx to alarm-api" invariant
  is enforceable. ``MCPClient`` is the only allowed path.

Feature 6.1 adds a second ``MCPClient`` for the ticketing
server. The chain runner routes ``CREATE_TICKET_DRAFT`` steps
to this client and the rest to the alarm-management client.
Construction is identical to the alarm client — just a
different base URL.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from core.config import Settings, get_settings
from core.exceptions import LLMError
from core.logging import get_logger

from .orchestrator.chain import ChainRunner
from .orchestrator.conversation import ConversationStore
from .orchestrator.llm_client import LLMClient, build_llm_client
from .orchestrator.mcp_client import MCPClient
from .orchestrator.planner import LLMPlanner, MockPlanner, Planner
from .orchestrator.rag_step import RagStepExecutor

log = get_logger(__name__)


@dataclass(frozen=True)
class OrchestratorBundle:
    """The orchestrator's runtime dependencies."""

    chain: ChainRunner
    planner: Planner
    conversation_store: ConversationStore
    mcp: MCPClient
    rag: RagStepExecutor
    ticket_mcp: MCPClient | None = None


def build_orchestrator(
    *,
    settings: Settings | None = None,
    index_path: Path | None = None,
    llm: LLMClient | None = None,
    mcp: MCPClient | None = None,
    ticket_mcp: MCPClient | None = None,
) -> OrchestratorBundle:
    """Build the orchestrator's runtime dependencies.

    Parameters
    ----------
    settings:
        Override the singleton settings. Tests pass a real
        instance. Production leaves it ``None`` and accepts
        the cached settings.
    index_path:
        Override the persisted RAG index path. Defaults to
        ``settings.index_path``.
    llm:
        Override the LLM client. Defaults to the configured
        provider (``llm_provider`` / ``llm_model``).
    mcp:
        Override the alarm-management MCP client. Defaults
        to the configured ``mcp_server_url``.
    ticket_mcp:
        Override the ticketing MCP client. Defaults to the
        configured ``ticketing_mcp_url``. When ``None``, the
        chain runner emits a ``TraceStep(outcome="error")``
        for ``CREATE_TICKET_DRAFT`` steps.
    """
    if settings is None:
        settings = get_settings()

    if mcp is None:
        mcp = MCPClient(base_url=settings.mcp_server_url)

    if ticket_mcp is None:
        ticket_mcp = MCPClient(base_url=settings.ticketing_mcp_url)

    if llm is None:
        llm = build_llm_client(
            provider=settings.llm_provider,
            api_key=settings.llm_api_key.get_secret_value(),
            model=settings.llm_model,
        )

    if settings.planner_provider == "llm":
        planner: Planner = LLMPlanner(llm=llm, model_name=settings.llm_model)
    else:
        planner = MockPlanner()

    if index_path is None:
        index_path = Path(settings.index_path)

    rag = _build_rag(index_path=index_path, settings=settings)

    chain = ChainRunner(mcp=mcp, rag=rag, ticket_mcp=ticket_mcp)
    store = ConversationStore()

    log.info(
        "orchestrator.built",
        mcp_server=settings.mcp_server_url,
        ticket_mcp_server=settings.ticketing_mcp_url,
        llm_provider=settings.llm_provider,
        planner_provider=settings.planner_provider,
        index_path=str(index_path),
    )

    return OrchestratorBundle(
        chain=chain,
        planner=planner,
        conversation_store=store,
        mcp=mcp,
        rag=rag,
        ticket_mcp=ticket_mcp,
    )


def _build_rag(*, index_path: Path, settings: Settings) -> RagStepExecutor:
    """Build the RAG step executor from the persisted index.

    The retrieval service is constructed with the embedder
    selected by ``settings.embedder_backend``. The default is
    ``deterministic`` so the demo path is hermetic and instant;
    production flips the env var to ``sentence-transformers``
    and re-ingests with the matching ``--embedder`` flag.

    The embedder's ``model_name`` must match the
    ``IndexMetadata.embedder_name`` written by the pipeline at
    ingestion time. A mismatch raises explicitly so the operator
    does not silently retrieve nonsense (closed-out limitation
    #7 in ``docs/known-limitations.md``).
    """
    from rag.ingestion import (
        DeterministicEmbeddingModel,
        InMemoryVectorIndex,
        SentenceTransformerEmbeddingModel,
    )
    from rag.retrieval import RetrievalService

    if not index_path.exists():
        raise LLMError(
            f"Persisted RAG index not found at {index_path}. "
            "Run `make ingest` to build it."
        )
    index = InMemoryVectorIndex.load(index_path)

    if settings.embedder_backend == "sentence-transformers":
        embedder: DeterministicEmbeddingModel | SentenceTransformerEmbeddingModel = (
            SentenceTransformerEmbeddingModel(dimension=index.metadata.dimension)
        )
    else:
        embedder = DeterministicEmbeddingModel(dimension=index.metadata.dimension)

    # Guard against the historic footgun: a query embedder that
    # was not the one that built the index produces cosine
    # scores that look plausible but mean nothing. Refuse early.
    if embedder.model_name != index.metadata.embedder_name:
        raise LLMError(
            f"Embedder mismatch: index was built with "
            f"{index.metadata.embedder_name!r} but the configured "
            f"embedder is {embedder.model_name!r}. Re-ingest with "
            f"`python -m rag.ingestion --embedder "
            f"{settings.embedder_backend}` or set "
            f"EMBEDDER_BACKEND to match the index."
        )

    service = RetrievalService(index=index, embedder=embedder)
    return RagStepExecutor(service=service)


__all__ = ["OrchestratorBundle", "build_orchestrator"]
