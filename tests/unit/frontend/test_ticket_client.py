"""Unit tests for ``apps.frontend.ticket_client``.

Mirrors the structure of ``tests/unit/frontend/test_chat_client.py``:
``httpx.MockTransport`` so we never touch the network, with
wire-level assertions on the request body, headers, and URL.

These tests verify Story 7.2.1 acceptance criteria at the HTTP
client layer:

* The client reads the backend URL from settings (no hard-coded URL).
* ``POST /tickets/preview`` is invoked with the documented body shape.
* ``POST /tickets/draft`` is invoked with ``approved=True``.
* ``x-trace-id`` round-trips so the backend's log correlation works.
* HTTP and transport failures surface as a stable ``TicketError``
  the UI can render.
"""
from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import httpx
import pytest

from apps.frontend.ticket_client import TicketClient, TicketDraft, TicketError, TicketPreview
from core.config import get_settings

HandlerFn = Callable[[httpx.Request], httpx.Response]


def _make_client(handler: HandlerFn, *, base_url: str = "http://stub") -> tuple[TicketClient, list[httpx.Request]]:
    """Build a :class:`TicketClient` whose httpx transport is replaced
    by ``handler``. Returns the client and a list that captures every
    request the client sends (in order)."""
    seen: list[httpx.Request] = []

    def capturing(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return handler(request)

    transport = httpx.MockTransport(capturing)
    client = TicketClient(base_url=base_url)
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


_PREVIEW_ENVELOPE: dict[str, Any] = {
    "title": "Boiler B-101 tube leak suspect",
    "body": "Recurring high-temp alarms; inspect tube sheet.",
    "severity": "critical",
    "assignee": None,
    "labels": ["severity:critical", "related:TKT-1042"],
    "incident_id": "INC-9001",
}


_CREATE_ENVELOPE: dict[str, Any] = {
    "conversation_id": "conv-abc",
    "title": "Boiler B-101 tube leak suspect",
    "body": "Recurring high-temp alarms; inspect tube sheet.",
    "severity": "critical",
    "assignee": None,
    "labels": ["severity:critical", "related:TKT-1042"],
    "ticket_id": "TKT-2001",
    "preview": False,
    "approval": {
        "approved_by": "operator",
        "approved_at": "2026-08-08T11:30:00Z",
        "request_id": "req-xyz",
    },
}


# --------------------------------------------------------------------------- #
# preview() — POST /tickets/preview
# --------------------------------------------------------------------------- #


def test_preview_happy_path() -> None:
    """200 + valid envelope → returned as a typed ``TicketPreview``."""
    client, seen = _make_client(lambda _req: _json_response(_PREVIEW_ENVELOPE))
    try:
        preview = client.preview(incident={"id": "INC-9001", "title": "x"})
    finally:
        client.close()

    assert isinstance(preview, TicketPreview)
    assert preview.title == "Boiler B-101 tube leak suspect"
    assert preview.severity == "critical"
    assert preview.labels == ["severity:critical", "related:TKT-1042"]
    assert preview.incident_id == "INC-9001"
    assert preview.assignee is None

    # Wire-level assertions.
    assert len(seen) == 1
    request = seen[0]
    assert request.method == "POST"
    assert str(request.url).endswith("/tickets/preview")
    assert json.loads(request.content) == {"incident": {"id": "INC-9001", "title": "x"}}


def test_preview_forwards_caller_trace_id() -> None:
    """A caller-supplied ``trace_id`` flows to ``x-trace-id``."""
    client, seen = _make_client(lambda _req: _json_response(_PREVIEW_ENVELOPE))
    try:
        client.preview(incident={"id": "INC-1"}, trace_id="trace-fixed-123")
    finally:
        client.close()
    assert seen[0].headers["x-trace-id"] == "trace-fixed-123"


def test_preview_generates_trace_id_when_none_provided() -> None:
    """A fresh uuid4 hex is generated when no trace id is supplied."""
    client, seen = _make_client(lambda _req: _json_response(_PREVIEW_ENVELOPE))
    try:
        client.preview(incident={"id": "INC-1"})
    finally:
        client.close()
    trace = seen[0].headers["x-trace-id"]
    assert isinstance(trace, str)
    assert len(trace) == 32  # uuid4 hex
    assert trace.isalnum()


def test_preview_403_maps_to_approval_required() -> None:
    """A 403 from the preview path (which can happen if the
    backend rejects the payload format) surfaces as
    ``code='approval_required'`` so the UI renders a stable
    message."""
    client, _ = _make_client(
        lambda _req: _envelope_error_response(
            code="approval_required",
            message="ticket creation requires explicit approval",
            status_code=403,
        )
    )
    try:
        with pytest.raises(TicketError) as exc_info:
            client.preview(incident={"id": "INC-1"})
    finally:
        client.close()
    assert exc_info.value.code == "approval_required"
    assert exc_info.value.status_code == 403


def test_preview_500_maps_to_orchestrator_error() -> None:
    """A 500 with structured envelope surfaces with the same code."""
    client, _ = _make_client(
        lambda _req: _envelope_error_response(
            code="orchestrator_error",
            message="Internal failure",
            status_code=500,
        )
    )
    try:
        with pytest.raises(TicketError) as exc_info:
            client.preview(incident={"id": "INC-1"})
    finally:
        client.close()
    assert exc_info.value.code == "orchestrator_error"
    assert exc_info.value.status_code == 500


def test_preview_non_json_body_falls_back() -> None:
    """A non-JSON 502 body surfaces as ``http_502`` with the
    raw text in the message."""
    plain = httpx.Response(
        status_code=502,
        content=b"not-json",
        headers={"content-type": "text/plain"},
    )
    client, _ = _make_client(lambda _req: plain)
    try:
        with pytest.raises(TicketError) as exc_info:
            client.preview(incident={"id": "INC-1"})
    finally:
        client.close()
    assert exc_info.value.code == "http_502"
    assert "not-json" in exc_info.value.message
    assert exc_info.value.status_code == 502


def test_preview_connection_error_maps_to_backend_unreachable() -> None:
    """A transport error surfaces as ``code='backend_unreachable'``."""

    def boom(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    client, _ = _make_client(boom)
    try:
        with pytest.raises(TicketError) as exc_info:
            client.preview(incident={"id": "INC-1"})
    finally:
        client.close()
    assert exc_info.value.code == "backend_unreachable"
    assert exc_info.value.status_code is None


def test_preview_rejects_non_dict_incident() -> None:
    """A non-dict ``incident`` is rejected client-side before
    any HTTP call."""
    client, seen = _make_client(lambda _req: _json_response(_PREVIEW_ENVELOPE))
    try:
        with pytest.raises(TicketError) as exc_info:
            client.preview(incident="not-a-dict")  # type: ignore[arg-type]
    finally:
        client.close()
    assert exc_info.value.code == "bad_incident"
    assert seen == []  # nothing was sent


# --------------------------------------------------------------------------- #
# create() — POST /tickets/draft with approved=True
# --------------------------------------------------------------------------- #


def test_create_happy_path() -> None:
    """200 + valid envelope → returned as a typed ``TicketDraft``
    with the approval block populated."""
    client, seen = _make_client(lambda _req: _json_response(_CREATE_ENVELOPE))
    try:
        draft = client.create(incident={"id": "INC-9001", "title": "x"})
    finally:
        client.close()

    assert isinstance(draft, TicketDraft)
    assert draft.ticket_id == "TKT-2001"
    assert draft.preview is False
    assert draft.approval == _CREATE_ENVELOPE["approval"]

    # Wire-level: approved=True is the only payload difference from
    # the preview path.
    assert len(seen) == 1
    request = seen[0]
    assert str(request.url).endswith("/tickets/draft")
    body = json.loads(request.content)
    assert body == {"incident": {"id": "INC-9001", "title": "x"}, "approved": True}


def test_create_403_maps_to_approval_required() -> None:
    """A 403 from the gated path surfaces as
    ``code='approval_required'`` so the UI renders a stable
    message — this happens if the caller forgets to approve."""
    client, _ = _make_client(
        lambda _req: _envelope_error_response(
            code="approval_required",
            message="ticket creation requires explicit approval",
            status_code=403,
        )
    )
    try:
        with pytest.raises(TicketError) as exc_info:
            client.create(incident={"id": "INC-1"})
    finally:
        client.close()
    assert exc_info.value.code == "approval_required"
    assert exc_info.value.status_code == 403


def test_create_connection_error_maps_to_backend_unreachable() -> None:
    """A transport error surfaces as ``code='backend_unreachable'``."""

    def boom(_request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("read timed out")

    client, _ = _make_client(boom)
    try:
        with pytest.raises(TicketError) as exc_info:
            client.create(incident={"id": "INC-1"})
    finally:
        client.close()
    assert exc_info.value.code == "backend_unreachable"


def test_create_forwards_trace_id() -> None:
    """``x-trace-id`` flows to the gated path."""
    client, seen = _make_client(lambda _req: _json_response(_CREATE_ENVELOPE))
    try:
        client.create(incident={"id": "INC-1"}, trace_id="trace-create-1")
    finally:
        client.close()
    assert seen[0].headers["x-trace-id"] == "trace-create-1"


# --------------------------------------------------------------------------- #
# URL handling & defaults
# --------------------------------------------------------------------------- #


def test_client_strips_trailing_slash() -> None:
    """``base_url`` with a trailing slash still hits ``/tickets/preview``."""
    client, _ = _make_client(lambda _req: _json_response(_PREVIEW_ENVELOPE), base_url="http://stub/")
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
        client = TicketClient()
    finally:
        get_settings.cache_clear()
        client.close()
    assert client.base_url == "https://example.test:8000"
