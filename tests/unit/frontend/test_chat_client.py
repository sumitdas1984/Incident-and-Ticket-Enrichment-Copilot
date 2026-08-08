"""Unit tests for ``apps.frontend.chat_client``.

The client is a thin httpx wrapper around ``POST /chat``. We
exercise it against ``httpx.MockTransport`` so we never touch
the network — the transport handler captures the request and
returns a pre-canned response. This is cleaner than the older
``fastapi.testclient.TestClient`` pattern for a unit test because:

* The transport sees exactly the bytes httpx would send on the
  wire — no FastAPI/Pydantic re-marshalling in between.
* We can assert directly on the request body, headers, and URL.
* No port juggling; ``base_url`` is irrelevant to the transport.

These tests verify Story 7.1.2 acceptance criteria:

* Frontend reads backend URL from settings (no hard-coded URL).
* ``POST /chat`` is invoked with the documented body shape.
* ``x-trace-id`` header round-trips so the backend's log
  correlation works.
* HTTP and transport failures surface as a stable ``ChatError``
  the UI can render.
"""
from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import httpx
import pytest

from apps.frontend.chat_client import ChatClient, ChatError, ChatResponse
from core.config import get_settings

# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


HandlerFn = Callable[[httpx.Request], httpx.Response]


def _make_client(handler: HandlerFn, *, base_url: str = "http://stub") -> tuple[ChatClient, list[httpx.Request]]:
    """Build a :class:`ChatClient` whose httpx transport is replaced
    by ``handler``. Returns the client and a list that captures every
    request the client sends (in order)."""
    seen: list[httpx.Request] = []

    def capturing(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return handler(request)

    transport = httpx.MockTransport(capturing)
    # Build the client with the swapped transport via the internal
    # httpx.Client constructor; we keep the ChatClient's URL-handling
    # behaviour by passing ``base_url`` through.
    client = ChatClient(base_url=base_url)
    # Replace the httpx.Client's transport.
    client._client = httpx.Client(  # type: ignore[attr-defined]
        transport=transport,
        timeout=client._timeout_s,  # type: ignore[attr-defined]
    )
    return client, seen


def _json_response(payload: dict[str, Any], *, status_code: int = 200) -> httpx.Response:
    return httpx.Response(
        status_code=status_code,
        content=json.dumps(payload).encode("utf-8"),
        headers={"content-type": "application/json"},
    )


def _envelope_error_response(*, code: str, message: str, status_code: int) -> httpx.Response:
    return httpx.Response(
        status_code=status_code,
        content=json.dumps({"detail": {"code": code, "message": message}}).encode("utf-8"),
        headers={"content-type": "application/json"},
    )


_FULL_ENVELOPE: dict[str, Any] = {
    "conversation_id": "conv-abc",
    "answer": "Investigated boiler B-101; no leaks found.",
    "citations": [
        {
            "doc_id": "boiler-tube-leak-troubleshooting",
            "section": "Initial assessment",
            "page": 1,
            "score": 0.91,
            "excerpt": "Inspect the lower tube sheet…",
        },
    ],
    "trace": [
        {
            "server": "alarm-management",
            "tool": "list_alarms",
            "args": {"asset_id": "boiler-b-101"},
            "output": {"items": []},
            "duration_ms": 42,
            "outcome": "success",
            "error": None,
            "retry_count": 0,
            "api_status_code": 200,
        },
    ],
    "rag_confidence": "high",
    "dropped_count": 0,
    "intent": "investigate_recurring_alarms",
    "raw_payload": {"plan_id": "p-1", "step_count": 2},
    "incident": {
        "id": "INC-9001",
        "title": "Boiler B-101 tube leak suspect",
        "summary": "Recurring high-temp alarms; inspect tube sheet.",
        "severity": "critical",
        "likely_cause": "Tube sheet leak",
        "recommended_actions": ["Inspect tube sheet"],
        "citations": [],
        "similar_tickets": ["TKT-1042"],
        "created_at": "2026-08-08T10:00:00Z",
    },
}


# --------------------------------------------------------------------------- #
# Happy path
# --------------------------------------------------------------------------- #


def test_send_happy_path() -> None:
    """200 + valid envelope → returned as a typed ``ChatResponse``."""
    client, seen = _make_client(lambda _req: _json_response(_FULL_ENVELOPE))
    try:
        response = client.send(message="Investigate boiler B-101", conversation_id=None)
    finally:
        client.close()

    assert isinstance(response, ChatResponse)
    assert response.conversation_id == "conv-abc"
    assert "Investigated boiler B-101" in response.answer
    assert len(response.citations) == 1
    assert response.citations[0]["doc_id"] == "boiler-tube-leak-troubleshooting"
    assert len(response.trace) == 1
    assert response.trace[0]["tool"] == "list_alarms"
    assert response.rag_confidence == "high"
    assert response.intent == "investigate_recurring_alarms"
    assert response.incident is not None
    assert response.incident["title"] == "Boiler B-101 tube leak suspect"

    # Wire-level assertions on what the client sent.
    assert len(seen) == 1
    request = seen[0]
    assert request.method == "POST"
    assert str(request.url).endswith("/chat")
    assert json.loads(request.content) == {"message": "Investigate boiler B-101"}


# --------------------------------------------------------------------------- #
# Request body
# --------------------------------------------------------------------------- #


def test_send_forwards_conversation_id_when_provided() -> None:
    """The request body carries ``message`` and ``conversation_id``."""
    client, seen = _make_client(lambda _req: _json_response(_FULL_ENVELOPE))
    try:
        response = client.send(message="Follow up", conversation_id="conv-abc")
    finally:
        client.close()
    assert response.conversation_id == "conv-abc"
    assert json.loads(seen[0].content) == {
        "message": "Follow up",
        "conversation_id": "conv-abc",
    }


def test_send_omits_conversation_id_when_none() -> None:
    """A missing ``conversation_id`` is dropped from the body."""
    client, seen = _make_client(lambda _req: _json_response(_FULL_ENVELOPE))
    try:
        client.send(message="New investigation")
    finally:
        client.close()
    body = json.loads(seen[0].content)
    assert body == {"message": "New investigation"}
    assert "conversation_id" not in body


# --------------------------------------------------------------------------- #
# Trace header
# --------------------------------------------------------------------------- #


def test_send_forwards_caller_trace_id() -> None:
    """A caller-supplied ``trace_id`` flows to ``x-trace-id``."""
    client, seen = _make_client(lambda _req: _json_response(_FULL_ENVELOPE))
    try:
        client.send(message="trace me", trace_id="trace-fixed-123")
    finally:
        client.close()
    assert seen[0].headers["x-trace-id"] == "trace-fixed-123"


def test_send_generates_trace_id_when_none_provided() -> None:
    """A fresh uuid4 hex is generated when no trace id is supplied."""
    client, seen = _make_client(lambda _req: _json_response(_FULL_ENVELOPE))
    try:
        client.send(message="auto trace")
    finally:
        client.close()
    trace = seen[0].headers["x-trace-id"]
    assert isinstance(trace, str)
    assert len(trace) == 32  # uuid4 hex
    assert trace.isalnum()


def test_send_generates_unique_trace_ids_per_call() -> None:
    """Each call mints a fresh trace id when none is supplied."""
    client, seen = _make_client(lambda _req: _json_response(_FULL_ENVELOPE))
    try:
        client.send(message="first")
        client.send(message="second")
    finally:
        client.close()
    trace_a = seen[0].headers["x-trace-id"]
    trace_b = seen[1].headers["x-trace-id"]
    assert trace_a != trace_b


def test_client_trace_id_used_when_call_omits() -> None:
    """A client-level ``trace_id`` overrides auto-generation but
    a per-call ``trace_id`` still wins."""
    client, seen = _make_client(lambda _req: _json_response(_FULL_ENVELOPE), base_url="http://stub")
    client._fixed_trace_id = "client-level-trace"  # type: ignore[attr-defined]
    try:
        client.send(message="no per-call trace")
        client.send(message="with per-call trace", trace_id="per-call")
    finally:
        client.close()
    assert seen[0].headers["x-trace-id"] == "client-level-trace"
    assert seen[1].headers["x-trace-id"] == "per-call"


# --------------------------------------------------------------------------- #
# HTTP error envelopes
# --------------------------------------------------------------------------- #


def test_send_http_error_with_envelope() -> None:
    """422 with ``{detail: {code, message}}`` surfaces verbatim."""
    client, _ = _make_client(
        lambda _req: _envelope_error_response(
            code="planner_error",
            message="Could not parse intent.",
            status_code=422,
        )
    )
    try:
        with pytest.raises(ChatError) as exc_info:
            client.send(message="x")
    finally:
        client.close()
    assert exc_info.value.code == "planner_error"
    assert "Could not parse intent" in exc_info.value.message
    assert exc_info.value.status_code == 422


def test_send_http_500_with_envelope() -> None:
    """500 + structured envelope surfaces with the same code."""
    client, _ = _make_client(
        lambda _req: _envelope_error_response(
            code="orchestrator_error",
            message="LLM provider is down.",
            status_code=500,
        )
    )
    try:
        with pytest.raises(ChatError) as exc_info:
            client.send(message="x")
    finally:
        client.close()
    assert exc_info.value.code == "orchestrator_error"
    assert exc_info.value.status_code == 500


def test_send_pydantic_validation_falls_back_to_http_code() -> None:
    """Pydantic's 422 ``[detail]`` list has no ``code``; we
    surface ``http_422`` and include the first error's loc/msg."""
    list_response = httpx.Response(
        status_code=422,
        content=json.dumps(
            {"detail": [{"loc": ["body", "message"], "msg": "field required", "type": "value_error"}]}
        ).encode("utf-8"),
        headers={"content-type": "application/json"},
    )
    client, _ = _make_client(lambda _req: list_response)
    try:
        with pytest.raises(ChatError) as exc_info:
            client.send(message="x")
    finally:
        client.close()
    assert exc_info.value.code == "http_422"
    assert "body.message" in exc_info.value.message
    assert exc_info.value.status_code == 422


def test_send_non_json_body_falls_back() -> None:
    """A non-JSON 502 body surfaces as ``http_502`` with the
    raw text in the message."""
    plain = httpx.Response(
        status_code=502,
        content=b"not-json",
        headers={"content-type": "text/plain"},
    )
    client, _ = _make_client(lambda _req: plain)
    try:
        with pytest.raises(ChatError) as exc_info:
            client.send(message="x")
    finally:
        client.close()
    assert exc_info.value.code == "http_502"
    assert "not-json" in exc_info.value.message
    assert exc_info.value.status_code == 502


# --------------------------------------------------------------------------- #
# Client-side guards
# --------------------------------------------------------------------------- #


def test_send_empty_message_raises_client_side() -> None:
    """An empty / whitespace message is rejected before any
    HTTP call — no point burning a backend round-trip."""
    client, seen = _make_client(lambda _req: _json_response(_FULL_ENVELOPE))
    try:
        with pytest.raises(ChatError) as exc_info:
            client.send(message="   ")
    finally:
        client.close()
    assert exc_info.value.code == "empty_message"
    assert seen == []  # nothing was sent


# --------------------------------------------------------------------------- #
# Transport errors
# --------------------------------------------------------------------------- #


def test_send_connection_error_maps_to_backend_unreachable() -> None:
    """A transport error surfaces as ``code='backend_unreachable'``."""

    def boom(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    client, _ = _make_client(boom)
    try:
        with pytest.raises(ChatError) as exc_info:
            client.send(message="hi")
    finally:
        client.close()
    assert exc_info.value.code == "backend_unreachable"
    assert "Could not reach" in exc_info.value.message
    assert exc_info.value.status_code is None


def test_send_timeout_maps_to_backend_unreachable() -> None:
    """A timeout surfaces with the same code so the UI renders
    a stable message regardless of the underlying failure."""

    def timeout(_request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("read timed out")

    client, _ = _make_client(timeout)
    try:
        with pytest.raises(ChatError) as exc_info:
            client.send(message="hi")
    finally:
        client.close()
    assert exc_info.value.code == "backend_unreachable"


# --------------------------------------------------------------------------- #
# URL handling
# --------------------------------------------------------------------------- #


def test_client_strips_trailing_slash() -> None:
    """``base_url`` with a trailing slash still hits ``/chat``."""
    client, _ = _make_client(lambda _req: _json_response(_FULL_ENVELOPE), base_url="http://stub/")
    try:
        assert client.base_url == "http://stub"
    finally:
        client.close()


def test_default_url_uses_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    """When no ``base_url`` is supplied, the client reads
    ``core.config.get_settings().copilot_backend_url`` — the
    only place this URL is resolved (the project-wide rule that
    all configuration flows through ``core.config``; see
    ``CLAUDE.md``)."""
    monkeypatch.setenv("COPILOT_BACKEND_URL", "https://example.test:8000")
    get_settings.cache_clear()
    try:
        client = ChatClient()
    finally:
        get_settings.cache_clear()
        client.close()
    assert client.base_url == "https://example.test:8000"
