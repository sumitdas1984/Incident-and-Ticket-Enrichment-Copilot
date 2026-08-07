# MCP Tool Catalog — Alarm Management Server

> **Audience.** Copilot orchestrator (LLM-driven tool selection), GUI
> trace renderer, reviewers of the MCP integration. This document is
> the canonical per-tool reference for the four Alarm Management
> tools registered by `mcp-servers/alarm-management/`.

This document satisfies the Submission § 5 mandatory MCP documentation
requirement: every tool has purpose, input/output schema, auth behaviour,
source-system operation, error/timeout behaviour, and an example
invocation + response.

---

## Server summary

| Field            | Value                                                                |
|------------------|----------------------------------------------------------------------|
| Server name      | `alarm-management`                                                   |
| Transport        | Streamable HTTP over HTTP/1.1 (no TLS terminator in the container)   |
| Default port     | `9000` (configurable via `MCP_SERVER_PORT`)                          |
| Auth to upstream | Bearer token in `Authorization` header (from `ALARM_API_TOKEN`)      |
| Trace to upstream| `X-Trace-Id` header (from structlog contextvar set per-call)        |
| Health           | `GET /health` (liveness, always 200), `GET /ready` (probes alarm-api)|
| Tools shipped    | 4 — `search_assets`, `get_alarm`, `summarize_alarms`, `recommend_actions` |

The server is the **only** component in the orchestrator / app
stack that opens an `httpx.AsyncClient` to the Alarm API. The
orchestration layer reaches the API exclusively through MCP —
that's hard constraint #1 from the brief.

---

## 1. `search_assets`

Search industrial assets by name fragment with optional site / unit
filters. The primary entry point when an operator wants to find the
asset a recurring alarm belongs to.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "query": {
      "type": "string",
      "minLength": 1,
      "maxLength": 200,
      "description": "Asset name fragment (e.g. 'Boiler')."
    },
    "site": {
      "type": "string",
      "description": "Optional site code (e.g. 'EastRefinery')."
    },
    "unit": {
      "type": "string",
      "description": "Optional unit code (e.g. 'Cracker-1')."
    },
    "limit": {
      "type": "integer",
      "minimum": 1,
      "maximum": 100,
      "default": 10,
      "description": "Maximum number of results to return."
    }
  },
  "required": ["query"],
  "additionalProperties": false
}
```

### Output schema

```json
{
  "type": "object",
  "properties": {
    "results": {
      "type": "array",
      "items": { "$ref": "#/$defs/Asset" }
    },
    "total": { "type": "integer" },
    "query": { "type": "string" }
  },
  "required": ["results", "total", "query"]
}
```

Where `Asset` is `{ asset_id, name, site, unit?, asset_class?, metadata }`.
The wire format aliases the domain field `id` → `asset_id` (Postman
collection's chaining script depends on `asset_id`).

### Source-system operation

`GET <ALARM_API_BASE_URL>/assets/search?query=<q>&limit=<n>&site=<s>&unit=<u>`

Auth: `Authorization: Bearer <ALARM_API_TOKEN>` (forwarded unchanged).

### Auth & trace behaviour

- **Bearer token:** forwarded on the upstream call. Never logged,
  never included in the MCP error envelope. The `ToolContext` is
  unused at the handler level; the client reads `ALARM_API_TOKEN`
  from settings.
- **Trace propagation:** the active `trace_id` (bound by
  `@register_tool` via structlog's contextvar) is sent on the
  upstream request as `X-Trace-Id`. The alarm-api echoes it back
  on its response and includes it in any error envelope.
- **Pagination:** the alarm-api is not paginated for `/assets/search`
  — the `limit` parameter clamps the page size.

### Error / timeout behaviour

| Condition                          | Result                                                              |
|------------------------------------|---------------------------------------------------------------------|
| `query` empty or > 200 chars       | Pydantic `ValidationError` → `isError=True` with field details     |
| `limit` < 1 or > 100              | Pydantic `ValidationError` → `isError=True`                         |
| Upstream 2xx                       | Tool result = alarm-api JSON body                                   |
| Upstream 404                       | Generic `ToolInvocationError("Upstream … status 404.")`             |
| Upstream 5xx / 4xx                 | Generic `ToolInvocationError("Upstream … status <code>.")`          |
| Transport error (connect / timeout)| Sanitised `ToolInvocationError("Upstream Alarm API call failed.")`  |
| Upstream timeout (5 s)             | `httpx.TimeoutException` → mapped to sanitised `ToolInvocationError`|

In every error path the bearer token is **not** in the message.
The token may appear in server-side structured logs (debug level)
but is never surfaced to the MCP client.

### Example

Request:

```json
{
  "method": "tools/call",
  "params": {
    "name": "search_assets",
    "arguments": { "query": "Boiler", "site": "EastRefinery", "limit": 5 }
  }
}
```

Response:

```json
{
  "result": {
    "structuredContent": {
      "results": [
        {
          "asset_id": "AST-Boiler-1",
          "name": "Boiler 1",
          "site": "EastRefinery",
          "unit": "Cracker-1",
          "asset_class": "boiler",
          "metadata": {}
        }
      ],
      "total": 1,
      "query": "Boiler"
    },
    "isError": false
  }
}
```

---

## 2. `get_alarm`

Fetch a single alarm by id. Returns the canonical alarm record
(asset, severity, message, raised_at, acknowledgement status).

### Input schema

```json
{
  "type": "object",
  "properties": {
    "alarm_id": {
      "type": "string",
      "minLength": 1,
      "maxLength": 128,
      "description": "Alarm identifier returned by search / summarize."
    }
  },
  "required": ["alarm_id"],
  "additionalProperties": false
}
```

### Output schema

```json
{
  "type": "object",
  "properties": {
    "alarm_id":       { "type": "string" },
    "asset_id":       { "type": "string" },
    "severity":       { "type": "string", "enum": ["low", "medium", "high", "critical"] },
    "message":        { "type": "string" },
    "raised_at":      { "type": "string", "format": "date-time" },
    "acknowledged":   { "type": "boolean" }
  },
  "required": ["alarm_id", "asset_id", "severity", "message", "raised_at"]
}
```

### Source-system operation

`GET <ALARM_API_BASE_URL>/alarms/{alarm_id}`

Auth: `Authorization: Bearer <ALARM_API_TOKEN>`.

### Auth & trace behaviour

Same pattern as `search_assets` — bearer forwarded, `X-Trace-Id`
propagated, no token leakage.

### Error / timeout behaviour

| Condition                          | Result                                                              |
|------------------------------------|---------------------------------------------------------------------|
| `alarm_id` empty                   | Pydantic `ValidationError` → `isError=True`                         |
| Upstream 2xx                       | Tool result = alarm-api JSON body                                   |
| Upstream 404                       | `AlarmNotFoundError("Alarm <id> not found.")` (precise envelope)    |
| Upstream 5xx / 4xx                 | Generic `ToolInvocationError("Upstream … status <code>.")`          |
| Transport error (connect / timeout)| Sanitised `ToolInvocationError("Upstream Alarm API call failed.")`  |

`AlarmNotFoundError` is a subclass of `ToolInvocationError` so the
caller can distinguish "alarm unknown" from "alarm-api down" if
it needs to. The message carries the alarm_id for operator
clarity but never the alarm-api URL or bearer token.

### Example

Request:

```json
{
  "method": "tools/call",
  "params": {
    "name": "get_alarm",
    "arguments": { "alarm_id": "AL-100" }
  }
}
```

Response:

```json
{
  "result": {
    "structuredContent": {
      "alarm_id": "AL-100",
      "asset_id": "AST-Boiler-1",
      "severity": "high",
      "message": "Boiler shell temperature exceeded threshold",
      "raised_at": "2026-08-01T12:00:00Z",
      "acknowledged": false
    },
    "isError": false
  }
}
```

`AlarmNotFoundError` response:

```json
{
  "result": {
    "content": [{ "type": "text", "text": "Alarm AL-999 not found." }],
    "isError": true
  }
}
```

---

## 3. `summarize_alarms`

List ranked alarms with filters (site / asset / severity / time range).
Returns the most recent top-N (default 25) ordered by `raised_at desc`.
This is the "give me recent activity on this asset" tool.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "site":     { "type": "string",  "description": "Optional site code filter." },
    "asset":    { "type": "string",  "description": "Optional asset id filter." },
    "severity": { "type": "string",  "enum": ["low", "medium", "high", "critical"] },
    "since":    { "type": "string",  "format": "date-time", "description": "Inclusive lower bound on raised_at." },
    "until":    { "type": "string",  "format": "date-time", "description": "Inclusive upper bound on raised_at." },
    "limit":    { "type": "integer", "minimum": 1, "maximum": 500, "default": 25 }
  },
  "additionalProperties": false
}
```

All fields are optional. The handler maps `asset` → `asset_id`,
`since` → `start_time`, `until` → `end_time` at request-build time
so the MCP payload uses orchestrator-natural names.

### Output schema

```json
{
  "type": "object",
  "properties": {
    "data": {
      "type": "array",
      "items": { "$ref": "#/components/schemas/Alarm" }
    },
    "page":      { "type": "integer" },
    "page_size": { "type": "integer" },
    "total":     { "type": "integer" }
  },
  "required": ["data", "page", "page_size", "total"]
}
```

### Source-system operation

`GET <ALARM_API_BASE_URL>/alarms?site=...&asset_id=...&severity=...&start_time=...&end_time=...&page=1&page_size=<limit>&sort_by=raised_at&sort_order=desc`

Auth: `Authorization: Bearer <ALARM_API_TOKEN>`.

**Why `GET /alarms` (not `POST /alarms/summary`):** the story says
"ranked alarms with priority". `/alarms` returns ranked items
with priority metadata; `/alarms/summary` returns aggregated
buckets + KPIs (counts per group). The MCP surface ships the
ranked variant; `/alarms/summary` is reachable from the
orchestrator's advanced-ops layer (Feature 3.5) without exposing
a second tool here.

### Auth & trace behaviour

Same pattern as `search_assets` and `get_alarm`. Unset filters are
omitted from the upstream query string (e.g. omitting `site` means
the upstream sees no `site` parameter, not `site=`).

### Error / timeout behaviour

| Condition                          | Result                                                              |
|------------------------------------|---------------------------------------------------------------------|
| `severity` not in enum             | Pydantic `ValidationError` → `isError=True`                         |
| `since` / `until` not ISO 8601     | Pydantic `ValidationError` → `isError=True`                         |
| `limit` < 1 or > 500               | Pydantic `ValidationError` → `isError=True`                         |
| Upstream 2xx                       | Tool result = alarm-api JSON body                                   |
| Upstream 4xx / 5xx                 | Generic `ToolInvocationError("Upstream … status <code>.")`          |
| Transport error (connect / timeout)| Sanitised `ToolInvocationError("Upstream Alarm API call failed.")`  |

### Example

Request:

```json
{
  "method": "tools/call",
  "params": {
    "name": "summarize_alarms",
    "arguments": {
      "site": "EastRefinery",
      "asset": "AST-Boiler-1",
      "severity": "high",
      "since": "2026-07-01T00:00:00Z",
      "until": "2026-08-01T00:00:00Z",
      "limit": 10
    }
  }
}
```

Response:

```json
{
  "result": {
    "structuredContent": {
      "data": [
        {
          "alarm_id": "AL-100",
          "asset_id": "AST-Boiler-1",
          "severity": "high",
          "message": "Boiler shell temperature exceeded threshold",
          "raised_at": "2026-07-30T14:22:00Z",
          "acknowledged": true
        }
      ],
      "page": 1,
      "page_size": 10,
      "total": 1
    },
    "isError": false
  }
}
```

---

## 4. `recommend_actions`

Get recommended operator actions and a priority score for an
alarm. Returns `priority_score` (0-100), a list of recommended
actions, the rationale, and (when available) asset context and
historical pattern.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "alarm_id": {
      "type": "string",
      "minLength": 1,
      "maxLength": 128,
      "description": "Alarm identifier to score and recommend against."
    }
  },
  "required": ["alarm_id"],
  "additionalProperties": false
}
```

### Output schema

```json
{
  "type": "object",
  "properties": {
    "alarm_id":                   { "type": "string" },
    "priority_score":             { "type": "integer", "minimum": 0, "maximum": 100 },
    "actions":                    { "type": "array",  "items": { "type": "string" } },
    "rationale":                  { "type": "string" },
    "include_related":            { "type": "boolean" },
    "include_asset_context":      { "type": "boolean" },
    "include_historical_pattern": { "type": "boolean" }
  },
  "required": ["alarm_id", "priority_score", "actions"]
}
```

### Source-system operation

`POST <ALARM_API_BASE_URL>/recommendations/operator-actions`

Request body (set by the handler, not by the caller):

```json
{
  "alarm_id": "<from caller>",
  "include_related": false,
  "include_asset_context": true,
  "include_historical_pattern": true
}
```

Auth: `Authorization: Bearer <ALARM_API_TOKEN>`.

We always set `include_asset_context` and `include_historical_pattern`
to `true` because the alarm-api store fills them regardless when the
asset class / history matches; this gives the orchestrator the richest
payload for downstream reasoning. `include_related` stays `false`
— it requires a separate `/related-alarms` endpoint that isn't in scope.

### Auth & trace behaviour

Same pattern as the other tools. Bearer forwarded, `X-Trace-Id`
propagated, no token leakage.

### Error / timeout behaviour

| Condition                          | Result                                                              |
|------------------------------------|---------------------------------------------------------------------|
| `alarm_id` empty                   | Pydantic `ValidationError` → `isError=True`                         |
| Upstream 2xx                       | Tool result = alarm-api JSON body                                   |
| Upstream 404                       | `AlarmNotFoundError("Alarm <id> not found.")` (precise envelope)    |
| Upstream 4xx / 5xx                 | Generic `ToolInvocationError("Upstream … status <code>.")`          |
| Transport error (connect / timeout)| Sanitised `ToolInvocationError("Upstream Alarm API call failed.")`  |

### Example

Request:

```json
{
  "method": "tools/call",
  "params": {
    "name": "recommend_actions",
    "arguments": { "alarm_id": "AL-100" }
  }
}
```

Response:

```json
{
  "result": {
    "structuredContent": {
      "alarm_id": "AL-100",
      "priority_score": 87,
      "actions": [
        "Reduce load by 10%",
        "Inspect boiler shell temperature sensor S-12"
      ],
      "rationale": "Asset class boiler has high recurrence over the past 90 days.",
      "include_related": false,
      "include_asset_context": true,
      "include_historical_pattern": true
    },
    "isError": false
  }
}
```

---

## Cross-cutting guarantees

These apply to all four tools, not just one:

1. **Bearer token never appears in `isError` messages.** Verified
   by `tests/integration/mcp_server/test_tools.py` for both the
   happy path and every error envelope.

2. **Trace context propagates upstream.** Every outbound request
   carries `X-Trace-Id` from structlog's contextvar (the same id
   bound by `@register_tool`). The orchestrator can correlate a
   tool call with the alarm-api's own logs and any error
   envelope the alarm-api emits.

3. **Handlers are pure pass-throughs.** Each handler validates
   inputs, builds the upstream call via `AlarmApiClient`, and
   returns the parsed JSON body. No filtering, ranking, or
   aggregation happens inside the MCP server — the alarm-api is
   the system of record and the MCP layer is a typed wrapper.

4. **The `AlarmApiClient` is shared.** It is built once at server
   startup (`__main__.AlarmManagementLifespan.__aenter__`) and
   reused across every tool call so connections are pooled. It is
   closed on server shutdown.

5. **No retries, no streaming.** Both are explicitly out of scope
   here. Retries land in Feature 3.3 (MCP Reliability); they wrap
   `AlarmApiClient.get_json` / `post_json` without touching the
   four tool handlers.

---

## Versioning

This document is updated whenever a tool's input or output schema
changes. Versioned alongside the Python package
(`pyproject.toml`'s `version` field). Breaking changes require a
coordinated bump so the orchestrator's planner prompt and the
GUI trace pane can adapt.
