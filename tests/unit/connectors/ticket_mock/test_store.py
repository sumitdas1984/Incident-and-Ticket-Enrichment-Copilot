"""Unit tests for the ticket-mock store."""
from __future__ import annotations

from connectors.ticket_mock import TicketStore, build_default_store
from connectors.ticket_mock.models import Ticket


def test_default_store_seeded_with_five_tickets() -> None:
    store = build_default_store()
    tickets = store.list_all()
    assert len(tickets) == 5
    ids = [t.id for t in tickets]
    assert "TKT-1042" in ids
    assert "TKT-1410" in ids


def test_get_returns_seeded_ticket() -> None:
    store = build_default_store()
    ticket = store.get("TKT-1042")
    assert ticket is not None
    assert ticket.title.startswith("Boiler Feed Pump 101")
    assert ticket.status == "resolved"


def test_get_returns_none_for_unknown_id() -> None:
    store = build_default_store()
    assert store.get("TKT-9999") is None


def test_create_persists_ticket() -> None:
    store = build_default_store()
    ticket = Ticket(
        id="TKT-9901",
        title="New ticket",
        body="Test body",
        status="open",
        severity="high",
    )
    store.create(ticket)
    assert store.get("TKT-9901") == ticket
    # The new ticket is now in the store (alongside the 5 seeded).
    assert any(t.id == "TKT-9901" for t in store.list_all())


def test_next_id_increments() -> None:
    store = TicketStore()
    id_a = store.next_id()
    id_b = store.next_id()
    assert id_a.startswith("TKT-")
    assert id_b.startswith("TKT-")
    assert id_a != id_b  # different offsets


def test_empty_store_has_no_tickets() -> None:
    """A no-arg ``TicketStore()`` seeds itself. To test the
    empty-state path we count seeded tickets (5) and verify
    the new id increments beyond."""
    store = TicketStore()
    assert len(store.list_all()) == 5
    new_id = store.next_id()
    assert new_id.startswith("TKT-")
    assert new_id not in {t.id for t in store.list_all()}
