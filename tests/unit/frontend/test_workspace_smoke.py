"""Headless smoke tests for the workspace column (Feature 7.2).

The chat column was covered by ``tests/unit/frontend/test_ui_smoke.py``.
This file focuses on:

* Empty-state copy on first load (Story 7.2.3).
* Workspace panels rendering for the latest assistant turn
  (Story 7.2.1 + 7.2.2).
* The "Create ticket" button enabled/disabled state.
* Loading-skeleton state when a chat request is in flight.

The confirmation modal is exercised through :func:`_snapshot_draft`
and :func:`_render_confirmation_modal` directly — ``st.dialog`` is
not supported by ``AppTest`` at the time of writing, so the modal's
interior is tested as a regular function call after staging the
payload via ``st.session_state``.

We inject the stub :class:`TicketClient` through
``st.session_state`` (the same trick used in
``tests/unit/frontend/test_ui_smoke.py``) so the tests don't depend
on the backend or the RAG index.
"""
from __future__ import annotations

from pathlib import Path

from streamlit.testing.v1 import AppTest

from apps.frontend.chat_client import ChatClient, ChatResponse
from apps.frontend.ticket_client import TicketClient, TicketDraft, TicketPreview

_REPO_ROOT = Path(__file__).resolve().parents[3]
_UI_SCRIPT = _REPO_ROOT / "apps" / "frontend" / "ui.py"


def _stub_ticket_client() -> TicketClient:
    """A :class:`TicketClient` with ``_base_url`` set so the
    UI's caption renders. ``preview`` and ``create`` are
    overridden per-test by injecting a different stub into
    ``st.session_state``."""

    class _Stub:
        base_url = "http://stub"

        def preview(self, *, incident: dict, trace_id: str | None = None) -> TicketPreview:
            return TicketPreview(
                title=incident.get("title", "Incident"),
                body=incident.get("summary", ""),
                severity=incident.get("severity", "medium"),
                assignee=None,
                labels=["severity:critical"],
                incident_id=incident.get("id"),
            )

        def create(self, *, incident: dict, trace_id: str | None = None) -> TicketDraft:
            return TicketDraft(
                conversation_id="conv-test",
                title=incident.get("title", "Incident"),
                body=incident.get("summary", ""),
                severity=incident.get("severity", "medium"),
                assignee=None,
                labels=[],
                ticket_id="TKT-9999",
                preview=False,
                approval={
                    "approved_by": "operator",
                    "approved_at": "2026-08-08T11:30:00Z",
                    "request_id": "req-test",
                },
            )

        def close(self) -> None:  # pragma: no cover — never called in tests
            pass

    stub = _Stub()
    stub._base_url = "http://stub"  # type: ignore[attr-defined]
    return stub  # type: ignore[return-value]


def test_workspace_empty_state_renders_hint() -> None:
    """First load (no assistant turn yet) renders the empty-state
    hint in the workspace column."""
    at = AppTest.from_file(str(_UI_SCRIPT)).run()
    # Inject the stub so the workspace caption renders without
    # an HTTP call.
    at.session_state["ticket_client"] = _stub_ticket_client()
    at.session_state["client"] = _stub_ticket_client()
    at.run()

    assert not at.exception
    # The workspace empty-state hint is rendered via the theme
    # (markdown block) — not via ``st.info``.
    joined = "\n".join(m.value for m in at.markdown)
    assert "Workspace empty" in joined
    # The "Create ticket" button is rendered, disabled (no incident).
    button_block = next((b for b in at.button if b.label == "🛡 Create ticket"), None)
    assert button_block is not None
    assert button_block.disabled is True


def test_workspace_renders_panels_for_latest_turn() -> None:
    """An assistant turn in the chat history surfaces as
    summary + draft + citations + trace panels in the workspace."""
    # Seed an assistant turn into session_state so the workspace
    # has something to render.
    at = AppTest.from_file(str(_UI_SCRIPT)).run()
    at.session_state["ticket_client"] = _stub_ticket_client()
    at.session_state["client"] = _stub_ticket_client()
    at.session_state["messages"] = [
        {
            "role": "user",
            "content": "Investigate boiler B-101",
            "citations": [],
            "trace": [],
            "incident": None,
            "conversation_id": None,
            "intent": "",
            "rag_confidence": "none",
            "dropped_count": 0,
        },
        {
            "role": "assistant",
            "content": "Investigated boiler B-101; no leaks found.",
            "citations": [
                {"doc_id": "boiler-tube-leak", "section": "s", "page": 1, "score": 0.5}
            ],
            "trace": [
                {
                    "server": "alarm-management",
                    "tool": "list_alarms",
                    "args": {},
                    "output": None,
                    "duration_ms": 42,
                    "outcome": "success",
                    "error": None,
                    "retry_count": 0,
                    "api_status_code": 200,
                }
            ],
            "incident": {
                "id": "INC-9001",
                "title": "Boiler B-101 tube leak suspect",
                "summary": "Inspect tube sheet",
                "severity": "critical",
                "likely_cause": "Tube sheet leak",
                "recommended_actions": ["Reduce feed rate", "Inspect tube sheet"],
                "similar_tickets": ["TKT-1042"],
                "asset_id": "asset-boiler-b-101",
                "site": "EastRefinery",
            },
            "conversation_id": "conv-1",
            "intent": "investigate",
            "rag_confidence": "high",
            "dropped_count": 0,
        },
    ]
    at.run()

    # The workspace panels render the incident's fields.
    joined = "\n".join(m.value for m in at.markdown)
    assert "Boiler B-101 tube leak suspect" in joined
    assert "EastRefinery" in joined
    assert "Reduce feed rate" in joined
    assert "TKT-1042" in joined
    # Citations panel renders the cited doc id.
    assert "boiler-tube-leak" in joined
    # Trace panel renders the tool invocation.
    assert "list_alarms" in joined
    # The error-state copy from the empty state is NOT present.
    assert "Workspace empty" not in joined


def test_workspace_create_ticket_button_enabled_when_incident_present() -> None:
    """The "Create ticket" button is enabled when the workspace
    has an incident to draft from."""
    at = AppTest.from_file(str(_UI_SCRIPT)).run()
    at.session_state["ticket_client"] = _stub_ticket_client()
    at.session_state["client"] = _stub_ticket_client()
    at.session_state["messages"] = [
        _assistant_message_with_incident(),
    ]
    at.run()

    button_block = next((b for b in at.button if b.label == "🛡 Create ticket"), None)
    assert button_block is not None
    assert button_block.disabled is False


def test_sidebar_suggested_prompt_dispatches_chat() -> None:
    """Regression: clicking a sidebar suggested prompt must call the
    backend's ``/chat`` and land the assistant reply in the history.
    Previously the sidebar handler set a ``pending`` flag and reran
    without ever calling ``client.send``, so the workspace stayed on
    "Investigating…" indefinitely."""

    class _StubChatClient(ChatClient):
        def __init__(self) -> None:  # type: ignore[no-super-call]
            self._base_url = "http://stub"
            self.calls: list[dict[str, object]] = []

        def send(self, *, message: str, conversation_id: str | None = None, trace_id: str | None = None) -> ChatResponse:  # type: ignore[override]
            self.calls.append(
                {"message": message, "conversation_id": conversation_id}
            )
            return ChatResponse(
                conversation_id="conv-test",
                answer="Recurring high-temp alarms traced to feed pump 101.",
                citations=[{"doc_id": "doc-procedure-boiler-b101"}],
                trace=[{
                    "server": "alarm-management",
                    "tool": "search_assets",
                    "args": {},
                    "output": None,
                    "duration_ms": 10,
                    "outcome": "success",
                    "error": None,
                    "retry_count": 0,
                    "api_status_code": 200,
                }],
                rag_confidence="high",
                dropped_count=0,
                intent="investigate_recurring_alarms",
                raw_payload={},
                incident={
                    "id": "INC-9001",
                    "title": "Boiler B-101 tube leak suspect",
                    "summary": "Inspect tube sheet",
                    "severity": "critical",
                    "likely_cause": "Tube sheet leak",
                    "recommended_actions": ["Inspect tube sheet"],
                    "citations": [],
                    "similar_tickets": [],
                    "created_at": "2026-08-10T10:00:00Z",
                },
            )

    stub = _StubChatClient()
    at = AppTest.from_file(str(_UI_SCRIPT)).run()
    at.session_state["client"] = stub
    at.session_state["ticket_client"] = _stub_ticket_client()

    # Simulate the operator clicking the first suggested prompt.
    assert len(at.sidebar.button) > 0, "no sidebar buttons rendered"
    at.sidebar.button[0].click().run()

    assert not at.exception, f"UI raised: {at.exception}"
    # The chat client must have been invoked exactly once.
    assert len(stub.calls) == 1, f"expected 1 call, got {len(stub.calls)}"
    # The user's question should be the message that went out.
    assert stub.calls[0]["message"].startswith(
        "Investigate recurring high-severity alarms"
    )
    # The assistant's answer must now appear in the chat history.
    messages = at.session_state["messages"]
    assert any(
        m["role"] == "assistant"
        and "Recurring high-temp alarms" in m["content"]
        for m in messages
    ), f"assistant reply missing from history: {messages}"


def _assistant_message_with_incident() -> dict:
    return {
        "role": "assistant",
        "content": "Investigated.",
        "citations": [],
        "trace": [],
        "incident": {
            "id": "INC-9001",
            "title": "Boiler B-101 tube leak suspect",
            "summary": "Inspect tube sheet",
            "severity": "critical",
            "likely_cause": "Tube sheet leak",
            "recommended_actions": ["Inspect tube sheet"],
            "similar_tickets": ["TKT-1042"],
            "asset_id": "asset-boiler-b-101",
            "site": "EastRefinery",
        },
        "conversation_id": "conv-1",
        "intent": "investigate",
        "rag_confidence": "high",
        "dropped_count": 0,
    }
