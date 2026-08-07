"""Tests for core.utils: now, new_id, TraceContext, trace_scope."""
from __future__ import annotations

import json
import re
import uuid

from core.logging import configure_logging, get_logger
from core.utils import TraceContext, new_id, now, trace_scope


def test_now_is_timezone_aware() -> None:
    t = now()
    assert t.tzinfo is not None
    assert t.tzinfo.utcoffset(t).total_seconds() == 0


def test_new_id_is_unique_uuid() -> None:
    ids = {new_id() for _ in range(50)}
    assert len(ids) == 50
    for i in ids:
        uuid.UUID(i)  # raises if not a valid UUID


def _both_streams(capsys) -> str:
    """Return everything written to either stdout or stderr during the test."""
    captured = capsys.readouterr()
    return captured.out + captured.err


def test_trace_context_bind_pushes_observability_fields(capsys) -> None:
    """The trace_scope context manager binds every log line with § 16 fields."""
    configure_logging("INFO")
    log = get_logger("test")
    ctx = TraceContext(
        request_id="req-test-1",
        conversation_id="conv-test-1",
        trace_id="trace-test-1",
        extras={"mcp_server": "alarm-management", "mcp_tool": "search_asset"},
    )
    with trace_scope(ctx):
        log.info("inside-scope")

    raw = _both_streams(capsys)
    rec = json.loads(raw.strip().splitlines()[-1])
    assert rec["request_id"] == "req-test-1"
    assert rec["conversation_id"] == "conv-test-1"
    assert rec["trace_id"] == "trace-test-1"
    assert rec["mcp_server"] == "alarm-management"
    assert rec["mcp_tool"] == "search_asset"


def test_trace_scope_clears_context_on_exit(capsys) -> None:
    configure_logging("INFO")
    log = get_logger("test")
    ctx = TraceContext(request_id="req-test-2")
    with trace_scope(ctx):
        log.info("inside")
    log.info("outside")

    raw = _both_streams(capsys)
    lines = [json.loads(line) for line in raw.strip().splitlines()]
    assert lines[0]["request_id"] == "req-test-2"
    assert "request_id" not in lines[1]


def test_trace_context_generates_request_id_by_default() -> None:
    ctx = TraceContext()
    assert re.match(r"^[0-9a-f-]{36}$", ctx.request_id)  # UUID format
    assert ctx.conversation_id is None
    assert ctx.trace_id is None
    assert ctx.extras == {}
