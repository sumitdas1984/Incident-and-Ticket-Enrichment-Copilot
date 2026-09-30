# Plan — Feature 3.3: MCP Reliability (Story 3.3.1)

> **Context.** Feature 3.2 (PR #78, merged) shipped the four Alarm Management MCP tools (`search_assets`, `get_alarm`, `summarize_alarms`, `recommend_actions`). The `AlarmApiClient` they all use already has bounded timeouts (5 s) and sanitised error mapping (`AlarmNotFoundError` for 404, generic `ToolInvocationError` for everything else) — but **no retries**. A single transient alarm-api blip surfaces to the LLM as a hard failure, and the orchestrator has no way to distinguish a transient outage from a permanent one.
>
> Feature 3.3 wraps `AlarmApiClient.get_json` / `post_json` in a bounded retry policy: exponential back-off with jitter, capped attempts, retry-on-5xx-and-transport, no-retry-on-4xx. Acceptance is set by Story [3.3.1](https://github.com/sumitdas1984/Incident-and-Ticket-Enrichment-Copilot/issues/43) and the parent Feature [3.3](https://github.com/sumitdas1984/Incident-and-Ticket-Enrichment-Copilot/issues/17).
>
> **What we don't do here**: circuit breakers (deferred to Feature 3.5 / orchestrator-side), per-tool policy overrides (single global policy keeps the four handlers uniform), or changing the four handlers.

---

## 1. Goal

- A single transient 5xx or connect/timeout error from the alarm-api is **silently retried** with bounded exponential back-off + jitter; the orchestrator only sees the final outcome.
- A 4xx (especially 404) is **never retried** — it surfaces immediately as `AlarmNotFoundError` / `ToolInvocationError`. We don't paper over a real client mistake.
- The bearer token, alarm-api URL with credentials, and stack traces never appear in any retry log or error envelope (current invariant must hold through the retry layer too).
- Defaults are configurable via `core.config.Settings` / `.env` without code changes — but the *interface* the four handlers depend on (`get_json` / `post_json`) stays unchanged.

---

## 2. Approach

Five concrete edits. The handlers in `tools.py` are untouched.

### 2.1 `pyproject.toml` — add `tenacity`

```toml
dependencies = [
    ...
    "tenacity>=8.2",
]
```

Tenacity is the most widely-used retry library in the Python async ecosystem; it gives us exponential back-off with jitter, decorator- and direct-call APIs, and a clean way to express which exception types are retryable. Rolling our own means re-implementing jitter, jitter cap, and exception filtering — yak shaving for the timebox.

### 2.2 `mcp-servers/alarm-management/retry.py` (NEW) — `RetryPolicy` + retry decorator

A small, testable policy module. Three things:

```python
@dataclass(frozen=True)
class RetryPolicy:
    max_attempts: int = 3
    initial_backoff_s: float = 0.25
    max_backoff_s: float = 2.0
    jitter: float = 0.1            # ±10 % of computed backoff

    @classmethod
    def from_settings(cls, settings: Settings) -> "RetryPolicy": ...

    def is_retryable_status(self, status_code: int) -> bool:
        return status_code in RETRYABLE_STATUS_CODES  # {408, 425, 429, 500, 502, 503, 504}

    def is_retryable_exception(self, exc: BaseException) -> bool:
        return isinstance(exc, (httpx.ConnectError, httpx.ReadTimeout, httpx.WriteTimeout,
                                httpx.PoolTimeout, httpx.RemoteProtocolError))

def retry_with_policy(policy: RetryPolicy): ...
```

The `retry_with_policy` factory wraps an async callable in a tenacity retry decorator. It uses `tenacity.AsyncRetrying` with:

- `stop_after_attempt(policy.max_attempts)` — bounded attempts (default 3: initial + 2 retries).
- `wait_exponential_jitter(initial=policy.initial_backoff_s, max=policy.max_backoff_s, jitter=policy.jitter)` — exponential back-off with full jitter.
- `retry_if_exception(_is_retryable_httpx)` — only retry on the documented transport exceptions.
- `retry_if_result(_is_retryable_status)` — only retry when the response's status code is retryable (we use a custom retry state that captures the status from the wrapped call's return value).

For the "retry on status code" case we use tenacity's `retry_if_result` hook: the wrapper catches `httpx.HTTPStatusError`, inspects the status, raises if non-retryable (so tenacity aborts), or returns the response object (so tenacity retries) if retryable. This keeps the handler-facing contract clean: `get_json` either returns the parsed body or raises the same exceptions as before.

### 2.3 `mcp-servers/alarm-management/alarm_api_client.py` — wire the policy

Wrap `get_json` / `post_json` internals in the retry decorator:

```python
class AlarmApiClient:
    def __init__(self, *, ..., retry_policy: RetryPolicy | None = None) -> None:
        ...
        self._retry_policy = retry_policy or RetryPolicy()

    async def get_json(self, path, *, params=None):
        @retry_with_policy(self._retry_policy)
        async def _do() -> dict[str, Any]:
            try:
                response = await self._client.get(path, params=params, headers=self._headers())
                response.raise_for_status()
            except httpx.HTTPStatusError as exc:
                # Retryable status -> return response so tenacity's
                # retry_if_result triggers a retry.
                # Non-retryable status -> raise the existing envelope.
                if self._retry_policy.is_retryable_status(exc.response.status_code):
                    return exc.response
                self._raise_for_status(exc)
            except httpx.HTTPError as exc:
                if self._retry_policy.is_retryable_exception(exc):
                    raise  # let tenacity catch and retry
                log.warning("alarm_api.transport_error", ...)
                raise ToolInvocationError("Upstream Alarm API call failed.") from exc
            return response.json()
        return await _do()
```

Key behavioural changes:

- **5xx / connect / timeout** → silent retry up to `max_attempts`; on exhaustion, the existing `ToolInvocationError` envelope fires.
- **4xx (except 408 / 425 / 429)** → no retry; surfaces immediately. 404 still maps to `AlarmNotFoundError` exactly as today.
- **Logging**: a single `alarm_api.retry` log line fires per retry with `attempt`, `backoff_s`, and `reason` so an operator can see *why* a retry happened without us leaking secrets.
- The `transport_error` log path for non-retryable transport errors (e.g. `httpx.InvalidURL`) is unchanged.

### 2.4 `core/config.py` + `.env.example` — settings + placeholders

Three new optional settings, all with sane defaults:

```python
# Settings
alarm_api_timeout_s: float = 5.0
alarm_api_max_attempts: int = 3
alarm_api_initial_backoff_s: float = 0.25
alarm_api_max_backoff_s: float = 2.0
```

```bash
# .env.example
ALARM_API_TIMEOUT_S=5.0
ALARM_API_MAX_ATTEMPTS=3
ALARM_API_INITIAL_BACKOFF_S=0.25
ALARM_API_MAX_BACKOFF_S=2.0
```

The constructor accepts a `RetryPolicy`; `from_settings()` builds one from the four new fields. Tests pass an explicit `RetryPolicy(max_attempts=2, initial_backoff_s=0.0, jitter=0.0)` so backoff timing is deterministic.

### 2.5 `tests/integration/mcp_server/test_retry.py` (NEW)

Twelve-ish tests covering:

1. **Retry on 5xx** — three 503s, then 200 → caller sees 200; alarm-api was called 4×.
2. **No retry on 4xx** — single 404 → caller sees `AlarmNotFoundError`; alarm-api was called once.
3. **Retry exhaustion** — three 503s → caller sees `ToolInvocationError`; alarm-api was called `max_attempts`×; no token in message.
4. **Retry on `ConnectError`** — two `ConnectError`s, then 200 → caller sees 200.
5. **No retry on `InvalidURL`** — surfaces immediately (deterministic, not transient).
6. **Backoff timing within bounds** — with `initial_backoff_s=0.1, max_backoff_s=0.4`, elapsed across `max_attempts=3` retries is ≤ `0.1 + 0.2 + 0.4 + jitter` (asserted with a generous upper bound to avoid flakiness).
7. **Retry header preserved** — `Authorization` and `X-Trace-Id` are unchanged across retries.
8. **Jitter is bounded** — computed backoff is within `±jitter` of the deterministic value, sampled across many attempts.
9. **`max_attempts=1` disables retry** — first failure surfaces immediately (parity with Feature 3.2 behaviour; default for tests).
10. **Retry on 408 / 425 / 429** — all retryable by policy.
11. **`AlarmNotFoundError` is not retried** — even if `max_attempts > 1`, 404 → 404.
12. **POST path is retried** — `recommend_actions` POSTs and the same retry envelope applies.

### 2.6 `docs/mcp-tool-catalog.md` — document the new behaviour

Add a **"Retry and timeout behaviour"** section under "Cross-cutting guarantees" so the orchestrator knows what to expect:

- Default policy: 3 attempts, 0.25 s → 2.0 s exponential back-off with ±10 % jitter.
- Retryable: 5xx (502/503/504 explicitly), 408, 425, 429, and the transport exceptions (`ConnectError`, `ReadTimeout`, `WriteTimeout`, `PoolTimeout`, `RemoteProtocolError`).
- Non-retryable: all other 4xx; `AlarmNotFoundError` surfaces on the first 404.
- Total worst-case latency per tool call: `(max_attempts × per-request timeout) + sum(backoff)` = `3 × 5 s + (0.25 + 0.5 + 1.0 + jitter) ≈ 17 s`.

The per-tool sections keep their existing language ("Sanitised ToolInvocationError envelope") — the new behaviour is strictly an internal resilience layer.

---

## 3. Non-goals

- **No circuit breaker.** A flapping alarm-api will still hammer it with retries; a circuit breaker would short-circuit when failure rate exceeds a threshold. That's a separate feature (and arguably belongs at the orchestrator level, not inside the MCP server).
- **No per-tool policy overrides.** All four tools share one `RetryPolicy`. Per-tool tuning isn't required by 3.3.1 and adds surface area for tests.
- **No retry on `POST /recommendations/operator-actions` from the LLM's point of view** — but the *transport-level* retry still applies. The alarm-api's recommendation endpoint is idempotent under a single `alarm_id`, so retrying it is safe.
- **No changes to the four tool handlers.** They keep using `client.get_json` / `client.post_json` exactly as today.
- **No changes to the alarm-api simulator.** The simulator is the system of record; we're hardening our wrapper.
- **No retry budget / cross-call backoff.** That's a resilience policy for the orchestrator to enforce.

---

## 4. Critical files

- `pyproject.toml` — add `"tenacity>=8.2"` to `dependencies` (1 line).
- `mcp-servers/alarm-management/retry.py` (NEW) — `RetryPolicy`, `RETRYABLE_STATUS_CODES`, `retry_with_policy`.
- `mcp-servers/alarm-management/alarm_api_client.py` (modified) — accept `retry_policy`; wrap `get_json` / `post_json` internals; new `alarm_api.retry` log line.
- `mcp-servers/alarm-management/__init__.py` (modified) — re-export `RetryPolicy`, `RETRYABLE_STATUS_CODES`.
- `mcp-servers/alarm-management/__main__.py` (modified) — wire `RetryPolicy.from_settings(get_settings())` into the `AlarmApiClient` constructed by `AlarmManagementLifespan`.
- `tests/integration/mcp_server/test_retry.py` (NEW) — twelve-ish tests covering retry/no-retry/backoff/secrets.
- `core/config.py` (modified) — four new optional `Settings` fields with defaults.
- `.env.example` (modified) — four new placeholders.
- `docs/mcp-tool-catalog.md` (modified) — new "Retry and timeout behaviour" section.

`connectors/`, `apps/`, `rag/`, `mcp-servers/alarm-management/tools.py`, `mcp-servers/alarm-management/registry.py` stay untouched.

---

## 5. Verification

1. **Static checks** (must pass before pushing):
   ```bash
   uv sync
   uv run ruff check .
   uv run mypy apps rag connectors core
   uv run pytest -ra
   ```
   Expect: 133 prior + ~12 new = ~145 tests green.

2. **Live behaviour** (recorded in PR description):
   - Start the MCP server (`uv run python -m mcp_servers.alarm_management`).
   - Stand up a stub alarm-api on port 18000 that returns 503 twice then 200 (a 30-line FastAPI app; not committed — described in the PR).
   - Drive `search_assets` through the official MCP client and observe the `alarm_api.retry` log lines on the server.

3. **Lint / types**: clean (see step 1).

4. **Documentation check**: `docs/mcp-tool-catalog.md` has the new section; no TODO markers.

---

## 6. Rollback

Trivial. `AlarmApiClient`'s constructor accepts `retry_policy: RetryPolicy | None = None`. Passing `RetryPolicy(max_attempts=1, initial_backoff_s=0.0)` restores Feature 3.2 behaviour exactly (no retries) without changing the four tool handlers. Reverting the `__main__.py` change that wires `RetryPolicy.from_settings(...)` does the same thing at the deployment level. No DB migrations, no API contract changes, no changes to the alarm-api simulator.

---

**Awaiting sign-off.** Reply "approved" to apply, or send edits.
