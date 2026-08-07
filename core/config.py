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

    # --- Vector store (Epic 4) ---
    vector_store_url: str = "http://localhost:8002"
    vector_store_port: int = 8002
    document_path: str = "./rag/documents"

    # --- Ticketing (Epic 6) ---
    ticketing_api_url: str = "http://localhost:8003"
    ticketing_api_port: int = 8003

    # --- App ---
    backend_port: int = 8000
    frontend_port: int = 5173
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Singleton accessor. Tests can call get_settings.cache_clear()."""
    return Settings()
