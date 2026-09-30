"""Centralised, env-driven configuration.

No code outside this module should call os.getenv. Every other package
imports get_settings() and reads typed fields.
"""
from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- Alarm API (Epic 2 + 3) ---
    alarm_api_base_url: str = "http://localhost:8000"
    alarm_api_token: SecretStr = SecretStr("replace-me")
    alarm_api_port: int = 8000
    # Per-request timeout (connect/read/write/pool). Feature 3.3 surfaces
    # this on Settings so an operator can tune tail latency without code
    # changes.
    alarm_api_timeout_s: float = 5.0
    # Retry policy (Feature 3.3 — Story 3.3.1). Defaults: 3 attempts
    # (initial + 2 retries) with exponential back-off from 0.25 s
    # capped at 2.0 s and ±10 % jitter.
    alarm_api_max_attempts: int = 3
    alarm_api_initial_backoff_s: float = 0.25
    alarm_api_max_backoff_s: float = 2.0

    # --- MCP server (Epic 3) ---
    mcp_server_url: str = "http://localhost:9000"
    mcp_server_port: int = 9000

    # --- LLM (Epic 5) ---
    llm_provider: Literal["openai", "anthropic", "mock"] = "mock"
    llm_api_key: SecretStr = SecretStr("replace-me")
    # Model name passed to the configured provider. OpenAI default is
    # the cheapest capable model; Anthropic default is Claude Haiku.
    llm_model: str = "gpt-4o-mini"
    # Planner provider (Story 5.1.1). The "mock" planner is a
    # general NL-to-slots extractor that produces the same plan
    # shape as the LLM-driven planner; useful for the demo path
    # without an API key. The "llm" planner invokes the configured
    # LLM provider.
    planner_provider: Literal["mock", "llm"] = "mock"
    # Embedder backend used by the orchestrator at query time.
    # Must match the embedder that built ``index_path`` — the
    # ``_build_rag`` wiring raises on mismatch (see
    # ``docs/known-limitations.md`` § 7).
    embedder_backend: Literal["deterministic", "sentence-transformers"] = (
        "deterministic"
    )
    # Path to the persisted RAG index (Feature 4.1 artefact).
    index_path: str = "./var/index/v1.pkl"

    # --- Vector store (Epic 4) ---
    vector_store_url: str = "http://localhost:8002"
    vector_store_port: int = 8002
    document_path: str = "./rag/documents"

    # --- Ticketing (Epic 6) ---
    ticketing_api_url: str = "http://localhost:8003"
    ticketing_api_port: int = 8003
    ticketing_api_token: SecretStr = SecretStr("replace-me")
    ticketing_mcp_url: str = "http://localhost:9001"
    ticketing_mcp_port: int = 9001
    # Identity stamped on every approved ticket creation (Feature 6.2).
    # The brief's hard constraint #3 ("ticket / issue creation is a
    # write operation; it must require explicit user confirmation in
    # the GUI") is enforced at the ticket-mock service; the
    # ``APPROVAL_USER`` env var is the audit-trail attribution. Epic
    # 7 will derive this from the auth subject instead.
    approval_user: str = "operator"

    # --- App ---
    backend_port: int = 8000
    frontend_port: int = 5173
    # The copilot-backend URL the Streamlit GUI POSTs /chat to. The
    # default targets a local dev backend; the docker-compose
    # ``frontend`` service overrides this to ``http://copilot-backend:8000``
    # so the in-container Streamlit reaches the backend over the
    # compose network. No URL is hard-coded in any other module — this
    # is the only place this value is read (Feature 7.1, Story 7.1.2).
    copilot_backend_url: str = "http://localhost:8000"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Singleton accessor. Tests can call get_settings.cache_clear()."""
    return Settings()
