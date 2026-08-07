"""Tests for core.exceptions: hierarchy, catchability, naming."""
from __future__ import annotations

import pytest

from core.exceptions import (
    AlarmAPIError,
    ConfigError,
    CopilotError,
    MCPError,
    RAGError,
    TicketApprovalRequired,
    TicketError,
)


@pytest.mark.parametrize(
    "exc_cls",
    [
        AlarmAPIError,
        ConfigError,
        MCPError,
        RAGError,
        TicketApprovalRequired,
        TicketError,
    ],
)
def test_concrete_exception_is_copilot_error_and_exception(exc_cls: type[CopilotError]) -> None:
    assert issubclass(exc_cls, CopilotError)
    assert issubclass(exc_cls, Exception)


def test_catch_via_base() -> None:
    """Caller can catch any project error with a single `except CopilotError`."""
    with pytest.raises(CopilotError):
        raise TicketApprovalRequired("user has not approved ticket creation")
    with pytest.raises(CopilotError):
        raise RAGError("retrieval index missing")
    with pytest.raises(Exception):  # noqa: B017  -- also catchable as plain Exception
        raise AlarmAPIError("alarm API 503")


def test_exception_carries_message() -> None:
    err = MCPError("MCP server unreachable at http://mcp:9000")
    assert "MCP server unreachable" in str(err)
    assert err.args == ("MCP server unreachable at http://mcp:9000",)
