"""Streamlit UI for the copilot backend.

Feature 7.1 — Story 7.1.1 (chat interface) + Story 7.1.2
(connect frontend with backend). Feature 7.2 adds the workspace
column and the ticket confirmation modal (Stories 7.2.1, 7.2.2,
7.2.3).

The UI is a thin client to the backend's three endpoints:

* ``POST /chat`` — the chat input posts the user's message and
  renders the response envelope (``ChatResponse``).
* ``POST /tickets/preview`` — when the user clicks "Create ticket"
  in the workspace column, the GUI calls preview to populate
  the editable draft.
* ``POST /tickets/draft`` — when the user approves the
  confirmation modal, the GUI calls the gated create path
  (Feature 6.2).

The chat column renders with expanders per assistant turn for
citations, MCP execution trace, and the structured ``Incident``
payload (Story 7.1.1). The workspace column surfaces those
same fields as first-class panels for the **latest** assistant
turn (Story 7.2.2) and adds an editable ticket-draft form
plus the confirmation modal (Story 7.2.1, hard constraint #3).
Loading / empty / error states are explicit (Story 7.2.3).

Conversation state lives in ``st.session_state.messages`` and is
preserved across reruns. The backend's ``conversation_id`` is
echoed back in the response and threaded into the next request
so multi-turn context works.

We intentionally keep all rendering logic in pure functions that
take ``messages`` and a ``client`` so
``tests/unit/frontend/test_ui_smoke.py`` and
``tests/unit/frontend/test_workspace_smoke.py`` can drive the
same code paths through Streamlit's ``AppTest`` headless runner.
"""
from __future__ import annotations

from typing import Any

import streamlit as st

from apps.frontend.chat_client import ChatClient, ChatError, build_default_client
from apps.frontend.ticket_client import (
    TicketClient,
    TicketError,
    TicketPreview,
)
from apps.frontend.ticket_client import (
    build_default_client as build_default_ticket_client,
)
from core.logging import get_logger

log = get_logger(__name__)


# --------------------------------------------------------------------------- #
# Page config & session state
# --------------------------------------------------------------------------- #

_PAGE_TITLE = "Incident Copilot"
_PAGE_ICON = "🚨"

# Suggested prompt shown in the empty-state callout.
_SUGGESTED_PROMPT = (
    "Try: *Investigate recurring high-severity alarms on boiler "
    "B-101 in the last 90 days.*"
)

# Session-state keys. Pulled into module-level constants so the
# unit tests can introspect / reset them without poking at private
# attributes.
_SESSION_MESSAGES = "messages"
_SESSION_CLIENT = "client"
_SESSION_LAST_ERROR = "last_error"

# Workspace column session-state keys (Feature 7.2). ``ticket_client``
# is the per-session HTTP client (analogous to ``_SESSION_CLIENT``);
# ``pending`` is the in-flight flag for the loading-skeleton states
# (Story 7.2.3); ``ticket_modal`` is the staged modal payload, set
# when the user clicks "Create ticket" and consumed by the modal
# callback. ``ticket_result`` carries the success envelope from
# ``TicketClient.create`` for the success-panel render.
_SESSION_TICKET_CLIENT = "ticket_client"
_SESSION_PENDING = "pending"
_SESSION_TICKET_MODAL = "ticket_modal"
_SESSION_TICKET_RESULT = "ticket_result"


def _init_session_state() -> None:
    """Seed the Streamlit session-state slots the UI uses."""
    if _SESSION_MESSAGES not in st.session_state:
        # Each entry is a dict with at least ``role`` and ``content``;
        # assistant turns also carry ``citations``, ``trace``,
        # ``incident``, ``conversation_id``, ``intent``,
        # ``rag_confidence``, ``dropped_count``.
        st.session_state[_SESSION_MESSAGES] = []
    if _SESSION_LAST_ERROR not in st.session_state:
        st.session_state[_SESSION_LAST_ERROR] = None
    if _SESSION_PENDING not in st.session_state:
        st.session_state[_SESSION_PENDING] = False
    if _SESSION_TICKET_MODAL not in st.session_state:
        # ``None`` when no modal is staged; a dict with the
        # modal payload (``incident`` + the in-progress draft
        # values) when the user has clicked "Create ticket".
        st.session_state[_SESSION_TICKET_MODAL] = None
    if _SESSION_TICKET_RESULT not in st.session_state:
        st.session_state[_SESSION_TICKET_RESULT] = None


def get_client() -> ChatClient:
    """Return the per-session :class:`ChatClient`.

    Created lazily on first access so import-time side effects
    don't trigger an HTTP connection. Streamlit serialises the
    session between reruns via ``st.session_state`` but it does
    not pickle arbitrary objects cleanly, so we keep the client
    in ``st.session_state`` keyed by id and rebuild on access if
    it went missing.
    """
    client = st.session_state.get(_SESSION_CLIENT)
    if client is None:
        client = build_default_client()
        st.session_state[_SESSION_CLIENT] = client
    return client


def get_ticket_client() -> TicketClient:
    """Return the per-session :class:`TicketClient` (Feature 7.2).

    Mirrors :func:`get_client` — built lazily on first access so
    import-time side effects don't trigger an HTTP connection.
    The test harness can inject a stub via
    ``st.session_state[_SESSION_TICKET_CLIENT] = stub`` after
    the first ``AppTest.run()`` to drive the workspace column
    without a network round-trip.
    """
    client = st.session_state.get(_SESSION_TICKET_CLIENT)
    if client is None:
        client = build_default_ticket_client()
        st.session_state[_SESSION_TICKET_CLIENT] = client
    return client


# --------------------------------------------------------------------------- #
# Render helpers (pure functions — also called by tests)
# --------------------------------------------------------------------------- #


def render_history(messages: list[dict[str, Any]]) -> None:
    """Walk the session message list and render each turn.

    Each assistant turn renders its answer body, then three
    expanders: citations, MCP execution trace, and the structured
    ``Incident`` payload (when present). The expanders satisfy
    hard constraint #4 (every answer carries citations + MCP
    execution trace).
    """
    if not messages:
        _render_empty_state()
        return
    for message in messages:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])
            if message["role"] != "assistant":
                continue
            _render_citations(message.get("citations") or [])
            _render_trace(message.get("trace") or [])
            _render_incident(message.get("incident"))
            _render_confidence(
                message.get("rag_confidence", "none"),
                message.get("dropped_count", 0),
            )


def _render_empty_state() -> None:
    """Helpful first-load copy + suggested prompt."""
    st.info(_SUGGESTED_PROMPT)


def _render_citations(citations: list[dict[str, Any]]) -> None:
    """Expandable citation panel — one row per cited document."""
    label = f"📚 Citations ({len(citations)})"
    with st.expander(label, expanded=False):
        if not citations:
            st.caption("No documents were cited for this answer.")
            return
        for idx, citation in enumerate(citations, start=1):
            doc_id = citation.get("doc_id", "<unknown doc>")
            section = citation.get("section")
            page = citation.get("page")
            score = citation.get("score")
            excerpt = citation.get("excerpt")
            header_bits = [f"**{idx}. `{doc_id}`**"]
            if section:
                header_bits.append(f"§ {section}")
            if page is not None:
                header_bits.append(f"p. {page}")
            if score is not None:
                header_bits.append(f"score={score:.3f}")
            st.markdown(" — ".join(header_bits))
            if excerpt:
                st.caption(excerpt)


def _render_trace(trace: list[dict[str, Any]]) -> None:
    """Expandable MCP execution trace — one row per tool invocation."""
    label = f"🛠️ MCP execution trace ({len(trace)} step{'s' if len(trace) != 1 else ''})"
    with st.expander(label, expanded=False):
        if not trace:
            st.caption("No MCP tools were invoked for this answer.")
            return
        for idx, step in enumerate(trace, start=1):
            server = step.get("server", "?")
            tool = step.get("tool", "?")
            outcome = step.get("outcome", "?")
            duration = step.get("duration_ms", "?")
            api_status = step.get("api_status_code")
            header = f"{idx}. `{server}` → `{tool}` — {outcome} ({duration} ms)"
            if api_status is not None:
                header += f" [HTTP {api_status}]"
            st.markdown(header)
            error = step.get("error")
            if error:
                st.caption(f"error: {error}")


def _render_incident(incident: dict[str, Any] | None) -> None:
    """Expandable structured-incident panel — read-only in 7.1.

    Story 7.2.1 replaces this with an editable draft panel; for
    now we render the fields so the reviewer can confirm the
    backend's structured output is reaching the GUI.
    """
    if not incident:
        return
    title = incident.get("title") or "Incident"
    label = f"📋 Incident — {title}"
    with st.expander(label, expanded=False):
        st.markdown(f"**Title:** {title}")
        if incident.get("summary"):
            st.markdown(f"**Summary:** {incident['summary']}")
        if incident.get("severity"):
            st.markdown(f"**Severity:** `{incident['severity']}`")
        if incident.get("likely_cause"):
            st.markdown(f"**Likely cause:** {incident['likely_cause']}")
        actions = incident.get("recommended_actions") or []
        if actions:
            st.markdown("**Recommended actions:**")
            for action in actions:
                st.markdown(f"- {action}")
        similar = incident.get("similar_tickets") or []
        if similar:
            st.markdown("**Similar tickets:** " + ", ".join(f"`{t}`" for t in similar))


def _render_confidence(rag_confidence: str, dropped_count: int) -> None:
    """Small caption below the assistant message for low-confidence answers."""
    if rag_confidence in {"low", "none"} or dropped_count > 0:
        bits = []
        if rag_confidence in {"low", "none"}:
            bits.append(f"RAG confidence: `{rag_confidence}`")
        if dropped_count > 0:
            bits.append(f"{dropped_count} chunk{'s' if dropped_count != 1 else ''} dropped")
        st.caption("⚠️ " + " · ".join(bits))


def render_input(client: ChatClient) -> None:
    """Bottom-of-page chat input + send logic.

    On submit:

    1. Append the user turn to ``st.session_state.messages``.
    2. ``st.spinner(...)`` while :meth:`ChatClient.send` runs.
    3. On success: append the assistant turn and rerun so the new
       turn appears above the input.
    4. On :class:`ChatError`: append a synthetic assistant turn
       containing the error envelope so the user can see what
       went wrong and retry from the same place.
    """
    prompt = st.chat_input("Ask the copilot…")
    if not prompt:
        return

    history: list[dict[str, Any]] = st.session_state[_SESSION_MESSAGES]
    conversation_id = _latest_conversation_id(history)

    history.append({"role": "user", "content": prompt})
    log.info(
        "ui.user_turn",
        conversation_id=conversation_id,
        message_length=len(prompt),
    )

    with st.spinner("Investigating…"):
        try:
            response = client.send(
                message=prompt,
                conversation_id=conversation_id,
            )
        except ChatError as exc:
            log.warning(
                "ui.chat_error",
                code=exc.code,
                message=exc.message,
                status_code=exc.status_code,
            )
            st.session_state[_SESSION_LAST_ERROR] = {
                "code": exc.code,
                "message": exc.message,
            }
            history.append(
                {
                    "role": "assistant",
                    "content": f"⚠️ **{exc.code}** — {exc.message}",
                    "citations": [],
                    "trace": [],
                    "incident": None,
                    "conversation_id": conversation_id,
                    "intent": "",
                    "rag_confidence": "none",
                    "dropped_count": 0,
                }
            )
            st.rerun()
            return

    log.info(
        "ui.assistant_turn",
        conversation_id=response.conversation_id,
        intent=response.intent,
        citation_count=len(response.citations),
        trace_steps=len(response.trace),
        has_incident=response.incident is not None,
    )
    history.append(
        {
            "role": "assistant",
            "content": response.answer or "(empty answer)",
            "citations": response.citations,
            "trace": response.trace,
            "incident": response.incident,
            "conversation_id": response.conversation_id,
            "intent": response.intent,
            "rag_confidence": response.rag_confidence,
            "dropped_count": response.dropped_count,
        }
    )
    st.session_state[_SESSION_LAST_ERROR] = None
    st.rerun()


def _latest_conversation_id(messages: list[dict[str, Any]]) -> str | None:
    """Return the most recent assistant ``conversation_id``.

    ``None`` for the first turn (the backend mints a new
    conversation id); subsequent turns thread it so the
    orchestrator's conversation store keeps the audit trail
    intact.
    """
    for message in reversed(messages):
        if message.get("role") == "assistant" and message.get("conversation_id"):
            return message["conversation_id"]
    return None


def _latest_assistant_message(messages: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Return the most recent assistant turn, or ``None``.

    Used by the workspace column to source its panels (Story
    7.2.2) — citations, MCP execution trace, and the structured
    ``Incident`` all come from the latest assistant turn.
    """
    for message in reversed(messages):
        if message.get("role") == "assistant":
            return message
    return None


# --------------------------------------------------------------------------- #
# Workspace column — Feature 7.2 (Stories 7.2.1, 7.2.2, 7.2.3)
# --------------------------------------------------------------------------- #

# Suggested prompts shown when no incident is loaded yet.
_WORKSPACE_EMPTY_HINT = (
    "Ask the copilot a question to see the structured incident, "
    "evidence chain, and editable ticket draft here."
)

# Severity options for the editable draft (matches the ticket-mock's
# ``TicketSeverity`` Literal). The GUI exposes them as a selectbox.
_SEVERITY_OPTIONS = ("low", "medium", "high", "critical")


def render_workspace(
    latest_message: dict[str, Any] | None,
    ticket_client: TicketClient,
) -> None:
    """Render the right-hand workspace column (Feature 7.2).

    Composed of four panels — incident summary, editable ticket
    draft, citations, MCP execution trace — plus the "Create
    ticket" button that opens the confirmation modal. Loading /
    empty / error states (Story 7.2.3) are explicit.

    The workspace is sourced from the **latest** assistant turn.
    Older turns remain visible in the left chat column.
    """
    st.subheader("🛠 Workspace")

    pending = bool(st.session_state.get(_SESSION_PENDING))
    last_error = st.session_state.get(_SESSION_LAST_ERROR)
    if last_error:
        st.warning(
            f"Last request failed ({last_error['code']}); "
            "previous turn results are still shown."
        )

    if pending:
        _render_workspace_skeleton()
        _render_create_ticket_button(None, ticket_client)
        return

    if latest_message is None:
        st.info(_WORKSPACE_EMPTY_HINT)
        # Render the button (disabled) even in the empty state so
        # the workspace's primary affordance is discoverable.
        _render_create_ticket_button(None, ticket_client)
        return

    incident = latest_message.get("incident")
    citations = latest_message.get("citations") or []
    trace = latest_message.get("trace") or []

    _render_incident_summary(incident)
    _render_editable_draft(incident)
    _render_citations_panel(citations)
    _render_trace_panel(trace)
    _render_create_ticket_button(incident, ticket_client)
    _render_ticket_result()


def _render_workspace_skeleton() -> None:
    """Loading skeletons for the workspace column (Story 7.2.3)."""
    with st.container():
        st.skeleton(height=120)
        st.skeleton(height=180)
        st.skeleton(height=160)
        st.skeleton(height=160)


def _render_incident_summary(incident: dict[str, Any] | None) -> None:
    """Top-level incident-summary panel (Story 7.2.1).

    Empty-state copy when no incident is available.
    """
    st.markdown("##### 📋 Incident summary")
    if not incident:
        st.caption("No structured incident yet.")
        return
    title = incident.get("title") or "Incident"
    st.markdown(f"**{title}**")
    if incident.get("severity"):
        st.markdown(f"Severity: `{incident['severity']}`")
    if incident.get("asset_id"):
        st.markdown(f"Asset: `{incident['asset_id']}`")
    if incident.get("site"):
        st.markdown(f"Site: `{incident['site']}`")
    if incident.get("likely_cause"):
        st.markdown(f"Likely cause: {incident['likely_cause']}")
    actions = incident.get("recommended_actions") or []
    if actions:
        st.markdown("**Recommended actions:**")
        for action in actions:
            st.markdown(f"- {action}")
    similar = incident.get("similar_tickets") or []
    if similar:
        st.markdown("**Similar tickets:** " + ", ".join(f"`{t}`" for t in similar))


def _render_editable_draft(incident: dict[str, Any] | None) -> None:
    """Editable ticket-draft form (Story 7.2.1).

    Pre-fills the widgets from the incident payload. The
    user-edited values live in ``st.session_state`` and are read
    by ``_render_create_ticket_button`` when the user clicks
    "Create ticket".

    Empty-state copy when no incident is available — the form
    is hidden entirely so the workspace doesn't tease an
    editable draft the user can't act on.
    """
    st.markdown("##### ✏️ Editable ticket draft")
    if not incident:
        st.caption("No draft yet — ask the copilot a question first.")
        return

    # Use ``key="draft_*"`` so the form values survive reruns
    # without our manual session-state bookkeeping.
    severity_default = str(incident.get("severity") or "medium").lower()
    if severity_default not in _SEVERITY_OPTIONS:
        severity_default = "medium"
    severity_index = _SEVERITY_OPTIONS.index(severity_default)

    title = st.text_input(
        "Title",
        value=str(incident.get("title") or "Incident"),
        key="draft_title",
    )
    severity = st.selectbox(
        "Severity",
        options=list(_SEVERITY_OPTIONS),
        index=severity_index,
        key="draft_severity",
    )
    body_default = _build_default_body(incident)
    body = st.text_area("Body", value=body_default, key="draft_body", height=160)
    assignee = st.text_input(
        "Assignee",
        value="",
        key="draft_assignee",
        placeholder="(optional)",
    )
    labels_csv = st.text_input(
        "Labels (comma-separated)",
        value=", ".join(_build_default_labels(incident)),
        key="draft_labels",
    )
    # Read the values back into the local scope so the linter
    # sees they're "used" — Streamlit reads them via ``key=``
    # but the form's logical flow benefits from the visible
    # binding. The values are captured into the session state
    # by Streamlit's widget machinery; we read them back via
    # ``st.session_state[...]`` in ``_snapshot_draft()``.
    _ = (title, severity, body, assignee, labels_csv)


def _build_default_body(incident: dict[str, Any]) -> str:
    """Compose the default body shown in the editable draft form.

    Mirrors the ticket-mock's ``build_draft()`` projection —
    summary + numbered recommended actions — so what the user
    sees is exactly what ``/tickets/preview`` would return.
    """
    summary = str(incident.get("summary") or "").strip()
    actions = list(incident.get("recommended_actions") or [])
    if not actions:
        return summary
    action_lines = "\n".join(f"{i + 1}. {a}" for i, a in enumerate(actions))
    return f"{summary}\n\nRecommended actions:\n{action_lines}"


def _build_default_labels(incident: dict[str, Any]) -> list[str]:
    """Compose the default labels shown in the editable draft form."""
    severity = str(incident.get("severity") or "medium").lower()
    if severity not in _SEVERITY_OPTIONS:
        severity = "medium"
    labels = [f"severity:{severity}"]
    for tid in incident.get("similar_tickets") or []:
        if isinstance(tid, str):
            labels.append(f"related:{tid}")
    return labels


def _render_citations_panel(citations: list[dict[str, Any]]) -> None:
    """Top-level citations panel (Story 7.2.2)."""
    st.markdown(f"##### 📚 Citations ({len(citations)})")
    if not citations:
        st.caption("No citations yet.")
        return
    for idx, citation in enumerate(citations, start=1):
        doc_id = citation.get("doc_id", "<unknown doc>")
        section = citation.get("section")
        page = citation.get("page")
        score = citation.get("score")
        excerpt = citation.get("excerpt")
        header_bits = [f"**{idx}. `{doc_id}`**"]
        if section:
            header_bits.append(f"§ {section}")
        if page is not None:
            header_bits.append(f"p. {page}")
        if score is not None:
            header_bits.append(f"score={score:.3f}")
        st.markdown(" — ".join(header_bits))
        if excerpt:
            st.caption(excerpt)


def _render_trace_panel(trace: list[dict[str, Any]]) -> None:
    """Top-level MCP execution trace panel (Story 7.2.2)."""
    step_label = "step" if len(trace) == 1 else "steps"
    st.markdown(f"##### 🛠️ MCP execution trace ({len(trace)} {step_label})")
    if not trace:
        st.caption("No MCP tools invoked yet.")
        return
    for idx, step in enumerate(trace, start=1):
        server = step.get("server", "?")
        tool = step.get("tool", "?")
        outcome = step.get("outcome", "?")
        duration = step.get("duration_ms", "?")
        api_status = step.get("api_status_code")
        header = f"{idx}. `{server}` → `{tool}` — {outcome} ({duration} ms)"
        if api_status is not None:
            header += f" [HTTP {api_status}]"
        st.markdown(header)
        error = step.get("error")
        if error:
            st.caption(f"error: {error}")


def _render_create_ticket_button(
    incident: dict[str, Any] | None,
    ticket_client: TicketClient,
) -> None:
    """The bottom-of-workspace button that opens the confirmation modal.

    Disabled until a draft is available. On click: stages the
    modal payload in ``st.session_state[_SESSION_TICKET_MODAL]``
    and reruns — the modal handler picks it up on the next pass.
    """
    disabled = not incident
    clicked = st.button(
        "🛡 Create ticket",
        disabled=disabled,
        key="create_ticket_button",
        help="Stage a ticket draft for approval",
    )
    if not clicked or disabled:
        return

    # Stage the modal with the current widget values. The user has
    # been editing the draft in the workspace column; we capture
    # those values verbatim and pass them through ``/tickets/preview``
    # inside the modal so the preview result is the authoritative
    # text the operator approves.
    st.session_state[_SESSION_TICKET_MODAL] = {
        "incident": dict(incident or {}),
        "draft": _snapshot_draft(),
    }
    log.info(
        "ui.create_ticket_clicked",
        incident_id=(incident or {}).get("id"),
    )
    st.rerun()


def _snapshot_draft() -> dict[str, Any]:
    """Capture the current values of the editable draft widgets."""
    return {
        "title": st.session_state.get("draft_title", ""),
        "severity": st.session_state.get("draft_severity", "medium"),
        "body": st.session_state.get("draft_body", ""),
        "assignee": st.session_state.get("draft_assignee", "") or None,
        "labels": [
            label.strip()
            for label in (st.session_state.get("draft_labels") or "").split(",")
            if label.strip()
        ],
    }


@st.dialog("Confirm ticket creation")
def _render_confirmation_modal(ticket_client: TicketClient) -> None:
    """The hard-constraint-#3 confirmation modal.

    ``st.dialog`` blocks the rest of the page until the user
    chooses Cancel or Approve. The modal calls
    ``TicketClient.preview`` on entry to populate the body /
    labels it shows (so the user sees exactly what the
    ticket-mock would produce), and ``TicketClient.create`` on
    Approve to persist.
    """
    payload = st.session_state.get(_SESSION_TICKET_MODAL)
    if not isinstance(payload, dict):
        # Modal was opened without a staged payload — close it.
        st.session_state[_SESSION_TICKET_MODAL] = None
        st.rerun()
        return

    incident = payload.get("incident") or {}
    draft = payload.get("draft") or {}

    # Merge the staged draft values into the incident so the
    # preview call sees the operator's edits. The preview
    # endpoint honours the incident fields it knows about and
    # ignores the rest; surfacing ``title``, ``summary``,
    # ``severity``, and ``similar_tickets`` is sufficient.
    merged = dict(incident)
    if draft.get("title"):
        merged["title"] = draft["title"]
    if draft.get("severity"):
        merged["severity"] = draft["severity"]
    if draft.get("body"):
        # The preview's body projection is ``summary`` + numbered
        # actions. We treat the operator's body as the new
        # summary so the preview reflects their edits.
        merged["summary"] = draft["body"]
        merged["recommended_actions"] = []
    if draft.get("assignee"):
        merged["assignee"] = draft["assignee"]
    if draft.get("labels"):
        merged["labels"] = list(draft["labels"])

    # Server-side preview to show the projected ticket text.
    preview: TicketPreview | None = None
    preview_error: str | None = None
    try:
        preview = ticket_client.preview(incident=merged)
    except TicketError as exc:
        preview_error = f"[{exc.code}] {exc.message}"
        log.warning(
            "ui.modal_preview_error",
            code=exc.code,
            message=exc.message,
        )

    if preview_error:
        st.error(f"Could not project draft: {preview_error}")
    else:
        st.markdown(
            f"**Title:** {preview.title if preview else draft.get('title', '')}"
        )
        st.markdown(f"**Severity:** `{preview.severity if preview else draft.get('severity', '')}`")
        body_preview = (preview.body if preview else draft.get("body", "")) or ""
        # Body is shown inside a collapsed expander so the modal
        # itself stays compact while the full text remains
        # inspectable on demand.
        with st.expander("Body", expanded=False):
            st.markdown(body_preview or "_(empty)_")

    st.caption(
        "This will create a ticket in the ticketing system. "
        "Approval is required by hard constraint #3."
    )

    col_cancel, _, col_approve = st.columns([1, 2, 1])
    with col_cancel:
        if st.button("Cancel", key="modal_cancel"):
            log.info("ui.modal_canceled")
            st.session_state[_SESSION_TICKET_MODAL] = None
            st.session_state[_SESSION_TICKET_RESULT] = None
            st.rerun()
    with col_approve:
        if st.button("✅ Approve & create", key="modal_approve", type="primary"):
            log.info(
                "ui.modal_approved",
                incident_id=merged.get("id"),
            )
            try:
                result = ticket_client.create(incident=merged)
            except TicketError as exc:
                log.warning(
                    "ui.modal_create_error",
                    code=exc.code,
                    message=exc.message,
                )
                st.session_state[_SESSION_TICKET_RESULT] = {
                    "error": f"[{exc.code}] {exc.message}",
                }
            else:
                st.session_state[_SESSION_TICKET_RESULT] = {
                    "ticket_id": result.ticket_id,
                    "approved_by": (result.approval or {}).get("approved_by"),
                    "approved_at": (result.approval or {}).get("approved_at"),
                    "request_id": (result.approval or {}).get("request_id"),
                }
            st.session_state[_SESSION_TICKET_MODAL] = None
            st.rerun()


def _render_ticket_result() -> None:
    """Render the post-approval success or error panel."""
    result = st.session_state.get(_SESSION_TICKET_RESULT)
    if not isinstance(result, dict):
        return
    if "error" in result:
        st.error(f"❌ Could not create ticket: {result['error']}")
        return
    ticket_id = result.get("ticket_id")
    approved_by = result.get("approved_by")
    if not ticket_id:
        st.warning("Approval returned but no ticket id was assigned.")
        return
    st.success(f"✅ Created ticket `{ticket_id}` (approved by `{approved_by or 'unknown'}`).")


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #


def main() -> None:
    """Streamlit script entrypoint — called by the launcher."""
    st.set_page_config(page_title=_PAGE_TITLE, page_icon=_PAGE_ICON)
    _init_session_state()
    client = get_client()
    ticket_client = get_ticket_client()

    st.title(f"{_PAGE_ICON} {_PAGE_TITLE}")
    st.caption(f"Backend: `{client.base_url}`")

    last_error = st.session_state.get(_SESSION_LAST_ERROR)
    if last_error:
        st.error(f"[{last_error['code']}] {last_error['message']}")

    # Feature 7.2 — two-column layout: chat column on the left,
    # workspace column on the right. Streamlit collapses to a
    # single column on narrow screens automatically. The chat
    # input lives in the left column so it stays adjacent to the
    # message list.
    history = st.session_state[_SESSION_MESSAGES]
    latest = _latest_assistant_message(history)
    chat_column, workspace_column = st.columns([1, 1], gap="large")

    with chat_column:
        render_history(history)
        render_input(client)

    with workspace_column:
        render_workspace(latest, ticket_client)

    # Confirmation modal (Feature 7.2 / hard constraint #3).
    # ``st.dialog`` is invoked at the top level of the script so
    # it can be triggered from any rerun. We only render its body
    # when the user has staged a modal payload.
    if st.session_state.get(_SESSION_TICKET_MODAL) is not None:
        _render_confirmation_modal(ticket_client)


__all__ = [
    "main",
    "render_history",
    "render_input",
    "get_client",
    "_init_session_state",
    "_latest_conversation_id",
]


# Streamlit executes a script top-to-bottom on every rerun, so
# the entrypoint must be invoked at module level. Both
# ``streamlit run apps/frontend/ui.py`` (production) and
# ``streamlit.testing.v1.AppTest.from_file(...)`` (tests) drive
# the same code path. The launcher at ``apps.frontend.__main__``
# execs ``streamlit run`` against this script; tests import it
# via ``AppTest.from_file``. In both cases ``__name__`` is
# ``"__main__"`` at execution time.
main()
