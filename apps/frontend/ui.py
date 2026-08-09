"""Streamlit UI for the copilot backend.

Feature 7.1 — Story 7.1.1 (chat interface) + Story 7.1.2
(connect frontend with backend). Feature 7.2 adds the workspace
column and the ticket confirmation modal (Stories 7.2.1, 7.2.2,
7.2.3). Feature 7.2 PR 2 + the Story 7.2.1 approval gate round
out the workflow.

The UI is a thin client to the backend's three endpoints:

* ``POST /chat`` — the chat input posts the user's message and
  renders the response envelope (``ChatResponse``).
* ``POST /tickets/preview`` — when the user clicks "Create ticket"
  in the workspace column, the GUI calls preview to populate
  the editable draft.
* ``POST /tickets/draft`` — when the user approves the
  confirmation modal, the GUI calls the gated create path
  (Feature 6.2).

The chat column renders the conversation history with custom
HTML cards (left accent bar, role badge, intent + RAG-confidence
pills). The workspace column surfaces the structured Incident,
editable ticket draft, citations, and MCP execution trace as
first-class panels (Story 7.2.2). Loading / empty / error
states (Story 7.2.3) are explicit.

Conversation state lives in ``st.session_state.messages`` and is
preserved across reruns. The backend's ``conversation_id`` is
echoed back in the response and threaded into the next request
so multi-turn context works.

Rendering helpers live in ``apps.frontend.theme`` so the
card / pill / timeline visuals are reusable and testable.
"""
from __future__ import annotations

import datetime as _dt
from typing import Any

import streamlit as st

from apps.frontend import theme
from apps.frontend.chat_client import ChatClient, ChatError, build_default_client
from apps.frontend.theme import (
    render_app_bar,
    render_assistant_message,
    render_card,
    render_chat_skeleton,
    render_citation_card,
    render_empty_state,
    render_kv,
    render_section,
    render_timeline,
    render_user_message,
    severity_pill,
)
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

_SUGGESTED_PROMPTS = [
    "Investigate recurring high-severity alarms on Boiler B-101 over the last 90 days.",
    "Prepare an incident for the highest-priority active alarm in EastRefinery.",
    "We're seeing intermittent high-temperature spikes on the cooling-water pump. What could be causing this?",
]

_SEVERITY_OPTIONS = ("low", "medium", "high", "critical")

# Session-state keys. Pulled into module-level constants so the
# unit tests can introspect / reset them without poking at private
# attributes.
_SESSION_MESSAGES = "messages"
_SESSION_CLIENT = "client"
_SESSION_TICKET_CLIENT = "ticket_client"
_SESSION_LAST_ERROR = "last_error"
_SESSION_PENDING = "pending"
_SESSION_TICKET_MODAL = "ticket_modal"
_SESSION_TICKET_RESULT = "ticket_result"


def _init_session_state() -> None:
    """Seed the Streamlit session-state slots the UI uses."""
    if _SESSION_MESSAGES not in st.session_state:
        st.session_state[_SESSION_MESSAGES] = []
    if _SESSION_LAST_ERROR not in st.session_state:
        st.session_state[_SESSION_LAST_ERROR] = None
    if _SESSION_PENDING not in st.session_state:
        st.session_state[_SESSION_PENDING] = False
    if _SESSION_TICKET_MODAL not in st.session_state:
        st.session_state[_SESSION_TICKET_MODAL] = None
    if _SESSION_TICKET_RESULT not in st.session_state:
        st.session_state[_SESSION_TICKET_RESULT] = None


def get_client() -> ChatClient:
    """Return the per-session :class:`ChatClient`."""
    client = st.session_state.get(_SESSION_CLIENT)
    if client is None:
        client = build_default_client()
        st.session_state[_SESSION_CLIENT] = client
    return client


def get_ticket_client() -> TicketClient:
    """Return the per-session :class:`TicketClient` (Feature 7.2)."""
    client = st.session_state.get(_SESSION_TICKET_CLIENT)
    if client is None:
        client = build_default_ticket_client()
        st.session_state[_SESSION_TICKET_CLIENT] = client
    return client


# --------------------------------------------------------------------------- #
# Chat column
# --------------------------------------------------------------------------- #


def _format_timestamp(ts: str | None) -> str | None:
    """Return a short HH:MM:SS stamp if the timestamp is ISO-8601."""
    if not ts:
        return None
    try:
        parsed = _dt.datetime.fromisoformat(ts.replace("Z", "+00:00"))
        return parsed.strftime("%H:%M:%S")
    except (ValueError, AttributeError):
        return None


def render_history(messages: list[dict[str, Any]]) -> None:
    """Walk the session message list and render each turn.

    Each user turn is a left-bordered blue card; each assistant turn
    is a left-bordered purple card with intent + RAG-confidence
    pills + a citation count + a trace-step count. The structured
    ``Incident`` payload is rendered as a card below the answer
    (Story 7.2.1).
    """
    if not messages:
        st.markdown(
            render_empty_state(
                "Start a conversation",
                "Ask the copilot about an alarm, an asset, or an operating procedure. "
                "The workspace on the right will populate with the evidence chain.",
                icon="💬",
            ),
            unsafe_allow_html=True,
        )
        return

    for message in messages:
        timestamp = _format_timestamp(message.get("timestamp"))
        if message["role"] == "user":
            st.markdown(
                render_user_message(message["content"], timestamp=timestamp),
                unsafe_allow_html=True,
            )
        elif message["role"] == "assistant":
            citations = message.get("citations") or []
            trace = message.get("trace") or []
            st.markdown(
                render_assistant_message(
                    message["content"],
                    timestamp=timestamp,
                    intent=message.get("intent"),
                    rag_confidence=message.get("rag_confidence"),
                    citations_count=len(citations),
                    trace_steps=len(trace),
                ),
                unsafe_allow_html=True,
            )
            incident = message.get("incident")
            if incident:
                _render_message_incident(incident)
            _render_message_evidence(citations, trace)


def _render_message_incident(incident: dict[str, Any]) -> None:
    """Render the structured Incident as a card under an assistant turn."""
    if not incident:
        return
    title = incident.get("title") or "Incident"
    severity = str(incident.get("severity") or "medium")
    body_bits: list[str] = []
    body_bits.append(
        f"<div class='kv-row'><span class='kv-label'>Title</span>"
        f"<span class='kv-value'><strong>{title}</strong></span></div>"
    )
    body_bits.append(
        f"<div class='kv-row'><span class='kv-label'>Severity</span>"
        f"<span class='kv-value'>{severity_pill(severity)}</span></div>"
    )
    if incident.get("asset_id"):
        body_bits.append(render_kv("Asset", str(incident["asset_id"])))
    if incident.get("site"):
        body_bits.append(render_kv("Site", str(incident["site"])))
    if incident.get("likely_cause"):
        body_bits.append(render_kv("Likely cause", str(incident["likely_cause"])))
    actions = incident.get("recommended_actions") or []
    if actions:
        items = "".join(f"<li>{a}</li>" for a in actions)
        body_bits.append(
            f"<div class='kv-row'><span class='kv-label'>Actions</span>"
            f"<span class='kv-value'><ul style='margin:0;padding-left:1rem'>{items}</ul></span></div>"
        )
    similar = incident.get("similar_tickets") or []
    if similar:
        chips = "".join(
            f"<span class='pill pill-neutral'>{theme.escape(str(t))}</span>" for t in similar
        )
        body_bits.append(f"<div class='chip-row'>{chips}</div>")

    st.markdown(
        render_card(
            "Structured Incident",
            "".join(body_bits),
            accent="primary",
            icon="📋",
        ),
        unsafe_allow_html=True,
    )


def _render_message_evidence(
    citations: list[dict[str, Any]],
    trace: list[dict[str, Any]],
) -> None:
    """Render the citations + MCP trace as collapsed sub-panels under
    the assistant turn. The **first-class** panels in the workspace
    column are the canonical view; these are the
    keep-scrolling-history view."""
    if not citations and not trace:
        return
    bits: list[str] = []
    if citations:
        bits.append(f"<div class='kv-row'><span class='kv-label'>📚 Citations</span>"
                    f"<span class='kv-value'>{len(citations)} referenced</span></div>")
    if trace:
        bits.append(f"<div class='kv-row'><span class='kv-label'>🛠 MCP trace</span>"
                    f"<span class='kv-value'>{len(trace)} tool call{'s' if len(trace) != 1 else ''}</span></div>")
    st.markdown(render_card("Evidence", "".join(bits), accent="neutral", icon="🔎"),
                unsafe_allow_html=True)


def render_input(client: ChatClient) -> None:
    """Bottom-of-page chat input + send logic."""
    prompt = st.chat_input("Ask the copilot…")
    if not prompt:
        return

    history: list[dict[str, Any]] = st.session_state[_SESSION_MESSAGES]
    conversation_id = _latest_conversation_id(history)

    history.append(
        {
            "role": "user",
            "content": prompt,
            "timestamp": _dt.datetime.now(_dt.UTC).isoformat(),
        }
    )
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
                    "timestamp": _dt.datetime.now(_dt.UTC).isoformat(),
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
            "timestamp": _dt.datetime.now(_dt.UTC).isoformat(),
        }
    )
    st.session_state[_SESSION_LAST_ERROR] = None
    st.rerun()


def _latest_conversation_id(messages: list[dict[str, Any]]) -> str | None:
    """Return the most recent assistant ``conversation_id``."""
    for message in reversed(messages):
        if message.get("role") == "assistant" and message.get("conversation_id"):
            return message["conversation_id"]
    return None


def _latest_assistant_message(messages: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Return the most recent assistant turn, or ``None``."""
    for message in reversed(messages):
        if message.get("role") == "assistant":
            return message
    return None


# --------------------------------------------------------------------------- #
# Sidebar
# --------------------------------------------------------------------------- #


def render_sidebar() -> None:
    """Left-rail sidebar with the copilot brand block + example prompts."""
    with st.sidebar:
        st.markdown(render_section("Copilot", icon="🚨"), unsafe_allow_html=True)
        st.caption("Industrial incident + RAG copilot.")
        st.markdown("<div class='divider'></div>", unsafe_allow_html=True)

        st.markdown(render_section("Try asking", icon="💡"), unsafe_allow_html=True)
        for prompt in _SUGGESTED_PROMPTS:
            if st.button(prompt, key=f"suggest::{prompt}", help="Click to ask"):
                history = st.session_state[_SESSION_MESSAGES]
                history.append(
                    {
                        "role": "user",
                        "content": prompt,
                        "timestamp": _dt.datetime.now(_dt.UTC).isoformat(),
                    }
                )
                st.session_state[_SESSION_PENDING] = True
                st.rerun()


# --------------------------------------------------------------------------- #
# Workspace column
# --------------------------------------------------------------------------- #


def render_workspace(
    latest_message: dict[str, Any] | None,
    ticket_client: TicketClient,
) -> None:
    """Render the right-hand workspace column.

    Composed of four panels — incident summary, editable ticket
    draft, citations, MCP execution trace — plus the "Create ticket"
    button that opens the confirmation modal. Loading / empty / error
    states (Story 7.2.3) are explicit.
    """
    st.markdown(render_section("Workspace", icon="🛠️"), unsafe_allow_html=True)

    last_error = st.session_state.get(_SESSION_LAST_ERROR)
    if last_error:
        st.markdown(
            render_card(
                "Last request failed",
                f"<div class='kv-row'><span class='kv-label'>Code</span>"
                f"<span class='kv-value'>{theme.escape(last_error['code'])}</span></div>"
                f"<div class='kv-row'><span class='kv-label'>Message</span>"
                f"<span class='kv-value'>{theme.escape(last_error['message'])}</span></div>",
                accent="warning",
                icon="⚠️",
            ),
            unsafe_allow_html=True,
        )

    pending = bool(st.session_state.get(_SESSION_PENDING))
    if pending:
        st.markdown(render_chat_skeleton(), unsafe_allow_html=True)
        _render_create_ticket_button(None, ticket_client)
        return

    if latest_message is None:
        st.markdown(
            render_empty_state(
                "Workspace empty",
                "Ask the copilot a question to see the structured incident, "
                "evidence chain, and editable ticket draft here.",
                icon="💭",
            ),
            unsafe_allow_html=True,
        )
        _render_create_ticket_button(None, ticket_client)
        return

    incident = latest_message.get("incident")
    citations = latest_message.get("citations") or []
    trace = latest_message.get("trace") or []

    _render_workspace_incident(incident)
    _render_workspace_editable_draft(incident)
    _render_workspace_citations(citations)
    _render_workspace_trace(trace)
    _render_create_ticket_button(incident, ticket_client)
    _render_ticket_result()


def _render_workspace_incident(incident: dict[str, Any] | None) -> None:
    """Top-level incident-summary panel (Story 7.2.1)."""
    if not incident:
        st.markdown(
            render_empty_state(
                "No structured incident yet",
                "The orchestrator will populate this when it returns an incident payload.",
                icon="📋",
            ),
            unsafe_allow_html=True,
        )
        return

    title = theme.escape(str(incident.get("title") or "Incident"))
    severity = str(incident.get("severity") or "medium")
    body_bits: list[str] = [
        f"<div class='kv-row'><span class='kv-label'>Title</span>"
        f"<span class='kv-value'><strong>{title}</strong></span></div>",
        f"<div class='kv-row'><span class='kv-label'>Severity</span>"
        f"<span class='kv-value'>{severity_pill(severity)}</span></div>",
    ]
    if incident.get("asset_id"):
        body_bits.append(render_kv("Asset", str(incident["asset_id"])))
    if incident.get("site"):
        body_bits.append(render_kv("Site", str(incident["site"])))
    if incident.get("likely_cause"):
        body_bits.append(render_kv("Likely cause", str(incident["likely_cause"])))
    actions = incident.get("recommended_actions") or []
    if actions:
        items = "".join(f"<li>{theme.escape(a)}</li>" for a in actions)
        body_bits.append(
            f"<div class='kv-row'><span class='kv-label'>Actions</span>"
            f"<span class='kv-value'><ul style='margin:0;padding-left:1rem'>{items}</ul></span></div>"
        )
    similar = incident.get("similar_tickets") or []
    if similar:
        chips = "".join(
            f"<span class='pill pill-neutral'>{theme.escape(str(t))}</span>" for t in similar
        )
        body_bits.append(f"<div class='chip-row'>{chips}</div>")

    st.markdown(
        render_card("Incident summary", "".join(body_bits), accent="primary", icon="📋"),
        unsafe_allow_html=True,
    )


def _render_workspace_editable_draft(incident: dict[str, Any] | None) -> None:
    """Editable ticket-draft form (Story 7.2.1)."""
    if not incident:
        st.markdown(
            render_empty_state(
                "No draft yet",
                "Ask the copilot a question first — the editable draft pre-fills from the structured incident.",
                icon="✏️",
            ),
            unsafe_allow_html=True,
        )
        return

    severity_default = str(incident.get("severity") or "medium").lower()
    if severity_default not in _SEVERITY_OPTIONS:
        severity_default = "medium"
    severity_index = _SEVERITY_OPTIONS.index(severity_default)

    # Section header above the form.
    st.markdown(
        render_card(
            "Editable ticket draft",
            (
                "<div class='card-subcard'>"
                "Pre-filled from the incident. Edit the fields, then click "
                "<strong>Create ticket</strong> below to open the approval modal."
                "</div>"
            ),
            accent="info",
            icon="✏️",
        ),
        unsafe_allow_html=True,
    )

    st.text_input(
        "Title",
        value=str(incident.get("title") or "Incident"),
        key="draft_title",
    )
    st.selectbox(
        "Severity",
        options=list(_SEVERITY_OPTIONS),
        index=severity_index,
        key="draft_severity",
    )
    body_default = _build_default_body(incident)
    st.text_area(
        "Body",
        value=body_default,
        key="draft_body",
        height=180,
        help="The body becomes the ticket's summary. Plain text; "
        "the ticket-mock builds the final ticket body from this.",
    )
    st.text_input(
        "Assignee",
        value="",
        key="draft_assignee",
        placeholder="(optional)",
    )
    st.text_input(
        "Labels (comma-separated)",
        value=", ".join(_build_default_labels(incident)),
        key="draft_labels",
        help="Comma-separated. A severity and related-ticket labels are "
        "auto-added on the orchestrator side.",
    )


def _build_default_body(incident: dict[str, Any]) -> str:
    """Compose the default body shown in the editable draft form."""
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


def _render_workspace_citations(citations: list[dict[str, Any]]) -> None:
    """Top-level citations panel (Story 7.2.2)."""
    if not citations:
        st.markdown(
            render_empty_state(
                "No citations yet",
                "The RAG step will populate this when the orchestrator returns citations.",
                icon="📚",
            ),
            unsafe_allow_html=True,
        )
        return
    cards = "".join(render_citation_card(idx, c) for idx, c in enumerate(citations, start=1))
    st.markdown(
        render_card(
            f"Citations ({len(citations)})",
            cards,
            accent="info",
            icon="📚",
        ),
        unsafe_allow_html=True,
    )


def _render_workspace_trace(trace: list[dict[str, Any]]) -> None:
    """Top-level MCP execution trace panel (Story 7.2.2)."""
    if not trace:
        st.markdown(
            render_empty_state(
                "No MCP tools invoked yet",
                "The chain runner will populate this when it dispatches the first tool.",
                icon="🛠",
            ),
            unsafe_allow_html=True,
        )
        return
    timeline_html = render_timeline(trace)
    st.markdown(
        render_card(
            f"MCP execution trace ({len(trace)} step{'s' if len(trace) != 1 else ''})",
            timeline_html,
            accent="neutral",
            icon="🛠",
        ),
        unsafe_allow_html=True,
    )


def _render_create_ticket_button(
    incident: dict[str, Any] | None,
    ticket_client: TicketClient,
) -> None:
    """The bottom-of-workspace button that opens the confirmation modal."""
    disabled = not incident
    clicked = st.button(
        "🛡 Create ticket",
        disabled=disabled,
        key="create_ticket_button",
        help="Stage a ticket draft for approval",
        use_container_width=True,
    )
    if not clicked or disabled:
        return

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


# --------------------------------------------------------------------------- #
# Confirmation modal — hard constraint #3
# --------------------------------------------------------------------------- #


@st.dialog("Confirm ticket creation")
def _render_confirmation_modal(ticket_client: TicketClient) -> None:
    """The hard-constraint-#3 confirmation modal.

    Inside the modal the approver sees:

    * The draft fields they edited (title, severity, body).
    * The Incident summary (so they can confirm the asset +
      severity they're approving).
    * The citations list (so the approval is evidence-backed).
    * A "What will happen" footer explaining the gated create path.

    The modal calls ``TicketClient.preview`` on entry to project
    the ticket-mock's draft, then ``TicketClient.create`` on
    Approve to persist.
    """
    payload = st.session_state.get(_SESSION_TICKET_MODAL)
    if not isinstance(payload, dict):
        st.session_state[_SESSION_TICKET_MODAL] = None
        st.rerun()
        return

    incident = payload.get("incident") or {}
    draft = payload.get("draft") or {}

    merged = _merge_draft_into_incident(dict(incident), draft)

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

    # ---- Header card ---------------------------------------------------
    if preview_error:
        st.markdown(
            render_card(
                "Could not project draft",
                f"<div class='kv-row'><span class='kv-label'>Code</span>"
                f"<span class='kv-value'>{theme.escape(preview_error)}</span></div>",
                accent="danger",
                icon="⚠️",
            ),
            unsafe_allow_html=True,
        )
    else:
        title = theme.escape(preview.title if preview else draft.get("title", ""))
        severity = str(preview.severity if preview else draft.get("severity", "medium"))
        body_preview = (preview.body if preview else draft.get("body", "")) or ""
        body_excerpt = "\n".join(body_preview.splitlines()[:5])
        if len(body_preview.splitlines()) > 5:
            body_excerpt += "\n…"

        header_bits: list[str] = [
            f"<div class='kv-row'><span class='kv-label'>Title</span>"
            f"<span class='kv-value'><strong>{title}</strong></span></div>",
            f"<div class='kv-row'><span class='kv-label'>Severity</span>"
            f"<span class='kv-value'>{severity_pill(severity)}</span></div>",
        ]
        if preview and preview.labels:
            header_bits.append(
                "<div class='kv-row'><span class='kv-label'>Labels</span>"
                "<span class='kv-value'>"
                + "".join(
                    f"<span class='pill pill-neutral'>{theme.escape(str(label))}</span>"
                    for label in preview.labels
                )
                + "</span></div>"
            )
        if draft.get("assignee"):
            header_bits.append(render_kv("Assignee", str(draft["assignee"])))
        header_bits.append(
            "<div class='card-subcard'>"
            f"<strong>Body preview</strong> (first 5 lines):<br>"
            f"<pre style='white-space:pre-wrap;margin:0.3rem 0 0 0;font-size:0.85rem;'>{theme.escape(body_excerpt)}</pre>"
            "</div>"
        )
        st.markdown(
            render_card("Ticket draft", "".join(header_bits), accent="primary", icon="📝"),
            unsafe_allow_html=True,
        )

    # ---- Evidence summary (citations + trace) ---------------------------
    citations = incident.get("citations") or []
    if citations:
        cards = "".join(render_citation_card(idx, c) for idx, c in enumerate(citations, start=1))
        st.markdown(
            render_card(
                f"Evidence ({len(citations)} citation{'s' if len(citations) != 1 else ''})",
                cards,
                accent="info",
                icon="📚",
            ),
            unsafe_allow_html=True,
        )

    # ---- What will happen ---------------------------------------------
    st.markdown(
        render_card(
            "What will happen",
            "<div class='card-subcard'>"
            "1. The ticket-mock will persist the ticket with the fields above.<br>"
            "2. An audit row will be appended (approved_by = <code>operator</code>).<br>"
            "3. The ticket id will be returned and surfaced in the workspace."
            "</div>",
            accent="neutral",
            icon="🛡",
        ),
        unsafe_allow_html=True,
    )

    # ---- Cancel / Approve buttons ------------------------------------
    col_cancel, _spacer, col_approve = st.columns([1, 2, 1])
    with col_cancel:
        if st.button("Cancel", key="modal_cancel", use_container_width=True):
            log.info("ui.modal_canceled")
            st.session_state[_SESSION_TICKET_MODAL] = None
            st.session_state[_SESSION_TICKET_RESULT] = None
            st.rerun()
    with col_approve:
        if st.button(
            "✅ Approve & create",
            key="modal_approve",
            type="primary",
            use_container_width=True,
        ):
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


def _merge_draft_into_incident(incident: dict[str, Any], draft: dict[str, Any]) -> dict[str, Any]:
    """Merge the user's draft edits into the incident before the
    preview / create calls. The preview endpoint honours the incident
    fields it knows about and ignores the rest."""
    merged = dict(incident)
    if draft.get("title"):
        merged["title"] = draft["title"]
    if draft.get("severity"):
        merged["severity"] = draft["severity"]
    if draft.get("body"):
        merged["summary"] = draft["body"]
        merged["recommended_actions"] = []
    if draft.get("assignee"):
        merged["assignee"] = draft["assignee"]
    if draft.get("labels"):
        merged["labels"] = list(draft["labels"])
    return merged


def _render_ticket_result() -> None:
    """Render the post-approval success or error panel."""
    result = st.session_state.get(_SESSION_TICKET_RESULT)
    if not isinstance(result, dict):
        return
    if "error" in result:
        st.markdown(
            render_card(
                "Ticket creation failed",
                f"<div class='kv-row'><span class='kv-label'>Error</span>"
                f"<span class='kv-value'>{theme.escape(result['error'])}</span></div>",
                accent="danger",
                icon="❌",
            ),
            unsafe_allow_html=True,
        )
        return
    ticket_id = result.get("ticket_id")
    approved_by = result.get("approved_by")
    request_id = result.get("request_id")
    if not ticket_id:
        st.warning("Approval returned but no ticket id was assigned.")
        return
    bits = [
        f"<div class='kv-row'><span class='kv-label'>Ticket id</span>"
        f"<span class='kv-value'><strong>{theme.escape(str(ticket_id))}</strong></span></div>",
        f"<div class='kv-row'><span class='kv-label'>Approved by</span>"
        f"<span class='kv-value'>{theme.escape(str(approved_by or 'unknown'))}</span></div>",
    ]
    if request_id:
        bits.append(
            f"<div class='kv-row'><span class='kv-label'>Request id</span>"
            f"<span class='kv-value'><code>{theme.escape(str(request_id))}</code></span></div>"
        )
    bits.append(
        "<div class='card-subcard'>"
        "The audit row is appended to the ticket-mock's <code>GET /tickets/audit</code> log."
        "</div>"
    )
    st.markdown(
        render_card("Ticket created", "".join(bits), accent="success", icon="✅"),
        unsafe_allow_html=True,
    )


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #


def main() -> None:
    """Streamlit script entrypoint — called by the launcher."""
    st.set_page_config(
        page_title=_PAGE_TITLE,
        page_icon=_PAGE_ICON,
        layout="wide",
        initial_sidebar_state="expanded",
    )
    theme.inject_theme()
    _init_session_state()
    client = get_client()
    ticket_client = get_ticket_client()

    # Top app bar (full width).
    st.markdown(render_app_bar(client.base_url), unsafe_allow_html=True)

    # Sidebar (renders the example prompts + backend config).
    render_sidebar()

    # Sidebar state is "expanded" by default; the main content area
    # already excludes the sidebar's width.

    last_error = st.session_state.get(_SESSION_LAST_ERROR)
    if last_error:
        st.markdown(
            render_card(
                "Backend error",
                f"<div class='kv-row'><span class='kv-label'>Code</span>"
                f"<span class='kv-value'>{theme.escape(last_error['code'])}</span></div>"
                f"<div class='kv-row'><span class='kv-label'>Message</span>"
                f"<span class='kv-value'>{theme.escape(last_error['message'])}</span></div>",
                accent="warning",
                icon="⚠️",
            ),
            unsafe_allow_html=True,
        )

    history = st.session_state[_SESSION_MESSAGES]
    latest = _latest_assistant_message(history)
    chat_column, workspace_column = st.columns([1, 1], gap="large")

    with chat_column:
        render_history(history)
        render_input(client)

    with workspace_column:
        render_workspace(latest, ticket_client)

    # Confirmation modal — only renders when a payload is staged.
    if st.session_state.get(_SESSION_TICKET_MODAL) is not None:
        _render_confirmation_modal(ticket_client)


__all__ = [
    "main",
    "render_history",
    "render_input",
    "render_workspace",
    "render_sidebar",
    "get_client",
    "get_ticket_client",
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
