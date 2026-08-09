"""Typed HTTP client for the copilot backend's ticket endpoints.

Feature 7.2 — PR 2 (GUI). The Streamlit workspace column
(``apps.frontend.ui``) calls two endpoints through this client:

* :meth:`TicketClient.preview` — ``POST /tickets/preview`` (added
  in PR 1 of Feature 7.2). Pure projection — no ticket is
  persisted.
* :meth:`TicketClient.create` — ``POST /tickets/draft`` with
  ``approved=True`` (Feature 6.2's gated path). Persists the
  ticket and returns the audit metadata.

The client mirrors :mod:`apps.frontend.chat_client`: sync httpx,
typed envelope dataclasses, env-driven URL via
:func:`core.config.get_settings` (the project-wide rule that all
configuration flows through ``core.config``; see ``CLAUDE.md``),
``x-trace-id`` forwarded on every request so the backend's
structured logs chain with the GUI's request id, and httpx
transport / HTTP errors mapped to a typed :class:`TicketError`
the UI renders in a stable ``[code] message`` format.

The client owns its :class:`httpx.Client` and closes it when
closed; the Streamlit script keeps one instance for the lifetime
of the app via :func:`apps.frontend.ui.get_ticket_client`.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

import httpx

from core.config import get_settings
from core.logging import get_logger

log = get_logger(__name__)


class TicketError(Exception):
    """Raised when the backend is unreachable or returns a non-2xx.

    Attributes
    ----------
    code:
        A short stable identifier the UI renders in its error
        panel. ``backend_unreachable`` for transport errors.
        For HTTP failures the code is whatever the backend's
        ``detail.code`` field carried — e.g. ``approval_required``
        on a 403 from the gated path.
    message:
        Human-readable text.
    status_code:
        ``None`` for transport errors; the HTTP status otherwise.
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
class TicketPreview:
    """Decoded ``POST /tickets/preview`` response envelope.

    Carries the projected ticket draft fields — title, body,
    severity, assignee, labels — plus an echo of the source
    incident's id for the GUI to correlate.
    """

    title: str
    body: str
    severity: str
    assignee: str | None = None
    labels: list[str] = field(default_factory=list)
    incident_id: str | None = None


@dataclass
class TicketDraft:
    """Decoded ``POST /tickets/draft`` response envelope.

    ``ticket_id`` is ``None`` on a rejected (403) call; the GUI
    surfaces the rejection envelope via the ``approval`` /
    ``conversation_id`` blocks. ``preview`` is always ``False`` on
    this path — previews go through :meth:`TicketClient.preview`.
    """

    conversation_id: str
    title: str
    body: str
    severity: str
    assignee: str | None = None
    labels: list[str] = field(default_factory=list)
    ticket_id: str | None = None
    preview: bool = False
    approval: dict[str, Any] | None = None


class TicketClient:
    """Synchronous HTTP client for ``/tickets/preview`` and
    ``/tickets/draft``.

    Parameters
    ----------
    base_url:
        The copilot-backend root URL. ``core.config.Settings.copilot_backend_url``
        is the canonical source; tests can pass any URL.
    timeout_s:
        Per-request timeout. The default (30 s) accommodates the
        orchestrator's worst-case latency for the gated path.
    trace_id:
        Optional fixed trace id (e.g. from a unit test). When
        ``None``, every :meth:`preview` / :meth:`create` call
        generates a fresh uuid4 hex string so the backend's logs
        always carry a unique ``x-trace-id``.
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

    def __enter__(self) -> TicketClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def preview(
        self,
        *,
        incident: dict[str, Any],
        trace_id: str | None = None,
    ) -> TicketPreview:
        """POST a preview request and return the projected draft.

        Raises
        ------
        TicketError
            ``code='backend_unreachable'`` on transport failure,
            or the backend's ``detail.code`` on HTTP failure.
        """
        if not isinstance(incident, dict):
            raise TicketError(
                code="bad_incident",
                message="Incident must be a dict.",
            )

        url = f"{self._base_url}/tickets/preview"
        effective_trace = trace_id or self._fixed_trace_id or uuid.uuid4().hex
        headers = {"x-trace-id": effective_trace}

        log.info(
            "ticket.preview",
            url=url,
            incident_id=incident.get("id"),
            trace_id=effective_trace,
        )

        try:
            response = self._client.post(url, json={"incident": incident}, headers=headers)
        except httpx.RequestError as exc:
            log.warning(
                "ticket.transport_error",
                url=url,
                error=type(exc).__name__,
                detail=str(exc),
                trace_id=effective_trace,
            )
            raise TicketError(
                code="backend_unreachable",
                message=f"Could not reach the copilot backend: {exc}",
            ) from exc

        if response.status_code >= 400:
            raise self._http_error(response, trace_id=effective_trace)

        return self._parse_preview(response, trace_id=effective_trace)

    def create(
        self,
        *,
        incident: dict[str, Any],
        trace_id: str | None = None,
    ) -> TicketDraft:
        """POST a gated create request and return the persisted draft.

        Hard constraint #3 is enforced at the ticket-mock layer;
        this method's caller has already confirmed via the GUI's
        modal. The backend may still return 403 if the caller
        skipped the approval flag — that surfaces as
        :class:`TicketError` with ``code='approval_required'``.
        """
        if not isinstance(incident, dict):
            raise TicketError(
                code="bad_incident",
                message="Incident must be a dict.",
            )

        url = f"{self._base_url}/tickets/draft"
        effective_trace = trace_id or self._fixed_trace_id or uuid.uuid4().hex
        headers = {"x-trace-id": effective_trace}
        payload = {"incident": incident, "approved": True}

        log.info(
            "ticket.create",
            url=url,
            incident_id=incident.get("id"),
            trace_id=effective_trace,
        )

        try:
            response = self._client.post(url, json=payload, headers=headers)
        except httpx.RequestError as exc:
            log.warning(
                "ticket.transport_error",
                url=url,
                error=type(exc).__name__,
                detail=str(exc),
                trace_id=effective_trace,
            )
            raise TicketError(
                code="backend_unreachable",
                message=f"Could not reach the copilot backend: {exc}",
            ) from exc

        if response.status_code >= 400:
            raise self._http_error(response, trace_id=effective_trace)

        return self._parse_draft(response, trace_id=effective_trace)

    @staticmethod
    def _http_error(response: httpx.Response, *, trace_id: str) -> TicketError:
        """Translate a non-2xx response into a typed TicketError."""
        try:
            detail = response.json()
        except Exception:  # noqa: BLE001 — defensive: non-JSON body
            log.warning(
                "ticket.http_error_non_json",
                status_code=response.status_code,
                trace_id=trace_id,
            )
            return TicketError(
                code=f"http_{response.status_code}",
                message=response.text or "Backend returned an error.",
                status_code=response.status_code,
            )

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
            "ticket.http_error",
            status_code=response.status_code,
            code=code,
            message=message,
            trace_id=trace_id,
        )
        return TicketError(
            code=code,
            message=message,
            status_code=response.status_code,
        )

    @staticmethod
    def _parse_preview(response: httpx.Response, *, trace_id: str) -> TicketPreview:
        body = response.json()
        if not isinstance(body, dict):
            raise TicketError(
                code="bad_response_shape",
                message="Backend returned a non-object JSON body.",
                status_code=response.status_code,
            )
        return TicketPreview(
            title=str(body.get("title") or ""),
            body=str(body.get("body") or ""),
            severity=str(body.get("severity") or "medium"),
            assignee=body.get("assignee") if isinstance(body.get("assignee"), str) else None,
            labels=list(body.get("labels") or []),
            incident_id=body.get("incident_id") if isinstance(body.get("incident_id"), str) else None,
        )

    @staticmethod
    def _parse_draft(response: httpx.Response, *, trace_id: str) -> TicketDraft:
        body = response.json()
        if not isinstance(body, dict):
            raise TicketError(
                code="bad_response_shape",
                message="Backend returned a non-object JSON body.",
                status_code=response.status_code,
            )
        return TicketDraft(
            conversation_id=str(body.get("conversation_id") or ""),
            title=str(body.get("title") or ""),
            body=str(body.get("body") or ""),
            severity=str(body.get("severity") or "medium"),
            assignee=body.get("assignee") if isinstance(body.get("assignee"), str) else None,
            labels=list(body.get("labels") or []),
            ticket_id=body.get("ticket_id") if isinstance(body.get("ticket_id"), str) else None,
            preview=bool(body.get("preview", False)),
            approval=body.get("approval") if isinstance(body.get("approval"), dict) else None,
        )


def build_default_client() -> TicketClient:
    """Construct a :class:`TicketClient` from the cached settings."""
    return TicketClient(base_url=get_settings().copilot_backend_url)


__all__ = [
    "TicketClient",
    "TicketError",
    "TicketPreview",
    "TicketDraft",
    "build_default_client",
]
