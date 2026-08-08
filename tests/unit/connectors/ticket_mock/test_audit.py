"""Unit tests for the ticket-mock audit list (Feature 6.2).

The audit list is an in-memory append-only log alongside the
ticket list. Every successful ``POST /tickets/draft`` appends
an :class:`AuditEntry`; the list is exposed via
``GET /tickets/audit`` and bounded by ``limit``.
"""
from __future__ import annotations

from datetime import UTC, datetime

import pytest

from connectors.ticket_mock import TicketStore, build_default_store
from connectors.ticket_mock.models import AuditEntry


def test_default_store_has_empty_audit_list() -> None:
    """A freshly built store has no audit rows."""
    store = build_default_store()
    assert store.list_audit() == []


def test_append_audit_returns_entry_with_allocated_id() -> None:
    """``append_audit`` returns an :class:`AuditEntry` with a
    non-empty ``id`` (uuid4 hex). The same entry appears in
    ``list_audit`` afterwards."""
    store = TicketStore()
    now = datetime.now(tz=UTC)
    entry = store.append_audit(
        ticket_id="TKT-9001",
        request_id="req-1",
        approved_by="operator",
        approved_at=now,
        incident_id="INC-1",
    )
    assert isinstance(entry, AuditEntry)
    assert len(entry.id) == 32  # uuid4 hex
    assert entry.ticket_id == "TKT-9001"
    assert entry.request_id == "req-1"
    assert entry.approved_by == "operator"
    assert entry.approved_at == now
    assert entry.incident_id == "INC-1"
    assert entry.action == "create_ticket"
    assert store.list_audit() == [entry]


def test_append_audit_assigns_unique_ids() -> None:
    """Two appends get two distinct ids."""
    store = TicketStore()
    now = datetime.now(tz=UTC)
    e1 = store.append_audit(
        ticket_id="TKT-9001",
        request_id="req-1",
        approved_by="operator",
        approved_at=now,
        incident_id="INC-1",
    )
    e2 = store.append_audit(
        ticket_id="TKT-9002",
        request_id="req-2",
        approved_by="operator",
        approved_at=now,
        incident_id="INC-2",
    )
    assert e1.id != e2.id


def test_append_audit_preserves_insertion_order() -> None:
    """The audit list is FIFO; later appends come last."""
    store = TicketStore()
    now = datetime.now(tz=UTC)
    entries = [
        store.append_audit(
            ticket_id=f"TKT-{i}",
            request_id=f"req-{i}",
            approved_by="operator",
            approved_at=now,
            incident_id=f"INC-{i}",
        )
        for i in range(5)
    ]
    listed = store.list_audit()
    assert listed == entries


def test_append_audit_handles_missing_incident_id() -> None:
    """``incident_id`` is optional — a write without one is allowed."""
    store = TicketStore()
    now = datetime.now(tz=UTC)
    entry = store.append_audit(
        ticket_id="TKT-9001",
        request_id="req-1",
        approved_by="operator",
        approved_at=now,
        incident_id=None,
    )
    assert entry.incident_id is None


def test_list_audit_returns_independent_copy() -> None:
    """Mutating the returned list does not affect the store."""
    store = TicketStore()
    now = datetime.now(tz=UTC)
    store.append_audit(
        ticket_id="TKT-9001",
        request_id="req-1",
        approved_by="operator",
        approved_at=now,
        incident_id="INC-1",
    )
    listed = store.list_audit()
    listed.clear()
    assert len(store.list_audit()) == 1


@pytest.mark.parametrize("count", [1, 5, 25])
def test_audit_entry_pydantic_roundtrip(count: int) -> None:
    """The :class:`AuditEntry` Pydantic model serialises and
    deserialises round-trip; this guards the wire shape."""
    now = datetime.now(tz=UTC)
    entry = AuditEntry(
        id="a" * 32,
        ticket_id=f"TKT-{count}",
        request_id=f"req-{count}",
        approved_by="operator",
        approved_at=now,
        incident_id="INC-1",
    )
    dumped = entry.model_dump()
    rebuilt = AuditEntry.model_validate(dumped)
    assert rebuilt == entry
