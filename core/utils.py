"""Small helpers used everywhere."""
from __future__ import annotations

import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime

from .logging import bind_context, clear_context


def now() -> datetime:
    return datetime.now(UTC)


def new_id() -> str:
    return str(uuid.uuid4())


@dataclass
class TraceContext:
    request_id: str = field(default_factory=new_id)
    conversation_id: str | None = None
    trace_id: str | None = None
    extras: dict[str, str] = field(default_factory=dict)

    def bind(self) -> None:
        bind_context(
            request_id=self.request_id,
            conversation_id=self.conversation_id,
            trace_id=self.trace_id,
            **self.extras,
        )


@contextmanager
def trace_scope(ctx: TraceContext) -> Iterator[TraceContext]:
    ctx.bind()
    try:
        yield ctx
    finally:
        clear_context()
