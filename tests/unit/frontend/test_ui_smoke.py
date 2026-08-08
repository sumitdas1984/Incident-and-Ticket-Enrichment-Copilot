"""Headless smoke tests for the Streamlit UI.

Story 7.1.1 — the chat surface. Streamlit's ``AppTest`` runs
the script in-process without a browser, so we can assert on
the rendered widgets. We stub :class:`ChatClient` so the test
doesn't depend on the backend or the RAG index.

What we assert:

* ``AppTest`` boots the script without raising (the
  ``set_page_config`` call, session-state init, and the
  ``st.title`` all run).
* The empty-state info callout is present on first load.
* Submitting a message via the chat input appends a user
  turn and then an assistant turn after ``render_input``
  calls :meth:`ChatClient.send`.
* A failing client surfaces an assistant turn whose content
  includes the error code.

Note on patching
----------------

The UI module imports ``build_default_client`` by name into its
own namespace (``from apps.frontend.chat_client import ...
build_default_client``), so patching
``chat_client.build_default_client`` later doesn't affect what
the UI calls. We use :func:`unittest.mock.patch.object` against
the ``ui`` module's local binding (``apps.frontend.ui.build_default_client``)
instead — that reference is what the UI actually invokes.
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


def test_app_boots_and_shows_empty_state() -> None:
    """First load renders the suggested-prompt info callout."""
    # Inject a safe stub client into session_state so ``get_client``
    # never consults ``build_default_client`` and no real HTTP call
    # happens. The first run is just a render check.
    safe = ChatClient(base_url="http://test")
    at = AppTest.from_file(str(_UI_SCRIPT)).run()
    at.session_state["client"] = safe
    at.session_state["ticket_client"] = safe  # Feature 7.2 workspace column
    at.run()

    assert not at.exception
    # The empty-state copy mentions the suggested prompt.
    info_bodies = " ".join(info.value for info in at.info)
    assert "Investigate recurring" in info_bodies
    # The title is the page heading.
    titles = [t.value for t in at.title]
    assert any("Incident Copilot" in t for t in titles)
    # Feature 7.2 — the workspace column header is present.
    subheaders = [s.value for s in at.subheader]
    assert any("Workspace" in s for s in subheaders)


def test_submit_message_appends_user_and_assistant_turns() -> None:
    """Driving the chat input → user turn → spinner → assistant turn."""

    class _StubClient(ChatClient):
        def __init__(self) -> None:  # type: ignore[no-super-call]
            # Skip parent init — no real httpx.Client. The ``base_url``
            # property reads ``self._base_url``; set it directly so
            # ``st.caption(f"Backend: {client.base_url}")`` renders.
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

    # Inject the stub directly into session_state and clear any
    # previously cached client. ``get_client`` consults this cache
    # before calling ``build_default_client``; setting it here
    # sidesteps module-level patching entirely (which doesn't
    # always reach Streamlit's worker thread cleanly).
    at.session_state["client"] = stub
    assert len(at.chat_input) == 1
    at.chat_input[0].set_value("Investigate boiler B-101").run()

    # After the rerun, the assistant message should be rendered.
    markdown_blocks = [m.value for m in at.markdown]
    joined = "\n".join(markdown_blocks)
    assert "You said: Investigate boiler B-101" in joined
    # The expanders for citations / trace / incident exist.
    expander_labels = [e.label for e in at.expander]
    assert any("Citations" in label for label in expander_labels)
    assert any("MCP execution trace" in label for label in expander_labels)
    assert any("Incident" in label for label in expander_labels)


def test_submit_message_with_backend_error_renders_assistant_error() -> None:
    """A failing client surfaces the error code in the assistant turn."""

    class _FailingClient(ChatClient):
        def __init__(self) -> None:  # type: ignore[no-super-call]
            # ``base_url`` reads ``self._base_url``; set it directly so
            # the UI's caption renders. See the matching note in
            # ``_StubClient``.
            self._base_url = "http://stub"

        def send(self, *, message: str, conversation_id: str | None = None, trace_id: str | None = None) -> ChatResponse:
            raise ChatError(
                code="backend_unreachable",
                message="Could not reach the copilot backend: connection refused",
            )

    failing = _FailingClient()
    at = AppTest.from_file(str(_UI_SCRIPT)).run()

    # Inject the failing client into session_state so the rerun
    # surfaces its exception. See the matching comment in
    # ``test_submit_message_appends_user_and_assistant_turns``.
    at.session_state["client"] = failing
    at.chat_input[0].set_value("anything").run()

    markdown_blocks = [m.value for m in at.markdown]
    joined = "\n".join(markdown_blocks)
    assert "backend_unreachable" in joined
    # The error panel at the top is also rendered via ``st.error``.
    error_bodies = " ".join(e.value for e in at.error)
    assert "backend_unreachable" in error_bodies
