"""Streamlit UI for the copilot backend.

Feature 7.1 — Story 7.1.1 (chat interface) + Story 7.1.2
(connect frontend with backend). The UI is a thin client to the
backend's ``POST /chat``:

* The chat input posts the user's message to the backend (Story 7.1.2).
* The response envelope (``ChatResponse``) is rendered with
  expanders for citations, MCP execution trace, and the
  structured ``Incident`` payload (Story 7.1.1, acceptance
  criteria 1).
* Loading, empty, and error states are explicit
  (Story 7.1.1, acceptance criteria 3).
* Conversation state lives in ``st.session_state.messages`` and
  is preserved across reruns. The backend's
  ``conversation_id`` is echoed back in the response and
  threaded into the next request so multi-turn context works.

We intentionally keep all rendering logic in pure functions that
take ``messages`` and a ``client`` so ``tests/unit/frontend/test_ui_smoke.py``
can drive the same code paths through Streamlit's ``AppTest``
headless runner.
"""
from __future__ import annotations

from typing import Any

import streamlit as st

from apps.frontend.chat_client import ChatClient, ChatError, build_default_client
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


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #


def main() -> None:
    """Streamlit script entrypoint — called by the launcher."""
    st.set_page_config(page_title=_PAGE_TITLE, page_icon=_PAGE_ICON)
    _init_session_state()
    client = get_client()

    st.title(f"{_PAGE_ICON} {_PAGE_TITLE}")
    st.caption(f"Backend: `{client.base_url}`")

    last_error = st.session_state.get(_SESSION_LAST_ERROR)
    if last_error:
        st.error(f"[{last_error['code']}] {last_error['message']}")

    render_history(st.session_state[_SESSION_MESSAGES])
    render_input(client)


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
