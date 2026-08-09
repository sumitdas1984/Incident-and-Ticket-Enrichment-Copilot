"""Per-request context passed to every MCP tool handler.

Holds the trace identifiers used throughout the system (alarm-api,
MCP server, orchestrator, GUI) and the alarm-api bearer token.
The token is held as `SecretStr` so it never accidentally ends up
in a log line or trace dump.
"""
from __future__ import annotations

from dataclasses import dataclass

from pydantic import SecretStr


@dataclass(frozen=True)
class ToolContext:
    """Read-only context injected into every registered tool handler."""

    trace_id: str
    """End-to-end trace identifier; mirrors X-Trace-Id on alarm-api calls."""

    conversation_id: str | None
    """Chat-session identifier. None for one-off / scheduled calls."""

    request_id: str | None
    """Per-request identifier inside a conversation."""

    alarm_api_token: SecretStr
    """Bearer token the handler must send to the alarm-api simulator."""

    @classmethod
    def make(
        cls,
        *,
        trace_id: str,
        conversation_id: str | None = None,
        request_id: str | None = None,
        alarm_api_token: str | None = None,
    ) -> ToolContext:
        """Build a context, defaulting the token to the configured value.

        Production callers should pass `alarm_api_token` explicitly from
        the request headers; tests can omit it to fall back to whatever
        `core.config.get_settings()` resolves.
        """
        if alarm_api_token is None:
            from core.config import get_settings  # local import keeps top of module cheap

            alarm_api_token = get_settings().alarm_api_token.get_secret_value()
        return cls(
            trace_id=trace_id,
            conversation_id=conversation_id,
            request_id=request_id,
            alarm_api_token=SecretStr(alarm_api_token),
        )
