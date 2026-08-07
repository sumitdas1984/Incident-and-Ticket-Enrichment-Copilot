"""Async HTTP client for the Alarm Management API.

Every MCP tool handler talks to the Alarm API through this single
client. Centralising auth, trace propagation, timeouts, retries,
and error mapping here means the four tool handlers stay thin
and focused, and resilience tweaks (Feature 3.3) land in one
module.

Hard constraint #1 from the brief ("the copilot must call the
Alarm Management API exclusively through the MCP server") is
satisfied by the fact that the only place outside
``connectors/alarm_api`` (the simulator itself) that opens an
``httpx.AsyncClient`` for this base URL is this module — every
tool handler in ``tools.py`` imports ``AlarmApiClient`` and goes
through ``server.alarm_api_client``.

What we deliberately don't do here
----------------------------------

* **No circuit breaker.** Cross-call failure-rate tracking is a
  Feature 3.5 concern.
* **No connection pooling tuning.** Default ``httpx`` limits are
  fine for the four-tool MCP surface; the orchestrator is a single
  user in a synchronous conversation.
* **No streaming.** All alarm-api endpoints are request/response;
  none stream. Feature 3.5 (advanced ops) might add it.
"""
from __future__ import annotations

from typing import Any

import httpx
from pydantic import SecretStr

from core.config import Settings
from core.logging import get_logger

from .registry import ToolInvocationError
from .retry import RetryPolicy, retry_with_policy

log = get_logger(__name__)

# Default per-request timeout. Surfaced via ``Settings`` in
# Feature 3.3 so an operator can tune tail latency without code
# changes; the constant remains as the constructor default.
_DEFAULT_TIMEOUT_S = 5.0


class AlarmNotFoundError(ToolInvocationError):
    """Distinct envelope for "the alarm you asked about doesn't exist".

    The MCP transport turns this into ``isError=True`` with the
    message text — and crucially **without** the alarm-api URL or
    bearer token. Subclassing ``ToolInvocationError`` keeps the
    mapping uniform while letting callers (``get_alarm``,
    ``recommend_actions``) raise a more precise error than the
    generic 4xx envelope.
    """

    def __init__(self, alarm_id: str) -> None:
        super().__init__(
            f"Alarm {alarm_id} not found.",
            hint="Verify the alarm_id is correct and the alarm is still on record.",
        )
        self.alarm_id = alarm_id


class AlarmApiClient:
    """Async client for the Alarm Management API.

    The client is created once at server startup (see
    ``__main__.py``'s lifespan) so connections are reused across
    tool invocations. Each tool handler reads it from
    ``server.alarm_api_client`` (set by the lifespan).

    Parameters
    ----------
    base_url:
        Origin of the alarm-api simulator, e.g. ``http://localhost:8000``.
        No trailing slash; ``get_json`` / ``post_json`` join with ``/``.
    token:
        Bearer token. Wrapped in ``SecretStr`` so accidental
        ``str(token)`` in logs / exceptions doesn't leak it. We
        explicitly call ``get_secret_value()`` only at request time.
    timeout_seconds:
        Per-request timeout for connect / read / write / pool.
        Defaults to 5 s — short enough that a stuck alarm-api can't
        hang an MCP tool call, long enough for a healthy one to
        respond under docker-compose load.
    client:
        Optional pre-built ``httpx.AsyncClient`` (used by tests
        with ``httpx.MockTransport``). If omitted, a fresh client
        with sensible defaults is constructed.
    """

    def __init__(
        self,
        *,
        base_url: str,
        token: SecretStr,
        timeout_seconds: float = _DEFAULT_TIMEOUT_S,
        retry_policy: RetryPolicy | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._token = token
        self._retry_policy = retry_policy or RetryPolicy()
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(
            base_url=self._base_url,
            timeout=httpx.Timeout(timeout_seconds),
            headers={"Accept": "application/json"},
        )

    # ---- Public API ----------------------------------------------------- #

    @classmethod
    def from_settings(cls, settings: Settings) -> AlarmApiClient:
        """Build a client from the app's central `Settings`.

        Keeps ``ALARM_API_BASE_URL`` and ``ALARM_API_TOKEN`` as the
        single source of truth — same env vars the alarm-api
        simulator reads for its own port. The retry policy is
        derived from the ``alarm_api_max_attempts`` /
        ``alarm_api_initial_backoff_s`` / ``alarm_api_max_backoff_s``
        fields added in Feature 3.3.
        """
        return cls(
            base_url=settings.alarm_api_base_url,
            token=settings.alarm_api_token,
            timeout_seconds=settings.alarm_api_timeout_s,
            retry_policy=RetryPolicy.from_settings(settings),
        )

    async def get_json(
        self,
        path: str,
        *,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Issue ``GET <base_url><path>`` and return the parsed JSON body.

        Wrapped in a :class:`RetryPolicy` so transient 5xx, 408,
        425, 429, and the documented transport exceptions are
        retried with bounded exponential back-off + jitter. The
        four tool handlers see the same interface as Feature 3.2
        and the same exception envelope.

        Raises
        ------
        AlarmNotFoundError
            If the alarm-api returns 404 (never retried — first
            404 always surfaces).
        ToolInvocationError
            For any other non-2xx response after retries are
            exhausted, or for non-retryable transport errors.
            The message is sanitised; no token, no body, no URL
            with credentials.
        """
        @retry_with_policy(self._retry_policy)
        async def _attempt() -> httpx.Response:
            try:
                response = await self._client.get(
                    path, params=params, headers=self._headers()
                )
                response.raise_for_status()
            except httpx.HTTPError as exc:
                # ``HTTPStatusError`` is re-raised so the retry
                # decorator can decide retry-vs-surface based on
                # the status code (5xx, 408, 425, 429 are
                # retried; everything else falls through to
                # ``_raise_for_status`` in the post-retry shim).
                #
                # Retryable transport exceptions (``ConnectError``,
                # ``ReadTimeout``, etc.) are also re-raised so the
                # retry decorator sees them. Non-retryable
                # transport exceptions (``InvalidURL``,
                # ``UnsupportedProtocol``) are wrapped here in the
                # sanitised envelope.
                if isinstance(exc, httpx.HTTPStatusError):
                    raise
                if self._retry_policy.is_retryable_exception(exc):
                    raise
                log.warning(
                    "alarm_api.transport_error",
                    method="GET",
                    path=path,
                    error_type=type(exc).__name__,
                    exc_info=True,
                )
                raise ToolInvocationError(
                    "Upstream Alarm API call failed.",
                    hint="See server logs with the same trace_id for details.",
                ) from exc
            return response

        try:
            response = await _attempt()
        except httpx.HTTPStatusError as exc:
            # Retry exhausted (or non-retryable): map the status
            # to the right envelope.
            self._raise_for_status(exc)
            # Unreachable: ``_raise_for_status`` always raises.
            raise AssertionError("unreachable") from exc  # pragma: no cover
        return response.json()

    async def post_json(self, path: str, *, json: dict[str, Any]) -> dict[str, Any]:
        """Issue ``POST <base_url><path>`` with a JSON body and parse the response.

        Raises the same exceptions as ``get_json``. The retry
        policy applies identically because the alarm-api's
        recommendation endpoint is idempotent under a single
        ``alarm_id``.
        """
        @retry_with_policy(self._retry_policy)
        async def _attempt() -> httpx.Response:
            try:
                response = await self._client.post(
                    path, json=json, headers=self._headers()
                )
                response.raise_for_status()
            except httpx.HTTPError as exc:
                if isinstance(exc, httpx.HTTPStatusError):
                    raise
                if self._retry_policy.is_retryable_exception(exc):
                    raise
                log.warning(
                    "alarm_api.transport_error",
                    method="POST",
                    path=path,
                    error_type=type(exc).__name__,
                    exc_info=True,
                )
                raise ToolInvocationError(
                    "Upstream Alarm API call failed.",
                    hint="See server logs with the same trace_id for details.",
                ) from exc
            return response

        try:
            response = await _attempt()
        except httpx.HTTPStatusError as exc:
            self._raise_for_status(exc)
            raise AssertionError("unreachable") from exc  # pragma: no cover
        return response.json()

    async def aclose(self) -> None:
        """Close the underlying ``httpx.AsyncClient``.

        Called by ``MCPServerLifespan.__aexit__`` so connection
        pools shut down with the server. Safe to call even when
        the client was supplied by a test (those should pass
        ``client=`` and the test owns its lifecycle).
        """
        if self._owns_client:
            await self._client.aclose()

    # ---- Internals ------------------------------------------------------ #

    def _headers(self) -> dict[str, str]:
        """Build per-request headers (auth + trace propagation).

        The active ``trace_id`` comes from structlog's contextvar
        that ``registry.register_tool`` binds before each call —
        see ``core.logging.bind_context``. We read it through
        structlog's contextvars binding so it stays consistent
        with the rest of the request log lines.
        """
        import structlog.contextvars as cvars

        trace_id = cvars.get_contextvars().get("trace_id") or "mcp-no-trace"
        return {
            "Authorization": f"Bearer {self._token.get_secret_value()}",
            "X-Trace-Id": str(trace_id),
        }

    @staticmethod
    def _raise_for_status(exc: httpx.HTTPStatusError) -> None:
        """Map alarm-api non-2xx responses to MCP ``ToolInvocationError``.

        Called from ``get_json`` / ``post_json`` after the retry
        layer has exhausted its attempts. By the time we reach
        here, retryable status codes have already had their
        retries; we map them to the same envelopes the rest
        get, with the standard sanitised message.

        404 → ``AlarmNotFoundError`` (used by ``get_alarm`` and
        ``recommend_actions`` for precise "alarm not found" without
        the alarm-api URL leaking).

        All other non-2xx (including retryable ones after
        exhaustion) → generic ``ToolInvocationError`` with a
        sanitised message. We log the body server-side for
        debugging; the message on the wire carries no token, no
        URL with credentials, no body.
        """
        status = exc.response.status_code
        if status == 404:
            # Best-effort extract of an alarm_id from the path. The
            # alarm-api returns 404 for /alarms/{id} and
            # /recommendations/operator-actions when the alarm is
            # unknown; the path's last segment is the alarm_id.
            path = exc.request.url.path.rstrip("/")
            alarm_id = path.rsplit("/", 1)[-1] or "unknown"
            log.info("alarm_api.not_found", alarm_id=alarm_id)
            raise AlarmNotFoundError(alarm_id) from exc

        log.warning(
            "alarm_api.upstream_error",
            status=status,
            method=exc.request.method,
            path=exc.request.url.path,
            exc_info=True,
        )
        raise ToolInvocationError(
            f"Upstream Alarm API returned status {status}.",
            hint="See server logs with the same trace_id for details.",
        ) from exc
