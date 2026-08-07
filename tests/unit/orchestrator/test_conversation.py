"""Unit tests for the in-memory conversation store."""
from __future__ import annotations

import pytest

from apps.backend.orchestrator.conversation import (
    ConversationHistory,
    ConversationStore,
)
from apps.backend.orchestrator.errors import PlannerError
from apps.backend.orchestrator.request import ConversationMessage


def test_get_or_create_generates_uuid_for_none() -> None:
    store = ConversationStore()
    history = store.get_or_create(None)
    assert history.id
    assert len(history.id) >= 16  # uuid4 hex


def test_get_or_create_returns_existing() -> None:
    store = ConversationStore()
    a = store.get_or_create("abc")
    b = store.get_or_create("abc")
    assert a.id == b.id == "abc"


def test_append_message_increments_history() -> None:
    store = ConversationStore()
    store.get_or_create("abc")
    msg = ConversationMessage(role="user", content="hi")
    after = store.append("abc", msg)
    assert len(after.messages) == 1
    assert after.messages[0].content == "hi"


def test_append_unknown_conversation_raises() -> None:
    store = ConversationStore()
    with pytest.raises(PlannerError, match="not found"):
        store.append("ghost", ConversationMessage(role="user", content="x"))


def test_conversation_history_is_frozen() -> None:
    history = ConversationHistory(id="abc")
    msg = ConversationMessage(role="user", content="hi")
    after = history.with_message(msg)
    assert history.messages == ()
    assert len(after.messages) == 1


def test_conversation_store_len() -> None:
    store = ConversationStore()
    store.get_or_create("a")
    store.get_or_create("b")
    assert len(store) == 2
