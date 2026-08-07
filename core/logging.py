"""Structured JSON logging with per-request context binding."""
from __future__ import annotations

import logging
import sys
from collections.abc import MutableMapping
from contextvars import ContextVar
from typing import Any

import structlog

# Observability fields from Submission § 16. Bound via structlog's
# contextvars so a single log call carries them all without manual
# plumbing.
_LOG_CONTEXT: ContextVar[dict[str, Any] | None] = ContextVar("log_context", default=None)


def bind_context(**kwargs: Any) -> None:
    """Bind values that every subsequent log line in this context carries."""
    current = _LOG_CONTEXT.get() or {}
    _LOG_CONTEXT.set({**current, **kwargs})


def clear_context() -> None:
    _LOG_CONTEXT.set(None)


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    if name is None:
        name = __name__
    return structlog.get_logger(name)


def _add_context(
    _: Any,
    __: str,
    event_dict: MutableMapping[str, Any],
) -> MutableMapping[str, Any]:
    current = _LOG_CONTEXT.get()
    if current:
        for k, v in current.items():
            event_dict.setdefault(k, v)
    return event_dict


def configure_logging(level: str = "INFO") -> None:
    """Wire stdlib logging + structlog. Call once at app startup."""
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=getattr(logging, level),
    )
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            _add_context,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(getattr(logging, level)),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )
