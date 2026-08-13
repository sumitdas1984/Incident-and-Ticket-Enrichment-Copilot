# Feature 7.2 — Incident Workspace

> **Context.** Feature 7.1 shipped a chat-only Streamlit GUI
> (`apps/frontend/ui.py`). The brief (`Assignment_Use_Case.md` § 4 GUI
> expectations) wants a **workspace** alongside the chat: structured
> incident summary, editable ticket draft, document citations panel,
> MCP execution trace panel, and a ticket-confirmation modal that
> persists through the existing approval-gated `POST /tickets/draft`.
> Hard constraint #3 ("ticket creation is a write operation; explicit
> user confirmation in the GUI") makes the modal non-optional.
>
> Issue #25 (Feature 7.2) and its three sub-issues (#58, #59, #60) are
> open and block Feature 9.2 (demo video).
>
> **Outcome.** Two sequential PRs:
> 1. **PR 1 (server)** — adds `POST /tickets/preview` so the GUI can
>    show a draft before persisting. No GUI changes. Closes part of
>    Story 7.2.1.
> 2. **PR 2 (GUI)** — adds the workspace column (summary + editable
>    draft + citations panel + MCP trace panel), the confirmation
>    modal, and the loading/empty/error states. Closes Stories 7.2.1
>    (editable draft half), 7.2.2, 7.2.3, and the modal half of
>    Story 7.2.1.

---

## Why split server and client into two PRs

The previous single-PR plan mixed a new backend endpoint with new GUI
panels and a new HTTP client module. That's a wide diff with three
different reviewers in mind (backend, frontend, infra). Splitting it:

* **PR 1** is reviewable on its own. It's one new endpoint, two new
  Pydantic envelopes, one integration test file. Server-only.
* **PR 2** is the GUI surface — once PR 1 lands, the GUI can call the
  preview endpoint without depending on a chain stub. The GUI tests
  exercise the real backend via `apps.backend.create_app()`.

Both PRs land on `developer`. The brief's required-by (Feature 9.2)
gets both merged before the demo recording starts.

---

## PR 1 — `/tickets/preview` endpoint (server)

### Files modified / created

| Action | Path | Purpose |
|---|---|---|
| modify | `apps/backend/orchestrator/request.py` | `TicketPreviewRequest`, `TicketPreviewResponse` envelopes. |
| modify | `apps/backend/routes.py` | `POST /tickets/preview` route handler. |
| new | `tests/integration/test_ticket_preview.py` | Integration tests for the new endpoint. |
| modify | `tests/integration/test_orchestrator_ticket_e2e.py` | (optional) Add a regression test that `/tickets/draft` is unchanged. |

### Endpoint contract

`POST /tickets/preview` accepts `TicketPreviewRequest{ incident: dict }`
and returns `TicketPreviewResponse{ title, body, severity, assignee,
labels, incident_id }`. The handler calls
`connectors.ticket_mock.draft.build_draft(req.incident, approved=False)`
directly — no MCP, no chain runner, no audit row, no conversation-store
append.

### Why this is the right backend change

* Reuses `build_draft()` (the same function the chain invokes through
  the MCP tool), so the GUI sees the exact text the chain would have
  generated.
* No new dependencies — `connectors.ticket_mock` is already a project
  package.
* No new env vars.
* Doesn't touch Feature 6.2's approval gate (`/tickets/draft` is
  unchanged).

### Tests (`tests/integration/test_ticket_preview.py`)

* 200 + valid envelope for a representative incident payload.
* `title` from `incident.title`; `body` from `summary` + actions;
  `severity` falls back to `medium` when missing.
* `assignee` is `None` (matches `build_draft()` behaviour).
* `labels` includes `severity:*` and `related:*` for each
  `similar_tickets` id.
* `incident_id` echoes `incident["id"]`.
* No MCP call happens (asserted via a stubbed-out MCP client — the
  integration test never boots the alarm-management or ticketing MCP
  servers, mirroring `test_orchestrator_ticket_e2e.py`'s pattern).
* `/tickets/draft` (existing) is unchanged.

### Verification

```
uv run ruff check .
uv run mypy --explicit-package-bases apps rag connectors core
uv run pytest -ra tests/integration/test_ticket_preview.py
```

Smoke: `uv run apps/backend` then `curl -X POST
http://localhost:8000/tickets/preview -d '{"incident": {...}}'` → 200.

---

## PR 2 — Workspace column + confirmation modal (GUI)

### Files modified / created

| Action | Path | Purpose |
|---|---|---|
| new | `apps/frontend/ticket_client.py` | Typed HTTP client for `/tickets/preview` and `/tickets/draft`. |
| modify | `apps/frontend/ui.py` | Two-column layout; workspace panels; confirmation modal. |
| new | `tests/unit/frontend/test_ticket_client.py` | `httpx.MockTransport` unit tests. |
| new | `tests/unit/frontend/test_workspace_smoke.py` | Streamlit `AppTest` smoke for the workspace column. |
| modify | `tests/unit/frontend/test_ui_smoke.py` | Extend chat tests to assert the workspace column. |
| new | `tests/integration/test_workspace_e2e.py` | Real backend + AppTest end-to-end for the modal flow. |

### Layout

```
┌──────────────────────────┬──────────────────────────────────────────┐
│  Chat column             │  Workspace column (Story 7.2.1 + 7.2.2)  │
│  (Feature 7.1,           │                                          │
│   unchanged)             │  ┌─ 📋 Incident summary ────────────────┐ │
│                          │  │ title · severity · asset · site ·    │ │
│  ┌────────────────────┐  │  │ likely_cause · recommended_actions   │ │
│  │ User: investigate  │  │  │ similar_tickets                       │ │
│  │ boiler B-101…      │  │  └──────────────────────────────────────┘ │
│  └────────────────────┘  │                                          │
│  ┌────────────────────┐  │  ┌─ ✏️ Editable ticket draft ────────────┐ │
│  │ Assistant: …       │  │  │ title      [____________]              │ │
│  │ [Citations (N)]    │  │  │ severity   [low|med|high|crit ▼]      │ │
│  │ [Trace (N)]        │  │  │ body       [_________________]         │ │
│  │ [Incident]         │  │  │ assignee   [____________]              │ │
│  └────────────────────┘  │  │ labels     [tag ×, tag ×]              │ │
│                          │  │                                       │ │
│                          │  │ [ 🛡 Create ticket ] ←opens modal      │ │
│                          │  └──────────────────────────────────────┘ │
│                          │                                          │
│                          │  ┌─ 📚 Citations (N) ────────────────────┐ │
│                          │  │ doc_id · § · score · excerpt           │ │
│                          │  └──────────────────────────────────────┘ │
│                          │                                          │
│                          │  ┌─ 🛠 MCP execution trace (N steps) ───┐ │
│                          │  │ server → tool — outcome (ms)          │ │
│                          │  └──────────────────────────────────────┘ │
│  [chat_input at bottom]  │                                          │
└──────────────────────────┴──────────────────────────────────────────┘
```

The chat column is unchanged from Feature 7.1. The workspace column
is new; the panels render the **latest** assistant turn's structured
outputs.

### Confirmation modal (hard constraint #3)

```
┌─ Confirm ticket creation ─────────────────┐
│                                            │
│  Title:    <editable draft title>          │
│  Severity: <editable draft severity>       │
│  Body:     <truncated to 3 lines>          │
│                                            │
│  This will create a ticket in the          │
│  ticketing system. Approval is required    │
│  by hard constraint #3.                    │
│                                            │
│  [ Cancel ]      [ ✅ Approve & create ]   │
└────────────────────────────────────────────┘
```

Implemented with `st.dialog` (Streamlit 1.31+, our `pyproject.toml`
pins `streamlit>=1.39`). The modal:

1. Opens when the user clicks "Create ticket" in the workspace column.
2. Calls `TicketClient.preview(incident)` to populate the editable
   draft fields.
3. Shows the draft fields read-only inside the modal (the user has
   already edited them in the workspace column).
4. "Cancel" closes the modal without calling the backend.
5. "Approve & create" calls `TicketClient.create(incident)` and
   surfaces the resulting `ticket_id` + `approval` block in a
   success panel.

### Loading / empty / error states (Story 7.2.3)

| Panel | Loading | Empty | Error |
|---|---|---|---|
| Incident summary | `st.skeleton` placeholder rows | `st.info("Ask the copilot a question to see the evidence here.")` | `st.warning("Last request failed; previous turn results still shown.")` |
| Editable draft | `st.skeleton` text input | `st.caption("No draft yet.")` | same |
| Create-ticket button | disabled | disabled | disabled |
| Citations panel | `st.skeleton` rows | `st.caption("No citations yet.")` | same |
| Trace panel | `st.skeleton` rows | `st.caption("No MCP trace yet.")` | same |

The "in flight" signal comes from a `st.session_state[_PENDING]`
flag the chat input sets before calling `client.send()` and clears
after.

### File-by-file detail

**`apps/frontend/ticket_client.py`** — typed HTTP client. Two methods
on a class that owns an `httpx.Client` and a `core.config`-driven base
URL. Same env-var convention as `chat_client.py` (no `os.getenv`
outside `core/`).

```
class TicketError(Exception): ...
@dataclass class TicketPreview: title, body, severity, assignee, labels, incident_id
@dataclass class TicketDraft: title, body, severity, assignee, labels, ticket_id, preview, approval
class TicketClient:
    def preview(self, *, incident, trace_id=None) -> TicketPreview
    def create(self, *, incident, trace_id=None) -> TicketDraft
```

**`apps/frontend/ui.py`** — keep the existing chat column intact; add
a right-hand workspace column. New helpers:

* `render_workspace(latest_assistant_message, ticket_client)`
* `_render_incident_summary(incident)`
* `_render_editable_draft(incident, key_prefix)` — pre-fills the
  Streamlit widgets and returns the user-edited values via
  `st.session_state`.
* `_render_citations_panel(citations)`
* `_render_trace_panel(trace)`
* `_render_create_ticket_button(draft)` + `_render_confirmation_modal(draft)`
* `_render_workspace_skeleton()` — empty-state copy

**`tests/unit/frontend/test_ticket_client.py`** — `httpx.MockTransport`
tests for both methods, error envelopes, transport errors, trace-id
forwarding, empty incident rejection.

**`tests/unit/frontend/test_workspace_smoke.py`** — Streamlit
`AppTest` smoke. Stub the `TicketClient` (same `session_state`
injection trick that worked in Feature 7.1). Cases:

* Empty state copy renders when no assistant turn has happened.
* Latest assistant turn renders summary, draft, citations, trace.
* Editing a draft field reflects in the session state.
* "Create ticket" button is disabled when no incident is available.
* Modal opens (calls `st.dialog`), Cancel returns without
  contacting the backend.
* Modal Approve calls `TicketClient.create` and surfaces the
  resulting `ticket_id` + `approval` block.

**`tests/integration/test_workspace_e2e.py`** — in-process
`apps.backend.create_app()` + AppTest pointed at it. Skipped when
`var/index/v1.pkl` is missing (existing `_require_rag_index`
pattern). Verifies the full chat → preview → confirm → create
round-trip.

### Verification

```
uv run ruff check .
uv run mypy --explicit-package-bases apps rag connectors core
uv run pytest -ra
```

Live smoke (PR 2): `uv run streamlit run apps/frontend/ui.py
--server.port 5173 --server.headless true`. In the browser:

1. Ask "Investigate boiler B-101 in the last 90 days."
2. Confirm the right column shows incident summary, editable
   draft, citations, MCP trace.
3. Edit a field (e.g. title), click "Create ticket".
4. Modal opens with the edited title.
5. Click "Approve & create" → success panel shows `ticket_id` +
   `approved_by`.

Docker smoke (PR 2): `docker compose up --build` from a clean
clone. Same browser flow.

---

## What this plan deliberately does NOT do

* No new runtime dependencies. Streamlit 1.39 already ships
  `st.dialog` and `st.skeleton`. No new Pydantic, no new httpx.
* No changes to Feature 6.2's approval gate. `/tickets/draft` is
  unchanged in both PRs.
* No changes to docker-compose, Dockerfile, .env.example, or CI
  workflow. The GUI PR ships purely inside `apps/frontend/`.
* No editing of the incident payload itself (the draft form edits
  the **ticket** draft, not the structured Incident). That would
  be a different story.

---

## Rollback

**PR 1 rollback:** remove `POST /tickets/preview` route and the
`TicketPreviewRequest` / `TicketPreviewResponse` envelopes. The
existing `/tickets/draft` is unchanged and remains the only path
that persists.

**PR 2 rollback:** revert `apps/frontend/ui.py` to the Feature
7.1 version, delete `apps/frontend/ticket_client.py`. The chat
column continues to work — only the workspace column is removed.