"""Tests for core.logging: JSON output, context binding, no secret leakage."""
from __future__ import annotations

import json

from core.logging import bind_context, clear_context, configure_logging, get_logger


def test_log_emits_valid_json(capsys) -> None:
    """configure_logging + get_logger().info produces a single JSON line."""
    configure_logging("INFO")
    log = get_logger("test_log_emits_valid_json")
    log.info("hello", answer=42)

    raw = capsys.readouterr().out
    assert raw.strip(), "expected at least one log line"
    record = json.loads(raw.strip().splitlines()[-1])
    assert record["event"] == "hello"
    assert record["answer"] == 42
    assert record["level"] == "info"
    assert "timestamp" in record


def test_bind_context_propagates_to_log(capsys) -> None:
    """Fields set via bind_context appear in every subsequent log line."""
    configure_logging("INFO")
    log = get_logger("test_bind_context_propagates_to_log")
    bind_context(request_id="req-123", conversation_id="conv-456")
    log.info("first")
    log.info("second", extra_field="x")

    raw = capsys.readouterr().out
    lines = raw.strip().splitlines()
    assert len(lines) == 2
    for line in lines:
        rec = json.loads(line)
        assert rec["request_id"] == "req-123"
        assert rec["conversation_id"] == "conv-456"
    assert json.loads(lines[1])["extra_field"] == "x"


def test_clear_context_removes_bindings(capsys) -> None:
    """After clear_context, previously bound fields don't appear."""
    configure_logging("INFO")
    log = get_logger("test_clear_context_removes_bindings")
    bind_context(request_id="req-123")
    log.info("with-context")
    clear_context()
    log.info("no-context")

    raw = capsys.readouterr().out
    lines = raw.strip().splitlines()
    assert "request_id" in json.loads(lines[0])
    assert "request_id" not in json.loads(lines[1])


def test_secretstr_renders_redacted(capsys) -> None:
    """SecretStr values are redacted by structlog's pydantic integration.

    Passing a pydantic.SecretStr as a kwarg to log.info() should NOT
    appear in plain text in the log output.
    """
    from pydantic import SecretStr

    configure_logging("INFO")
    log = get_logger("test_secretstr_renders_redacted")
    secret = SecretStr("sk-do-not-leak-me-1234567890")
    log.info("login", token=secret)  # type: ignore[arg-type]
    raw = capsys.readouterr().out
    # The literal secret string must not appear anywhere in the log output.
    assert "sk-do-not-leak-me" not in raw, (
        f"SecretStr value leaked into log output: {raw!r}"
    )
