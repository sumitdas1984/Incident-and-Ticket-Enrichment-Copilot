"""LLM client — protocol + adapters.

The orchestrator's planner calls :class:`LLMClient.complete`
with a prompt and a response-format hint. Concrete adapters:

* :class:`MockLLMClient` — returns canned JSON. Default for
  demo mode and tests.
* :class:`OpenAILLMClient` — uses the OpenAI Chat Completions
  API with ``response_format={"type":"json_object"}`` when
  the caller asks for JSON.
* :class:`AnthropicLLMClient` — uses the Anthropic Messages
  API with JSON delimiters in the prompt.

The LLM client is *not* the path the orchestrator's answers
take — the orchestrator's final answer is composed from the
chain's outputs (MCP tools + RAG), not from an LLM call.
The LLM is only used to plan the chain.
"""
from __future__ import annotations

import json
from typing import Any, Literal, Protocol

import httpx

from core.exceptions import LLMError


class LLMClient(Protocol):
    """The LLM client surface."""

    async def complete(
        self,
        prompt: str,
        *,
        response_format: Literal["json", "text"] = "text",
    ) -> str: ...


class MockLLMClient:
    """Return canned JSON for the demo path.

    The mock emits a minimal one-step plan so the rest of the
    orchestrator can be exercised. Real planning flows through
    :class:`MockPlanner` (the general NL-to-slots extractor),
    not the LLM client.
    """

    async def complete(
        self,
        prompt: str,
        *,
        response_format: Literal["json", "text"] = "text",
    ) -> str:
        """Return a canned plan JSON.

        The plan emits a single RAG query + compose step. The
        chain runner consumes it the same way it consumes an
        LLM-generated plan.
        """
        if response_format != "json":
            return "I'm a mock LLM. Configure `llm_provider=openai` or `anthropic` for real responses."
        return json.dumps(
            {
                "plan_id": "mock-plan-1",
                "intent": "mock response",
                "steps": [
                    {
                        "step_id": "s1",
                        "kind": "rag_query",
                        "payload": {
                            "kind": "rag_query",
                            "query": prompt.split("User request:")[-1].strip()[:200],
                            "k": 5,
                        },
                    },
                    {
                        "step_id": "s2",
                        "kind": "compose",
                        "payload": {
                            "kind": "compose",
                            "template": "answer_with_citations",
                        },
                    },
                ],
            }
        )


class OpenAILLMClient:
    """OpenAI Chat Completions adapter.

    Requires ``OPENAI_API_KEY`` in the environment. The client
    is built on ``httpx.AsyncClient`` so the orchestrator can
    share the same connection pool with the MCP client.
    """

    def __init__(
        self,
        *,
        api_key: str,
        model: str = "gpt-4o-mini",
        base_url: str = "https://api.openai.com/v1",
        timeout_s: float = 30.0,
    ) -> None:
        self._api_key = api_key
        self._model = model
        self._base_url = base_url.rstrip("/")
        self._client = httpx.AsyncClient(timeout=timeout_s)

    async def complete(
        self,
        prompt: str,
        *,
        response_format: Literal["json", "text"] = "text",
    ) -> str:
        body: dict[str, Any] = {
            "model": self._model,
            "messages": [{"role": "user", "content": prompt}],
        }
        if response_format == "json":
            body["response_format"] = {"type": "json_object"}
        try:
            response = await self._client.post(
                f"{self._base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                },
                json=body,
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise LLMError(f"OpenAI request failed: {exc}") from exc
        payload = response.json()
        try:
            return str(payload["choices"][0]["message"]["content"])
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMError(f"OpenAI returned unexpected payload: {exc}") from exc

    async def aclose(self) -> None:
        await self._client.aclose()


class AnthropicLLMClient:
    """Anthropic Messages API adapter.

    Requires ``ANTHROPIC_API_KEY`` in the environment. JSON
    output is enforced by wrapping the prompt in delimiters
    and parsing the response's first JSON object.
    """

    def __init__(
        self,
        *,
        api_key: str,
        model: str = "claude-haiku-4-5",
        base_url: str = "https://api.anthropic.com/v1",
        timeout_s: float = 30.0,
    ) -> None:
        self._api_key = api_key
        self._model = model
        self._base_url = base_url.rstrip("/")
        self._client = httpx.AsyncClient(timeout=timeout_s)

    async def complete(
        self,
        prompt: str,
        *,
        response_format: Literal["json", "text"] = "text",
    ) -> str:
        from core.logging import bind_context

        bind_context(llm_provider="anthropic", llm_model=self._model)
        maybe_delimited = (
            f"{prompt}\n\nRespond with a single JSON object. No prose."
            if response_format == "json"
            else prompt
        )
        try:
            response = await self._client.post(
                f"{self._base_url}/messages",
                headers={
                    "x-api-key": self._api_key,
                    "anthropic-version": "2023-06-01",
                    "Content-Type": "application/json",
                },
                json={
                    "model": self._model,
                    "max_tokens": 4096,
                    "messages": [{"role": "user", "content": maybe_delimited}],
                },
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise LLMError(f"Anthropic request failed: {exc}") from exc
        payload = response.json()
        try:
            content_blocks = payload["content"]
            text = next(b["text"] for b in content_blocks if b.get("type") == "text")
        except (KeyError, StopIteration, TypeError) as exc:
            raise LLMError(f"Anthropic returned unexpected payload: {exc}") from exc
        if response_format == "json":
            # Strip any prose the model might have added before
            # the JSON object.
            start = text.find("{")
            end = text.rfind("}")
            if start == -1 or end == -1 or end <= start:
                raise LLMError("Anthropic response did not contain a JSON object")
            return text[start : end + 1]
        return text

    async def aclose(self) -> None:
        await self._client.aclose()


def build_llm_client(
    *,
    provider: str,
    api_key: str | None,
    model: str,
) -> LLMClient:
    """Factory — picks the configured LLMClient implementation."""
    if provider == "mock":
        return MockLLMClient()
    if provider == "openai":
        if not api_key:
            raise LLMError("OpenAI provider selected but no LLM_API_KEY configured")
        return OpenAILLMClient(api_key=api_key, model=model)
    if provider == "anthropic":
        if not api_key:
            raise LLMError("Anthropic provider selected but no LLM_API_KEY configured")
        return AnthropicLLMClient(api_key=api_key, model=model)
    raise LLMError(f"Unknown LLM provider: {provider!r}")


__all__ = [
    "AnthropicLLMClient",
    "LLMClient",
    "MockLLMClient",
    "OpenAILLMClient",
    "build_llm_client",
]
