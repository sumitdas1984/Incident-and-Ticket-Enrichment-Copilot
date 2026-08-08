"""Typed HTTP client for the copilot backend's ``POST /chat``.

Feature 7.1 — Story 7.1.2 connects the GUI to the backend. The
Streamlit UI script (``apps.frontend.ui``) calls
:meth:`ChatClient.send` on every user message. The client:

* Reads ``COPILOT_BACKEND_URL`` through :func:`core.config.get_settings`
  (the project-wide rule that all configuration flows through
  ``core.config``; see ``CLAUDE.md``).
* Marshals the request body to the same shape the backend's
  ``ChatRequest`` expects (``apps.backend.orchestrator.request.ChatRequest``).
* Forwards an optional ``x-trace-id`` header so the backend's
  structured logs chain with the GUI's request id.
* Translates httpx transport errors into a typed :class:`ChatError`
  the UI can render in a stable ``[code] message`` format.

The client is intentionally synchronous (Streamlit's runtime is
sync). It owns its :class:`httpx.Client` and closes it when closed;
the Streamlit script keeps one instance for the lifetime of the
app via :func:`apps.frontend.ui.get_client`.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

import httpx

from core.config import get_settings
from core.logging import get_logger

log = get_logger(__name__)


class ChatError(Exception):
    """Raised when the backend is unreachable or returns a non-2xx.

    Attributes
    ----------
    code:
        A short stable identifier the UI renders in its error
        panel. ``backend_unreachable`` for transport errors
        (connection refused, DNS failure, timeout). For HTTP
        failures the code is whatever the backend's ``detail.code``
        field carried — e.g. ``planner_error``, ``mcp_error``,
        ``rag_error``, ``orchestrator_error``, ``approval_required``.
    message:
        Human-readable text. For HTTP failures this is the
        backend's ``detail.message``. For transport errors it's
        the underlying httpx exception's message.
    status_code:
        ``None`` for transport errors; the HTTP status otherwise
        (so tests can assert on 4xx vs 5xx).
    """

    def __init__(
        self,
        *,
        code: str,
        message: str,
        status_code: int | None = None,
    ) -> None:
        super().__init__(f"[{code}] {message}")
        self.code = code
        self.message = message
        self.status_code = status_code


@dataclass
class ChatResponse:
    """Decoded ``POST /chat`` response envelope.

    Mirrors the shape of
    ``apps.backend.orchestrator.request.ChatResponse`` without
    coupling to FastAPI / Pydantic — Streamlit doesn't share
    models with the backend and we want the GUI's client to
    parse independently. ``citation`` / ``trace`` / ``incident``
    are kept as raw dicts so the UI can iterate over them
    without re-validation (Pydantic already validated them on
    the backend).
    """

    conversation_id: str
    answer: str
    citations: list[dict[str, Any]] = field(default_factory=list)
    trace: list[dict[str, Any]] = field(default_factory=list)
    rag_confidence: str = "none"
    dropped_count: int = 0
    intent: str = ""
    raw_payload: dict[str, Any] = field(default_factory=dict)
    incident: dict[str, Any] | None = None


class ChatClient:
    """Synchronous HTTP client for ``POST /chat``.

    Parameters
    ----------
    base_url:
        The copilot-backend root URL. ``core.config.Settings.copilot_backend_url``
        is the canonical source; tests can pass any URL (e.g.
        a TestClient root) to point at a fake backend.
    timeout_s:
        Per-request timeout (connect/read/write/pool). The default
        (30 s) accommodates the orchestrator's MCP chain + RAG
        retrieval worst-case latency. ``send`` does not retry;
        the backend's own retry layer (Feature 3.3) handles
        upstream MCP retries.
    trace_id:
        Optional fixed trace id (e.g. from a unit test). When
        ``None``, every :meth:`send` call generates a fresh
        uuid4 hex string so the backend's logs always carry a
        unique ``x-trace-id`` — useful when correlating one
        browser session to the structured logs.
    """

    def __init__(
        self,
        *,
        base_url: str | None = None,
        timeout_s: float = 30.0,
        trace_id: str | None = None,
    ) -> None:
        if base_url is None:
            base_url = get_settings().copilot_backend_url
        # Strip a trailing slash so URL joins are predictable.
        self._base_url = base_url.rstrip("/")
        self._timeout_s = timeout_s
        self._fixed_trace_id = trace_id
        self._client = httpx.Client(timeout=timeout_s)

    @property
    def base_url(self) -> str:
        """The resolved backend URL — surfaced for the UI header."""
        return self._base_url

    def close(self) -> None:
        """Release the underlying HTTP connection pool."""
        self._client.close()

    def __enter__(self) -> ChatClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def send(
        self,
        *,
        message: str,
        conversation_id: str | None = None,
        trace_id: str | None = None,
    ) -> ChatResponse:
        """POST a chat message and return the decoded response.

        Raises
        ------
        ChatError
            ``code='backend_unreachable'`` on transport failure,
            or the backend's own ``detail.code`` on HTTP failure.
        """
        if not message or not message.strip():
            raise ChatError(
                code="empty_message",
                message="Message must be a non-empty string.",
            )

        url = f"{self._base_url}/chat"
        payload: dict[str, Any] = {"message": message}
        if conversation_id:
            payload["conversation_id"] = conversation_id

        # Honour the caller's trace_id, then the client's default,
        # then generate one fresh — every outbound request gets a
        # trace header so the backend's logs always correlate.
        effective_trace = trace_id or self._fixed_trace_id or uuid.uuid4().hex
        headers = {"x-trace-id": effective_trace}

        log.info(
            "chat.send",
            url=url,
            conversation_id=conversation_id,
            message_length=len(message),
            trace_id=effective_trace,
        )

        try:
            response = self._client.post(url, json=payload, headers=headers)
        except httpx.RequestError as exc:
            log.warning(
                "chat.transport_error",
                url=url,
                error=type(exc).__name__,
                detail=str(exc),
                trace_id=effective_trace,
            )
            raise ChatError(
                code="backend_unreachable",
                message=f"Could not reach the copilot backend: {exc}",
            ) from exc

        if response.status_code >= 400:
            raise self._http_error(response, trace_id=effective_trace)

        return self._parse(response, trace_id=effective_trace)

    @staticmethod
    def _http_error(response: httpx.Response, *, trace_id: str) -> ChatError:
        """Translate a non-2xx response into a typed ChatError.

        The backend emits FastAPI's standard envelope:
        ``{"detail": {"code": "...", "message": "..."}}`` for the
        HTTPException paths in ``apps.backend.routes``. Anything
        that doesn't match that shape falls back to a generic
        ``http_<status>`` code so the UI always has something
        stable to render.
        """
        detail: Any
        try:
            detail = response.json()
        except Exception:  # noqa: BLE001 — defensive: non-JSON body
            log.warning(
                "chat.http_error_non_json",
                status_code=response.status_code,
                trace_id=trace_id,
            )
            return ChatError(
                code=f"http_{response.status_code}",
                message=response.text or "Backend returned an error.",
                status_code=response.status_code,
            )

        # FastAPI wraps HTTPException's ``detail`` directly — for
        # the orchestrator's routes the detail is already a dict
        # shaped ``{"code": ..., "message": ...}``. When the
        # backend returns a Pydantic validation 422 the body is
        # ``{"detail": [{"loc": [...], "msg": "...", ...}, ...]}``;
        # we surface the first error's msg as the message.
        inner = detail.get("detail") if isinstance(detail, dict) else None
        if isinstance(inner, dict) and "code" in inner:
            code = str(inner.get("code") or f"http_{response.status_code}")
            message = str(inner.get("message") or "Backend returned an error.")
        elif isinstance(inner, list) and inner and isinstance(inner[0], dict):
            code = f"http_{response.status_code}"
            first = inner[0]
            loc = ".".join(str(p) for p in first.get("loc", ()))
            message = f"{loc}: {first.get('msg', 'validation error')}"
        else:
            code = f"http_{response.status_code}"
            fallback_message = "Backend returned an error."
            if isinstance(detail, dict):
                raw_message = detail.get("message")
                if isinstance(raw_message, str):
                    fallback_message = raw_message
            message = fallback_message

        log.warning(
            "chat.http_error",
            status_code=response.status_code,
            code=code,
            message=message,
            trace_id=trace_id,
        )
        return ChatError(
            code=code,
            message=message,
            status_code=response.status_code,
        )

    @staticmethod
    def _parse(response: httpx.Response, *, trace_id: str) -> ChatResponse:
        """Decode a 2xx body into a :class:`ChatResponse`."""
        body = response.json()
        if not isinstance(body, dict):
            raise ChatError(
                code="bad_response_shape",
                message="Backend returned a non-object JSON body.",
                status_code=response.status_code,
            )
        return ChatResponse(
            conversation_id=str(body.get("conversation_id") or ""),
            answer=str(body.get("answer") or ""),
            citations=list(body.get("citations") or []),
            trace=list(body.get("trace") or []),
            rag_confidence=str(body.get("rag_confidence") or "none"),
            dropped_count=int(body.get("dropped_count") or 0),
            intent=str(body.get("intent") or ""),
            raw_payload=dict(body.get("raw_payload") or {}),
            incident=body.get("incident") if isinstance(body.get("incident"), dict) else None,
        )


def build_default_client() -> ChatClient:
    """Construct a :class:`ChatClient` from the cached settings.

    Convenience for the Streamlit entrypoint — pulls the URL out
    of the singleton settings (the only place this URL is
    resolved).
    """
    return ChatClient(base_url=get_settings().copilot_backend_url)


__all__ = ["ChatClient", "ChatError", "ChatResponse", "build_default_client"]
