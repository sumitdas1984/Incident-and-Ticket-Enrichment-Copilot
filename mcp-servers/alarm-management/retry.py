"""Retry policy for the Alarm Management API client.

Story 3.3.1 — implement validation, retry, timeout, and API error
mapping. This module owns the policy; :mod:`alarm_api_client` owns
the wiring. The four tool handlers in :mod:`tools` are untouched
because the policy wraps ``get_json`` / ``post_json`` internally.

Why tenacity
------------

Tenacity is the most widely-used async retry library in the Python
ecosystem. Re-implementing exponential back-off with jitter and
exception filtering in this module would be yak-shaving for the
timebox; ``tenacity`` ships battle-tested wait / stop / retry
hooks. We keep the public surface tiny (:class:`RetryPolicy`,
:func:`retry_with_policy`) so tests can construct a deterministic
policy without reaching into tenacity internals.

Why one global policy
---------------------

Story 3.3.1 doesn't require per-tool tuning. Sharing one policy
across all four tools keeps the handlers uniform and the test
surface small. A future story that needs per-tool overrides
should pass policy at the handler boundary, not duplicate the
wrapper.

Non-goals
---------

* **No circuit breaker.** A flapping alarm-api will still be hit
  up to ``max_attempts`` times per call. A circuit breaker is a
  separate concern (cross-call failure-rate tracking) and lives
  in Feature 3.5 / orchestrator-side.
* **No retry budget.** We don't track total retries across calls.
  The orchestrator decides how many tool calls to chain.
* **No per-tool policy overrides.** See "Why one global policy".
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, TypeVar

import httpx
import tenacity

from core.config import Settings
from core.logging import get_logger

log = get_logger(__name__)


# Status codes that warrant a retry. The set mirrors the
# conventional "transient upstream" bucket: request timeouts,
# rate limits, and any 5xx. We deliberately exclude 4xx other
# than 408 (request timeout) / 425 (too early) / 429 (rate
# limited) because 4xx indicates a client mistake that
# retrying won't fix.
RETRYABLE_STATUS_CODES: frozenset[int] = frozenset(
    {408, 425, 429, 500, 502, 503, 504}
)

# Transport-level exceptions that are transient. ``InvalidURL``,
# ``UnsupportedProtocol``, and the like are excluded — they're
# deterministic and retrying won't help.
_RETRYABLE_TRANSPORT_EXCEPTIONS: tuple[type[BaseException], ...] = (
    httpx.ConnectError,
    httpx.ReadTimeout,
    httpx.WriteTimeout,
    httpx.PoolTimeout,
    httpx.RemoteProtocolError,
)


@dataclass(frozen=True)
class RetryPolicy:
    """Bounded retry policy for :class:`AlarmApiClient`.

    All fields are tunable via :class:`core.config.Settings`; the
    defaults match the values documented in the Feature 3.3 plan
    (3 attempts, 0.25 s → 2.0 s exponential back-off with ±10 %
    jitter). Tests should construct an explicit instance with
    ``initial_backoff_s=0.0, jitter=0.0`` for deterministic
    timing.

    Attributes
    ----------
    max_attempts:
        Total attempts including the first one. ``max_attempts=1``
        disables retries entirely (parity with Feature 3.2
        behaviour).
    initial_backoff_s:
        Lower bound on the exponential-backoff wait between
        attempts. The wait doubles each retry, capped at
        ``max_backoff_s``.
    max_backoff_s:
        Upper bound on the exponential-backoff wait. After enough
        retries the wait plateaus here (plus jitter).
    jitter:
        Fractional jitter (±jitter of the computed backoff) added
        by tenacity. ``0.1`` means the actual wait is in
        ``[backoff × 0.9, backoff × 1.1]``.
    """

    max_attempts: int = 3
    initial_backoff_s: float = 0.25
    max_backoff_s: float = 2.0
    jitter: float = 0.1

    @classmethod
    def from_settings(cls, settings: Settings) -> RetryPolicy:
        """Build a :class:`RetryPolicy` from the app's central :class:`Settings`.

        The ``alarm_api_*`` fields on :class:`Settings` are surfaced
        so an operator can tune the policy via ``.env`` without
        code changes. Jitter stays at ``0.1`` — the value is hard
        coded because jitter of ±10 % is a sensible default and
        doesn't need per-deployment tuning.
        """
        return cls(
            max_attempts=settings.alarm_api_max_attempts,
            initial_backoff_s=settings.alarm_api_initial_backoff_s,
            max_backoff_s=settings.alarm_api_max_backoff_s,
            jitter=0.1,
        )

    def is_retryable_status(self, status_code: int) -> bool:
        """Return True if a response with ``status_code`` warrants a retry."""
        return status_code in RETRYABLE_STATUS_CODES

    def is_retryable_exception(self, exc: BaseException) -> bool:
        """Return True if an exception warrants a retry.

        ``HTTPStatusError`` is retryable when the embedded
        response's status code is in :data:`RETRYABLE_STATUS_CODES`
        (so the orchestrator sees the envelope only after retries
        are exhausted). ``httpx.ConnectError`` and the documented
        transport timeouts are always retryable. ``InvalidURL``
        and friends are deterministic — second attempt would fail
        identically.
        """
        if isinstance(exc, httpx.HTTPStatusError):
            response = exc.response
            if response is None:
                return False
            return self.is_retryable_status(response.status_code)
        return isinstance(exc, _RETRYABLE_TRANSPORT_EXCEPTIONS)


_RetryableCallable = TypeVar("_RetryableCallable", bound=Callable[..., Any])


def retry_with_policy(
    policy: RetryPolicy,
    *,
    logger: Any = None,
) -> Callable[[_RetryableCallable], _RetryableCallable]:
    """Wrap ``async def`` callable in a tenacity retry decorator.

    The wrapped callable runs inside a ``tenacity.AsyncRetrying``
    loop that triggers a retry when **either**:

    * the wrapped call raises a retryable transport exception
      (see :attr:`RetryPolicy.is_retryable_exception`), or
    * the wrapped call raises ``httpx.HTTPStatusError`` for a
      retryable status code (see
      :attr:`RetryPolicy.is_retryable_status`).

    Non-retryable ``HTTPStatusError`` propagates untouched so
    :func:`AlarmApiClient._raise_for_status` can map it to
    :class:`AlarmNotFoundError` / :class:`ToolInvocationError`
    exactly as before.

    Parameters
    ----------
    policy:
        The :class:`RetryPolicy` that bounds attempts and
        back-off.
    logger:
        Optional logger; defaults to this module's logger.
        Exposed so tests can swap in a capturing logger without
        monkey-patching :func:`core.logging.get_logger`.

    Contract for the wrapped callable
    ---------------------------------

    The callable may either return its result or raise. For the
    "retry on status code" case, the callable **must** raise
    ``httpx.HTTPStatusError`` for retryable codes (which the
    decorator will catch and trigger a retry via the
    ``retry_if_exception`` predicate). Tenacity's standard
    ``raise_for_status`` pattern satisfies this contract.

    Notes
    -----

    We use ``tenacity.AsyncRetrying`` directly rather than the
    ``@retry`` decorator so the ``before_sleep`` callback can log
    the retry reason with attempt number, method, and path —
    information only available from inside the retrying loop.
    """
    log_obj = logger if logger is not None else log

    if policy.max_attempts < 1:
        raise ValueError(
            f"RetryPolicy.max_attempts must be >= 1, got {policy.max_attempts}"
        )

    wait = tenacity.wait_exponential_jitter(
        initial=policy.initial_backoff_s,
        max=policy.max_backoff_s,
        jitter=policy.jitter,
    )
    stop = tenacity.stop_after_attempt(policy.max_attempts)

    retry_condition = tenacity.retry_if_exception(policy.is_retryable_exception)

    def _log_retry(retry_state: tenacity.RetryCallState) -> None:
        """Emit ``alarm_api.retry`` for each retry that actually sleeps."""
        outcome = retry_state.outcome
        exc = outcome.exception() if outcome is not None else None
        reason = (
            f"status_{exc.response.status_code}"
            if isinstance(exc, httpx.HTTPStatusError) and exc.response is not None
            else type(exc).__name__
            if exc is not None
            else "unknown"
        )
        method = "?"
        path = "?"
        if isinstance(exc, httpx.HTTPStatusError) and exc.request is not None:
            method = exc.request.method
            path = exc.request.url.path
        log_obj.info(
            "alarm_api.retry",
            attempt=retry_state.attempt_number,
            max_attempts=policy.max_attempts,
            reason=reason,
            method=method,
            path=path,
        )

    def decorator(fn: _RetryableCallable) -> _RetryableCallable:
        retrying = tenacity.AsyncRetrying(
            wait=wait,
            stop=stop,
            retry=retry_condition,
            reraise=True,
            before_sleep=_log_retry,
        )

        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            # ``AsyncRetrying.__call__`` runs the wrapped coroutine
            # in a loop, evaluating ``retry_condition`` after each
            # attempt. ``reraise=True`` re-raises the original
            # exception on exhaustion instead of tenacity's
            # ``RetryError`` wrapper — keeps the error envelope
            # identical to Feature 3.2 for the orchestrator.
            return await retrying(fn, *args, **kwargs)

        return wrapper  # type: ignore[return-value]

    return decorator


__all__ = [
    "RETRYABLE_STATUS_CODES",
    "RetryPolicy",
    "retry_with_policy",
]
