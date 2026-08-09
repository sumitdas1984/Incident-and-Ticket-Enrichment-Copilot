"""Headless smoke tests for the Streamlit UI.

Story 7.1.1 — the chat surface. Streamlit's ``AppTest`` runs
the script in-process without a browser, so we can assert on
the rendered widgets. We stub :class:`ChatClient` so the test
doesn't depend on the backend or the RAG index.

What we assert:

* ``AppTest`` boots the script without raising (the
  ``set_page_config`` call, session-state init, and the
  ``render_app_bar`` / theme-injection all run).
* The empty-state copy renders on first load.
* Submitting a message via the chat input appends a user
  turn and then an assistant turn after ``render_input``
  calls :meth:`ChatClient.send`.
* A failing client surfaces an assistant turn whose content
  includes the error code.

The UI renders cards via ``st.markdown(unsafe_allow_html=True)``
(not via ``st.info`` / ``st.expander``), so the assertions grep
the rendered HTML inside ``at.markdown``.

Note on patching
----------------

The UI module imports ``build_default_client`` by name into its
own namespace, so patching ``chat_client.build_default_client``
later doesn't affect what the UI calls. We inject the stub
directly into ``st.session_state`` after the first ``AppTest.run()``
so the rerun picks it up.
"""
from __future__ import annotations

from pathlib import Path

from streamlit.testing.v1 import AppTest

from apps.frontend.chat_client import ChatClient, ChatError, ChatResponse

# ``AppTest.from_file`` resolves relative paths against the test
# file's directory, not cwd — pin to the repo root so the path
# works no matter how pytest is invoked.
_REPO_ROOT = Path(__file__).resolve().parents[3]
_UI_SCRIPT = _REPO_ROOT / "apps" / "frontend" / "ui.py"


def _all_markdown(at: AppTest) -> str:
    """Concatenate every markdown block into one searchable string."""
    return "\n".join(m.value for m in at.markdown)


def test_app_boots_and_shows_empty_state() -> None:
    """First load renders the empty-state copy in the chat column."""
    safe = ChatClient(base_url="http://test")
    at = AppTest.from_file(str(_UI_SCRIPT)).run()
    at.session_state["client"] = safe
    at.session_state["ticket_client"] = safe  # Feature 7.2 workspace column
    at.run()

    assert not at.exception
    # The chat column's empty state copy mentions the suggested prompts.
    joined = _all_markdown(at)
    assert "Start a conversation" in joined
    # The sidebar's example prompts appear as buttons (Streamlit's
    # ``st.button`` labels are visible in the page DOM).
    sidebar_button_labels = [b.label for b in at.button]
    assert any("Investigate recurring high-severity alarms" in label for label in sidebar_button_labels)
    # The workspace column's empty state copy is present.
    assert "Workspace empty" in joined


def test_submit_message_appends_user_and_assistant_turns() -> None:
    """Driving the chat input → user turn → spinner → assistant turn."""

    class _StubClient(ChatClient):
        def __init__(self) -> None:  # type: ignore[no-super-call]
            self._base_url = "http://stub"

        def send(self, *, message: str, conversation_id: str | None = None, trace_id: str | None = None) -> ChatResponse:
            return ChatResponse(
                conversation_id="conv-test",
                answer=f"You said: {message}",
                citations=[{"doc_id": "x", "section": "s", "page": 1, "score": 0.5}],
                trace=[{
                    "server": "alarm-management",
                    "tool": "list_alarms",
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
                intent="test",
                raw_payload={},
                incident={
                    "id": "INC-1",
                    "title": "Test",
                    "summary": "Summary",
                    "severity": "high",
                    "likely_cause": None,
                    "recommended_actions": ["a"],
                    "citations": [],
                    "similar_tickets": [],
                    "created_at": "2026-08-08T10:00:00Z",
                },
            )

    stub = _StubClient()
    at = AppTest.from_file(str(_UI_SCRIPT)).run()
    at.session_state["client"] = stub
    assert len(at.chat_input) == 1
    at.chat_input[0].set_value("Investigate boiler B-101").run()
    at.session_state["client"] = stub  # cached client survives the rerun

    joined = _all_markdown(at)
    assert "You said: Investigate boiler B-101" in joined
    # The assistant message card carries the citation + trace
    # count pills (rendered via the theme).
    assert "1 citation" in joined
    assert "1 step" in joined
    # The structured Incident card surfaces under the assistant turn.
    assert "Structured Incident" in joined
    assert "Severity" in joined


def test_submit_message_with_backend_error_renders_assistant_error() -> None:
    """A failing client surfaces the error code in the assistant turn."""

    class _FailingClient(ChatClient):
        def __init__(self) -> None:  # type: ignore[no-super-call]
            self._base_url = "http://stub"

        def send(self, *, message: str, conversation_id: str | None = None, trace_id: str | None = None) -> ChatResponse:
            raise ChatError(
                code="backend_unreachable",
                message="Could not reach the copilot backend: connection refused",
            )

    failing = _FailingClient()
    at = AppTest.from_file(str(_UI_SCRIPT)).run()
    at.session_state["client"] = failing
    at.chat_input[0].set_value("anything").run()
    at.session_state["client"] = failing  # cached client survives the rerun

    joined = _all_markdown(at)
    assert "backend_unreachable" in joined
