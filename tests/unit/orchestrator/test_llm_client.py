"""Unit tests for the LLM client and factory."""
from __future__ import annotations

import asyncio

import pytest

from apps.backend.orchestrator.llm_client import (
    AnthropicLLMClient,
    MockLLMClient,
    OpenAILLMClient,
    build_llm_client,
)
from core.exceptions import LLMError


def test_mock_llm_returns_canned_json() -> None:
    async def runner() -> None:
        client = MockLLMClient()
        out = await client.complete("hello", response_format="json")
        assert "plan_id" in out
        assert "steps" in out

    asyncio.run(runner())


def test_mock_llm_returns_prose_for_text_format() -> None:
    async def runner() -> None:
        client = MockLLMClient()
        out = await client.complete("hello", response_format="text")
        assert "mock" in out.lower()

    asyncio.run(runner())


def test_build_llm_client_returns_mock_for_mock_provider() -> None:
    client = build_llm_client(provider="mock", api_key=None, model="x")
    assert isinstance(client, MockLLMClient)


def test_build_llm_client_raises_without_api_key_for_openai() -> None:
    with pytest.raises(LLMError, match="no LLM_API_KEY"):
        build_llm_client(provider="openai", api_key=None, model="x")


def test_build_llm_client_returns_openai_with_key() -> None:
    client = build_llm_client(provider="openai", api_key="sk-test", model="gpt-4o-mini")
    assert isinstance(client, OpenAILLMClient)


def test_build_llm_client_returns_anthropic_with_key() -> None:
    client = build_llm_client(provider="anthropic", api_key="sk-ant-test", model="claude-haiku-4-5")
    assert isinstance(client, AnthropicLLMClient)


def test_build_llm_client_rejects_unknown_provider() -> None:
    with pytest.raises(LLMError, match="Unknown LLM provider"):
        build_llm_client(provider="google", api_key=None, model="x")
