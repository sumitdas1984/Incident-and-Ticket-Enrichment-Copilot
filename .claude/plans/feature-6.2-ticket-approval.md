# Plan — Feature 6.2: Ticket Approval (Story 6.2.1)

> **Context.** Feature 6.1 ships the ticket service and the orchestrator's `create_ticket_draft` MCP tool. The orchestrator already passes the `approved` flag from the chain payload. But hard constraint #3 ("ticket / issue creation is a write operation; it must require explicit user confirmation in the GUI before the MCP server is invoked") is not yet enforced. The MCP tool today silently creates the ticket if `approved=True` and silently returns a preview if `approved=False`. We need a hard fail-closed at the ticket-mock: any `create_ticket_draft` call **without** the `approved` flag, or with `approved=False`, must be rejected with a structured error — no draft, no write, no record. Approvals must also produce an auditable trail (who approved, when, which ticket id) so a reviewer can prove the write was sanctioned.
>
> **Parent issues:** Epic 6 — Ticket Management — `#7`; Feature 6.2 — `#23`; Story 6.2.1 — `#55` (sub-issue of #23).
>
> **What we don't do here:** GUI rendering of the confirmation modal (Feature 7.2); the orchestrator already passes the flag — no change to the orchestrator's chain runner; no change to the MCP client. The work is concentrated in `connectors/ticket_mock/`.
>
> **What we explicitly do:** hard-fail the `create_ticket_draft` HTTP endpoint when `approved` is missing or `False`; append an in-memory audit log entry on every successful ticket creation; expose `GET /tickets/audit` for the GUI; surface the approval state in the orchestrator's MCP execution trace so the trace tells the reviewer whether the write was sanctioned.

---

## 1. Goal

A FastAPI run that:

1. Rejects any `POST /tickets/draft` call whose body lacks `approved` (defaults to `False` are explicit rejections) with a structured `403` envelope. The error body carries `{code, message, requires_approval, request_id}` so the orchestrator (or GUI) can surface a clear "this write needs approval" message.
2. Accepts `POST /tickets/draft` only when `approved=True`. On success, the response carries the assigned `ticket_id` plus an `approval` block: `{approved_by, approved_at, request_id}`.
3. Persists an in-memory `AuditEntry` for every successful ticket creation. The audit list is exposed at `GET /tickets/audit` and is bounded by the in-memory store's lifetime (documented as a known limitation).
4. Surfaces the approval state in the orchestrator's MCP execution trace: the `TraceStep` for `create_ticket_draft` carries `approved_by` and `request_id` in its metadata. The orchestrator's chain runner already attaches metadata to `TraceStep.output` — we extend the protocol slightly to thread approval info through.

---

## 2. Approach

### 2.1 `connectors/ticket_mock/models.py` — new shapes

```python
class TicketApprovalRequiredError(BaseModel):
    """The wire shape of an approval-gate rejection."""
    model_config = ConfigDict(extra="forbid")
    code: Literal["approval_required"] = "approval_required"
    message: str
    request_id: str
    requires_approval: Literal[True] = True


class TicketApprovalInfo(BaseModel):
    """Audit fields attached to a successful ticket creation."""
    model_config = ConfigDict(extra="forbid")
    approved_by: str
    approved_at: datetime
    request_id: str


class AuditEntry(BaseModel):
    """One row in the in-memory audit log."""
    model_config = ConfigDict(extra="forbid")
    id: str  # a uuid4 hex
    ticket_id: str
    request_id: str
    approved_by: str
    approved_at: datetime
    incident_id: str | None = None
    action: Literal["create_ticket"] = "create_ticket"


class AuditListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    items: list[AuditEntry]
    total: int
```

The `TicketDraftResponse` gains an `approval: TicketApprovalInfo | None` field — `None` for preview drafts (which the orchestrator never invokes in production), populated on every persisted ticket.

### 2.2 `connectors/ticket_mock/store.py` — audit list on the store

The `TicketStore` already owns the persistence layer. Adding an in-memory audit list next to the tickets:

```python
class TicketStore:
    def __init__(self) -> None:
        ...
        self._audit: list[AuditEntry] = []

    def append_audit(self, entry: AuditEntry) -> None: ...
    def list_audit(self) -> list[AuditEntry]: ...
```

The store allocates `AuditEntry.id` (uuid4 hex) and provides the timestamp. Thread-safe via the existing `threading.Lock`.

### 2.3 `connectors/ticket_mock/routers/tickets.py` — gate + audit endpoint

`POST /tickets/draft` becomes fail-closed:

```python
@router.post("/draft", response_model=TicketDraftResponse)
def draft_endpoint(request: Request, body: TicketDraftRequest):
    if not body.approved:
        # The caller must explicitly opt in. This is the hard constraint
        # #3 enforcement point.
        raise HTTPException(
            status_code=403,
            detail=TicketApprovalRequiredError(
                message="ticket creation requires explicit approval",
                request_id=str(uuid.uuid4()),
            ).model_dump(),
        )
    ...
    # Persist ticket + append audit entry
    request_id = str(uuid.uuid4())
    audit = AuditEntry(
        id=str(uuid.uuid4()),
        ticket_id=ticket_id,
        request_id=request_id,
        approved_by=settings.approval_user,
        approved_at=now,
        incident_id=body.incident.get("id"),
    )
    store.append_audit(audit)
    return draft.model_copy(update={"ticket_id": ticket_id, "preview": False, "approval": ...})


@router.get("/audit", response_model=AuditListResponse)
def list_audit(request: Request, limit: int = Query(50, ge=1, le=200)) -> AuditListResponse:
    return AuditListResponse(items=store.list_audit()[:limit], total=len(store.list_audit()))
```

`GET /tickets/audit` is open-bearer (the bearer auth on the router is already in place).

### 2.4 `core/config.py` — approval_user

```python
approval_user: str = "operator"  # APPROVAL_USER env var override
```

Settings already lists all the other role-shaped env vars; this slots in.

### 2.5 MCP tool — pass-through

`mcp-servers/ticketing/tools.py::create_ticket_draft` is unchanged. The MCP call still goes through `httpx` to the ticket-mock, but the service now returns `403` if `approved=False`. The MCP transport maps that to `is_error=True` on `CallToolResult` — the orchestrator's chain runner already records `outcome="error"` for that case. The orchestrator's trace step carries the 403 envelope in `error`.

The orchestrator's `apps/backend/orchestrator/routes.py` already extracts `draft.get("ticket_id")` and `draft.get("preview")`. We extend the trace to attach `approved_by` and `request_id` to the `TraceStep.output` so the audit trail is visible in the orchestrator's response. Implementation: `_call_mcp` already passes the tool's response through verbatim; we just enrich the `TraceStep` with the audit fields after a successful call. The change is local to `apps/backend/orchestrator/chain.py`.

### 2.6 Tests

**Unit (`tests/unit/`):**

| File | Coverage |
|---|---|
| `connectors/ticket_mock/test_audit.py` (NEW) | Audit list append / list / ordering; thread-safety. |
| `connectors/ticket_mock/test_draft.py` (extend) | `approved=False` → 403 with `code="approval_required"`. `approved=True` → 200 + audit row. `approved` field omitted from the request body → 403. |
| `orchestrator/test_ticket_step.py` (extend) | When the MCP returns a 403 envelope, the chain's `TraceStep` has `outcome="error"`. When the MCP returns the persisted ticket, the chain surfaces `approved_by` in the response. |

**Integration (`tests/integration/`):**

| File | Coverage |
|---|---|
| `ticket_mock/test_endpoints.py` (extend) | `POST /tickets/draft` with `approved=False` returns 403. `POST` with `approved=True` returns 200 + audit row visible at `GET /tickets/audit`. |
| `mcp_server_ticketing/test_tools.py` (extend) | `create_ticket_draft` tool call with `approved=False` returns `is_error=True`. |
| `test_orchestrator_ticket_e2e.py` (extend) | End-to-end: orchestrator's `POST /tickets/draft` with `approved=False` returns the rejection envelope. With `approved=True` the response carries `ticket_id` and `approval.approved_by`. |

Expected test count delta: ~12 new tests. Total: ~384 + 12 = ~396.

### 2.7 Non-goals

- **No persistent audit log.** In-memory is consistent with the ticket store; SQLite is a future story.
- **No per-user identity.** A single configured `APPROVAL_USER` is the demo. Epic 7 derives the identity from auth.
- **No chain-runner changes beyond the trace metadata.** The dispatch logic is unchanged; the only addition is the `approved_by` / `request_id` metadata on the success trace step.
- **No MCP client changes.** The MCP wire surface is unchanged; the new failure mode is a `ToolInvocationError` with the `approval_required` envelope.

### 2.8 Dependencies

No new runtime dependencies. The audit list lives in the existing in-memory store.

---

## 3. Critical files

### New

- `tests/unit/connectors/ticket_mock/test_audit.py`

### Modified

- `connectors/ticket_mock/models.py` — add `TicketApprovalRequiredError`, `TicketApprovalInfo`, `AuditEntry`, `AuditListResponse`. Extend `TicketDraftResponse` with `approval: TicketApprovalInfo | None`.
- `connectors/ticket_mock/store.py` — add `_audit` list, `append_audit`, `list_audit`.
- `connectors/ticket_mock/routers/tickets.py` — `POST /draft` returns 403 when `approved=False`; `GET /audit` endpoint.
- `core/config.py` — `approval_user: str = "operator"` (env `APPROVAL_USER`).
- `apps/backend/orchestrator/chain.py` — extract `approved_by` + `request_id` from the tool's response and attach to the success `TraceStep.output`.
- `tests/unit/connectors/ticket_mock/test_draft.py` (extend) — the 403 path.
- `tests/unit/orchestrator/test_ticket_step.py` (extend) — the 403 trace-step path.
- `tests/integration/ticket_mock/test_endpoints.py` (extend) — the 403 + audit-list paths.
- `tests/integration/mcp_server_ticketing/test_tools.py` (extend) — the `is_error=True` mapping.
- `tests/integration/test_orchestrator_ticket_e2e.py` (extend) — end-to-end.

### Untouched

- `mcp-servers/ticketing/tools.py` — the tool is unchanged; the service does the gating.
- `apps/backend/orchestrator/mcp_client.py` — the client is generic.
- `apps/backend/orchestrator/planner.py` — the planner's emission is unchanged.
- `rag/`, `core/domain.py` — no domain changes.

### Patterns to reuse (with file paths)

- `connectors/alarm_api/errors.py::install_handlers` — the structured error envelope pattern.
- `connectors/ticket_mock/store.py::TicketStore` — the existing thread-safe store pattern.
- `mcp-servers/alarm-management/registry.py::register_tool` — the tool decorator.
- `apps/backend/orchestrator/chain.py::_call_mcp` — the shared dispatch helper.

---

## 4. Verification

1. **Static gates:**
   ```bash
   uv run ruff check .
   uv run mypy --explicit-package-bases apps rag connectors core
   uv run pytest -ra
   ```
   Expect: ~396 passed (384 + 12 new). mypy clean.

2. **Live smoke (unapproved):**
   ```bash
   curl -X POST http://localhost:8000/tickets/draft \
     -H 'authorization: Bearer test-token' \
     -H 'content-type: application/json' \
     -d '{"incident": {"id": "INC-1", "title": "x", "severity": "high"}}'
   ```
   Expect: 403 with body `{"code": "approval_required", "message": "...", "request_id": "...", "requires_approval": true}`.

3. **Live smoke (approved):**
   ```bash
   curl -X POST http://localhost:8000/tickets/draft \
     -H 'authorization: Bearer test-token' \
     -H 'content-type: application/json' \
     -d '{"incident": {"id": "INC-1", "title": "x", "severity": "high"}, "approved": true}'
   curl http://localhost:8000/tickets/audit -H 'authorization: Bearer test-token'
   ```
   Expect: 200 with `ticket_id` and `approval.approved_by = "operator"`. Audit endpoint returns the entry.

4. **Orchestrator smoke:**
   ```bash
   curl -X POST http://localhost:8001/tickets/draft \
     -H 'content-type: application/json' \
     -d '{"incident": {...}, "approved": false}'
   ```
   Expect: 502 with the 403 envelope echoed in the orchestrator's trace. The response's `trace[0].outcome = "error"`.

5. **Live HTTP (docker-compose):** all four services up; the `/tickets/draft` without `approved=True` round-trips through the orchestrator → ticket-MCP → ticket-mock and surfaces the rejection.

---

## 5. Rollback

Trivial. The gate is additive in `connectors/ticket_mock/routers/tickets.py::draft_endpoint` — removing the `if not body.approved: raise` line restores the pre-PR behavior. The audit append is a separate operation; removing it doesn't affect ticket creation.

---

## 6. Branch + PR

- Branch: `feature/feature-6.2-ticket-approval` (off `developer` at the post-6.1 merge).
- Single PR closes `#55` (Story 6.2.1).

---

**Awaiting sign-off.** Reply "approved" to apply, or send edits.
