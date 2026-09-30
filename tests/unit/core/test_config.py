"""Tests for core.config.Settings."""
from __future__ import annotations

import pytest

from core.config import Settings, get_settings


def test_settings_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    """Without any env vars, Settings returns the documented defaults."""
    # Strip every env var pydantic-settings reads so this test
    # is not affected by the operator's local ``.env``.
    for key in [
        "ALARM_API_BASE_URL",
        "ALARM_API_PORT",
        "MCP_SERVER_URL",
        "MCP_SERVER_PORT",
        "LLM_PROVIDER",
        "LLM_API_KEY",
        "LLM_MODEL",
        "PLANNER_PROVIDER",
        "EMBEDDER_BACKEND",
        "INDEX_PATH",
        "VECTOR_STORE_URL",
        "VECTOR_STORE_PORT",
        "DOCUMENT_PATH",
        "TICKETING_API_URL",
        "TICKETING_API_PORT",
        "TICKETING_MCP_URL",
        "TICKETING_MCP_PORT",
        "APPROVAL_USER",
        "BACKEND_PORT",
        "FRONTEND_PORT",
        "COPILOT_BACKEND_URL",
        "LOG_LEVEL",
    ]:
        monkeypatch.delenv(key, raising=False)
    s = Settings(_env_file=None)
    assert s.alarm_api_base_url == "http://localhost:8000"
    assert s.alarm_api_port == 8000
    assert s.mcp_server_url == "http://localhost:9000"
    assert s.llm_provider == "mock"
    assert s.embedder_backend == "deterministic"
    assert s.log_level == "INFO"
    # Feature 7.1 — the GUI's default backend URL.
    assert s.copilot_backend_url == "http://localhost:8000"
    assert s.frontend_port == 5173


def test_copilot_backend_url_env_override(monkeypatch: object) -> None:
    """``COPILOT_BACKEND_URL`` overrides the default (Feature 7.1)."""
    monkeypatch.setenv("COPILOT_BACKEND_URL", "https://prod-copilot.example.com")
    s = Settings()
    assert s.copilot_backend_url == "https://prod-copilot.example.com"


def test_settings_env_override(monkeypatch: object) -> None:
    """Env vars override defaults."""
    monkeypatch.setenv("ALARM_API_BASE_URL", "https://prod-alarm.example.com")
    monkeypatch.setenv("LLM_PROVIDER", "anthropic")
    s = Settings()
    assert s.alarm_api_base_url == "https://prod-alarm.example.com"
    assert s.llm_provider == "anthropic"


def test_settings_secret_does_not_leak(monkeypatch: object) -> None:
    """SecretStr fields never appear in plain text in repr/str."""
    monkeypatch.setenv("ALARM_API_TOKEN", "super-secret-token")
    s = Settings()
    text = repr(s) + str(s.alarm_api_token)
    assert "super-secret-token" not in text
    # The actual value is accessible via get_secret_value() for code that needs it.
    assert s.alarm_api_token.get_secret_value() == "super-secret-token"


def test_get_settings_is_singleton() -> None:
    """get_settings returns the same instance until cache_clear()."""
    get_settings.cache_clear()
    a = get_settings()
    b = get_settings()
    assert a is b
    get_settings.cache_clear()


def test_settings_extra_keys_are_ignored() -> None:
    """Unknown env vars don't raise (extra='ignore')."""
    import os

    os.environ["COMPLETELY_UNRELATED"] = "x"
    try:
        s = Settings()
        assert s.alarm_api_base_url == "http://localhost:8000"
    finally:
        del os.environ["COMPLETELY_UNRELATED"]
