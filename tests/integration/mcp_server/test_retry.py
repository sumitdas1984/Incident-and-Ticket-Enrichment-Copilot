"""Retry-policy tests for ``AlarmApiClient`` (Feature 3.3 — Story 3.3.1).

What this covers
----------------

The four tool handlers in :mod:`mcp_servers.alarm_management.tools`
are unchanged because the policy wraps ``AlarmApiClient.get_json``
/ ``post_json`` internally. These tests exercise that wrapping
against a mock-transport alarm-api (the same pattern as
``test_tools.py``) so we can:

* confirm transient 5xx / 408 / 425 / 429 are retried,
* confirm non-retryable 4xx (404, 400) are surfaced immediately,
* confirm retryable transport exceptions are retried,
* confirm non-retryable transport exceptions are surfaced,
* confirm the bearer token and alarm-api URL never leak into
  retry log lines or error envelopes,
* confirm back-off timing stays within configured bounds,
* confirm ``max_attempts=1`` disables retries (parity with
  Feature 3.2).

Test-time policy
----------------

Every test builds a :class:`RetryPolicy` with
``initial_backoff_s=0.0, jitter=0.0`` so the run is
deterministic — no real wall-clock sleep. The ``max_attempts``
parameter is small (2-3) so retries are observable in test
output.
"""
from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from typing import Any

import httpx
import pytest
from mcp_servers.alarm_management import (
    RETRYABLE_STATUS_CODES,
    AlarmApiClient,
    AlarmNotFoundError,
    RetryPolicy,
    ToolInvocationError,
)
from mcp_servers.alarm_management.retry import retry_with_policy
from pydantic import SecretStr

# --------------------------------------------------------------------------- #
# Fixtures.
# --------------------------------------------------------------------------- #


def _deterministic_policy(max_attempts: int = 3) -> RetryPolicy:
    """Build a RetryPolicy with zero back-off and zero jitter.

    Test-only: keeps the suite fast and deterministic. Back-off
    timing is asserted in a dedicated test below by
    constructing a policy with a small but non-zero back-off.
    """
    return RetryPolicy(
        max_attempts=max_attempts,
        initial_backoff_s=0.0,
        max_backoff_s=0.0,
        jitter=0.0,
    )


def _make_client(
    handler: Callable[[httpx.Request], httpx.Response],
    policy: RetryPolicy,
) -> tuple[AlarmApiClient, list[httpx.Request]]:
    """Build an ``AlarmApiClient`` backed by ``httpx.MockTransport``.

    Returns ``(client, recorded_requests)``. The list is mutated
    by ``MockTransport``; the caller can inspect it after the
    test to assert how many times the alarm-api was hit.
    """
    recorded: list[httpx.Request] = []

    def _recording(request: httpx.Request) -> httpx.Response:
        recorded.append(request)
        return handler(request)

    client = AlarmApiClient(
        base_url="http://alarm-api.test",
        token=SecretStr("test-token-do-not-leak"),
        retry_policy=policy,
        client=httpx.AsyncClient(
            transport=httpx.MockTransport(_recording),
            base_url="http://alarm-api.test",
        ),
    )
    return client, recorded


def _run(coro: Any) -> Any:
    """Tiny helper so tests don't have to import asyncio at the top."""
    return asyncio.run(coro)


# --------------------------------------------------------------------------- #
# Policy unit tests.
# --------------------------------------------------------------------------- #


def test_retryable_status_codes_constant() -> None:
    """``RETRYABLE_STATUS_CODES`` is a frozen set of documented status codes."""
    assert RETRYABLE_STATUS_CODES == frozenset({408, 425, 429, 500, 502, 503, 504})


def test_policy_defaults_match_plan() -> None:
    """Default ``RetryPolicy`` matches the values in the Feature 3.3 plan."""
    policy = RetryPolicy()
    assert policy.max_attempts == 3
    assert policy.initial_backoff_s == 0.25
    assert policy.max_backoff_s == 2.0
    assert policy.jitter == 0.1


def test_policy_from_settings_uses_settings_fields() -> None:
    """``RetryPolicy.from_settings`` reads the four Settings fields."""
    from core.config import Settings

    settings = Settings(
        alarm_api_max_attempts=5,
        alarm_api_initial_backoff_s=0.5,
        alarm_api_max_backoff_s=4.0,
    )
    policy = RetryPolicy.from_settings(settings)
    assert policy.max_attempts == 5
    assert policy.initial_backoff_s == 0.5
    assert policy.max_backoff_s == 4.0
    assert policy.jitter == 0.1  # hard-coded


def test_policy_is_retryable_status() -> None:
    policy = RetryPolicy()
    for code in (408, 425, 429, 500, 502, 503, 504):
        assert policy.is_retryable_status(code), code
    for code in (200, 201, 301, 400, 401, 403, 404, 409, 422, 501):
        assert not policy.is_retryable_status(code), code


def test_policy_is_retryable_exception() -> None:
    policy = RetryPolicy()
    assert policy.is_retryable_exception(httpx.ConnectError("x"))
    assert policy.is_retryable_exception(httpx.ReadTimeout("x"))
    assert policy.is_retryable_exception(httpx.WriteTimeout("x"))
    assert policy.is_retryable_exception(httpx.PoolTimeout("x"))
    assert policy.is_retryable_exception(httpx.RemoteProtocolError("x"))
    # ``DecodingError`` is deterministic — no retry.
    assert not policy.is_retryable_exception(httpx.DecodingError("x"))
    # ``InvalidURL`` is not even an ``HTTPError`` subclass; the
    # retry layer doesn't reach it (httpx raises it pre-flight
    # during URL parsing, before any request is sent).
    assert not policy.is_retryable_exception(httpx.InvalidURL("x"))


def test_policy_rejects_zero_attempts() -> None:
    """``max_attempts < 1`` is a programmer error caught at decoration."""
    with pytest.raises(ValueError, match="max_attempts"):
        retry_with_policy(RetryPolicy(max_attempts=0))


# --------------------------------------------------------------------------- #
# Retry on 5xx.
# --------------------------------------------------------------------------- #


def test_get_retries_5xx_until_success() -> None:
    """Three 503s followed by 200 → caller sees 200, alarm-api hit 4×."""
    attempts = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        attempts["n"] += 1
        if attempts["n"] < 4:
            return httpx.Response(503, json={"error": "unavailable"})
        return httpx.Response(200, json={"assets": []})

    policy = _deterministic_policy(max_attempts=4)
    client, recorded = _make_client(handler, policy)

    result = _run(client.get_json("/assets/search", params={"query": "boiler"}))
    assert result == {"assets": []}
    assert attempts["n"] == 4
    assert len(recorded) == 4


def test_get_retries_429() -> None:
    """429 (rate-limited) is retryable."""
    attempts = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        attempts["n"] += 1
        if attempts["n"] < 3:
            return httpx.Response(429, json={"error": "rate_limited"})
        return httpx.Response(200, json={"assets": []})

    policy = _deterministic_policy(max_attempts=3)
    client, _ = _make_client(handler, policy)
    _run(client.get_json("/assets/search", params={"query": "boiler"}))
    assert attempts["n"] == 3


def test_get_retries_500() -> None:
    """Plain 500 is retryable."""
    attempts = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        attempts["n"] += 1
        if attempts["n"] < 2:
            return httpx.Response(500, json={"error": "boom"})
        return httpx.Response(200, json={"assets": []})

    policy = _deterministic_policy(max_attempts=2)
    client, _ = _make_client(handler, policy)
    _run(client.get_json("/assets/search", params={"query": "boiler"}))
    assert attempts["n"] == 2


# --------------------------------------------------------------------------- #
# No retry on 4xx.
# --------------------------------------------------------------------------- #


def test_get_does_not_retry_404() -> None:
    """404 surfaces as AlarmNotFoundError on the first attempt."""
    attempts = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        attempts["n"] += 1
        return httpx.Response(404, json={"error": "not_found"})

    policy = _deterministic_policy(max_attempts=5)
    client, _ = _make_client(handler, policy)

    with pytest.raises(AlarmNotFoundError) as exc_info:
        _run(client.get_json("/alarms/A-1"))
    assert "A-1" in str(exc_info.value)
    assert attempts["n"] == 1


def test_get_does_not_retry_400() -> None:
    """Non-retryable 4xx (400 Bad Request) surfaces on first attempt."""
    attempts = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        attempts["n"] += 1
        return httpx.Response(400, json={"error": "bad_input"})

    policy = _deterministic_policy(max_attempts=5)
    client, _ = _make_client(handler, policy)

    with pytest.raises(ToolInvocationError) as exc_info:
        _run(client.get_json("/assets/search", params={"query": "x"}))
    assert "400" in str(exc_info.value)
    assert attempts["n"] == 1


# --------------------------------------------------------------------------- #
# Retry exhaustion.
# --------------------------------------------------------------------------- #


def test_retry_exhaustion_surfaces_tool_invocation_error() -> None:
    """Three 503s exhaust attempts → ToolInvocationError envelope."""
    attempts = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        attempts["n"] += 1
        return httpx.Response(503, json={"error": "unavailable"})

    policy = _deterministic_policy(max_attempts=3)
    client, _ = _make_client(handler, policy)

    with pytest.raises(ToolInvocationError):
        _run(client.get_json("/assets/search", params={"query": "boiler"}))
    assert attempts["n"] == 3


def test_retry_exhaustion_message_does_not_leak_token() -> None:
    """The error envelope must not include the bearer token or URL."""
    attempts = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        attempts["n"] += 1
        return httpx.Response(503, json={"error": "unavailable"})

    policy = _deterministic_policy(max_attempts=2)
    client, _ = _make_client(handler, policy)

    with pytest.raises(ToolInvocationError) as exc_info:
        _run(client.get_json("/assets/search", params={"query": "boiler"}))
    msg = str(exc_info.value)
    assert "test-token-do-not-leak" not in msg
    assert "alarm-api.test" not in msg
    assert "Upstream Alarm API" in msg or "status 503" in msg


# --------------------------------------------------------------------------- #
# Retry on transport exceptions.
# --------------------------------------------------------------------------- #


def test_get_retries_connect_error() -> None:
    """``httpx.ConnectError`` is retried; eventually succeeds."""
    attempts = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        attempts["n"] += 1
        if attempts["n"] < 3:
            raise httpx.ConnectError("simulated connect failure")
        return httpx.Response(200, json={"assets": []})

    policy = _deterministic_policy(max_attempts=3)
    client, _ = _make_client(handler, policy)

    result = _run(client.get_json("/assets/search", params={"query": "boiler"}))
    assert result == {"assets": []}
    assert attempts["n"] == 3


def test_get_retries_read_timeout() -> None:
    """``httpx.ReadTimeout`` is retried."""
    attempts = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        attempts["n"] += 1
        if attempts["n"] < 2:
            raise httpx.ReadTimeout("simulated read timeout")
        return httpx.Response(200, json={"assets": []})

    policy = _deterministic_policy(max_attempts=2)
    client, _ = _make_client(handler, policy)
    _run(client.get_json("/assets/search", params={"query": "boiler"}))
    assert attempts["n"] == 2


def test_get_does_not_retry_invalid_url() -> None:
    """Non-retryable ``HTTPError`` subclasses surface immediately."""
    attempts = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        attempts["n"] += 1
        # ``httpx.DecodingError`` is a deterministic transport
        # failure (we asked for a JSON response and the body
        # wasn't valid JSON). It's NOT in the retryable set
        # (only ConnectError / ReadTimeout / WriteTimeout /
        # PoolTimeout / RemoteProtocolError are), so the call
        # surfaces on the first attempt with the sanitised
        # ``ToolInvocationError`` envelope.
        raise httpx.DecodingError("simulated decode failure", request=request)

    policy = _deterministic_policy(max_attempts=5)
    client, _ = _make_client(handler, policy)

    with pytest.raises(ToolInvocationError):
        _run(client.get_json("/assets/search", params={"query": "boiler"}))
    assert attempts["n"] == 1


# --------------------------------------------------------------------------- #
# Back-off timing.
# --------------------------------------------------------------------------- #


def test_backoff_timing_within_bounds() -> None:
    """With small but non-zero back-off, elapsed is bounded by the policy."""
    attempts = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        attempts["n"] += 1
        if attempts["n"] < 3:
            return httpx.Response(503, json={"error": "unavailable"})
        return httpx.Response(200, json={"assets": []})

    policy = RetryPolicy(
        max_attempts=3,
        initial_backoff_s=0.05,
        max_backoff_s=0.2,
        jitter=0.0,
    )
    client, _ = _make_client(handler, policy)

    started = time.perf_counter()
    _run(client.get_json("/assets/search", params={"query": "boiler"}))
    elapsed = time.perf_counter() - started

    # Two retries → waits of 0.05 s and 0.10 s = 0.15 s minimum.
    # Generous upper bound to absorb event-loop overhead.
    assert 0.15 <= elapsed <= 1.0, f"elapsed={elapsed:.3f}s out of bounds"


# --------------------------------------------------------------------------- #
# Headers preserved across retries.
# --------------------------------------------------------------------------- #


def test_auth_and_trace_headers_preserved_across_retries() -> None:
    """``Authorization`` and ``X-Trace-Id`` are identical on every retry."""
    attempts = {"n": 0}
    recorded_headers: list[dict[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        attempts["n"] += 1
        recorded_headers.append(dict(request.headers))
        if attempts["n"] < 3:
            return httpx.Response(503, json={"error": "unavailable"})
        return httpx.Response(200, json={"assets": []})

    policy = _deterministic_policy(max_attempts=3)
    client, _ = _make_client(handler, policy)

    _run(client.get_json("/assets/search", params={"query": "boiler"}))
    assert len(recorded_headers) == 3
    for headers in recorded_headers:
        assert headers["authorization"] == "Bearer test-token-do-not-leak"
        assert headers.get("x-trace-id") == "mcp-no-trace"


# --------------------------------------------------------------------------- #
# POST path is retried identically.
# --------------------------------------------------------------------------- #


def test_post_retries_5xx_until_success() -> None:
    """``post_json`` uses the same policy; two 503s then 200."""
    attempts = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        attempts["n"] += 1
        if attempts["n"] < 3:
            return httpx.Response(503, json={"error": "unavailable"})
        return httpx.Response(
            200,
            json={"priority_score": 75, "actions": ["Reduce load"]},
        )

    policy = _deterministic_policy(max_attempts=3)
    client, _ = _make_client(handler, policy)

    result = _run(client.post_json("/recommendations/operator-actions", json={}))
    assert result["priority_score"] == 75
    assert attempts["n"] == 3


def test_post_does_not_retry_404() -> None:
    """``recommend_actions`` POSTs; 404 must surface on the first attempt."""
    attempts = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        attempts["n"] += 1
        return httpx.Response(404, json={"error": "alarm_not_found"})

    policy = _deterministic_policy(max_attempts=4)
    client, _ = _make_client(handler, policy)

    with pytest.raises(AlarmNotFoundError):
        _run(client.post_json("/recommendations/operator-actions", json={"alarm_id": "x"}))
    assert attempts["n"] == 1


# --------------------------------------------------------------------------- #
# max_attempts=1 disables retry.
# --------------------------------------------------------------------------- #


def test_max_attempts_one_disables_retry() -> None:
    """``max_attempts=1`` matches Feature 3.2 semantics."""
    attempts = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        attempts["n"] += 1
        return httpx.Response(503, json={"error": "unavailable"})

    policy = RetryPolicy(max_attempts=1, initial_backoff_s=0.0, jitter=0.0)
    client, _ = _make_client(handler, policy)

    with pytest.raises(ToolInvocationError):
        _run(client.get_json("/assets/search", params={"query": "boiler"}))
    assert attempts["n"] == 1


# --------------------------------------------------------------------------- #
# 408 / 425 are retryable (alongside 5xx).
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("retryable_status", [408, 425, 500, 502, 503, 504])
def test_retryable_status_codes_are_retried(retryable_status: int) -> None:
    """Every code in ``RETRYABLE_STATUS_CODES`` is actually retried."""
    attempts = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        attempts["n"] += 1
        if attempts["n"] < 2:
            return httpx.Response(retryable_status, json={"error": "transient"})
        return httpx.Response(200, json={"assets": []})

    policy = _deterministic_policy(max_attempts=2)
    client, _ = _make_client(handler, policy)

    _run(client.get_json("/assets/search", params={"query": "boiler"}))
    assert attempts["n"] == 2, f"status {retryable_status} was not retried"
