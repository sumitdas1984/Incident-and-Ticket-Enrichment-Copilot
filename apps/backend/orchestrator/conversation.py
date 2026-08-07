"""In-memory conversation store.

The store is a process-local dict keyed by ``conversation_id``
(uuid4 hex). The store is the documented known limitation:
the orchestrator loses conversation context on restart. A
persistent backend (SQLite, Redis) is a future story.

Why a dict, not a database
--------------------------

* The brief's hard constraints do not require persistence.
* The hard timebox (10-14 h) does not accommodate a database
  dependency.
* The orchestrator's tests do not need a real backend; the
  in-memory store is deterministic and trivial to mock.

Why a uuid4 id
--------------

* Stateless — the client can generate it locally and reuse it
  across processes if the backend is replaced.
* Short enough to put in a URL or a log line.
* Globally unique without coordination.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass

from .errors import PlannerError
from .request import ConversationMessage


@dataclass(frozen=True)
class ConversationHistory:
    """The full history for one conversation.

    Frozen so callers can't mutate the conversation underneath
    the orchestrator. Use :meth:`with_message` to append.
    """

    id: str
    messages: tuple[ConversationMessage, ...] = ()

    def with_message(self, message: ConversationMessage) -> ConversationHistory:
        """Return a new history with ``message`` appended."""
        return ConversationHistory(
            id=self.id,
            messages=(*self.messages, message),
        )


class ConversationStore:
    """Process-local dict of conversations keyed by ``conversation_id``.

    Thread-safety: protects internal state with a
    :class:`threading.Lock` so concurrent FastAPI handlers don't
    race on the same conversation id.
    """

    def __init__(self) -> None:
        import threading

        self._lock = threading.Lock()
        self._store: dict[str, ConversationHistory] = {}

    def get_or_create(self, conversation_id: str | None) -> ConversationHistory:
        """Return the conversation for ``conversation_id`` or create a new one.

        A ``None`` or missing id generates a fresh uuid4.
        """
        if conversation_id is None:
            conversation_id = uuid.uuid4().hex
        with self._lock:
            history = self._store.get(conversation_id)
            if history is None:
                history = ConversationHistory(id=conversation_id)
                self._store[conversation_id] = history
            return history

    def append(self, conversation_id: str, message: ConversationMessage) -> ConversationHistory:
        """Append ``message`` to the conversation and return the new history.

        Raises :class:`PlannerError` if the conversation has
        never been seen (the caller should use :meth:`get_or_create`
        first).
        """
        with self._lock:
            history = self._store.get(conversation_id)
            if history is None:
                raise PlannerError(
                    f"conversation {conversation_id!r} not found; "
                    "call get_or_create() first"
                )
            updated = history.with_message(message)
            self._store[conversation_id] = updated
            return updated

    def get(self, conversation_id: str) -> ConversationHistory | None:
        """Return the conversation for ``conversation_id`` or ``None``."""
        with self._lock:
            return self._store.get(conversation_id)

    def __len__(self) -> int:
        with self._lock:
            return len(self._store)


__all__ = ["ConversationHistory", "ConversationStore"]
