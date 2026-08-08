"""Unit tests for the ticket-mock search scoring."""
from __future__ import annotations

from connectors.ticket_mock.models import Ticket
from connectors.ticket_mock.search import score_ticket, search_tickets
from connectors.ticket_mock.store import build_default_store


def test_score_ticket_asset_id_match() -> None:
    ticket = Ticket(
        id="TKT-1",
        title="x",
        body="x",
        asset_id="asset-bfp-101",
    )
    assert score_ticket(ticket, asset_id="asset-bfp-101") == 1.0
    assert score_ticket(ticket, asset_id="asset-bfp-102") == 0.0


def test_score_ticket_text_substring() -> None:
    ticket = Ticket(id="TKT-1", title="Boiler failure", body="leak in the steam line")
    assert score_ticket(ticket, text="leak") >= 0.5
    assert score_ticket(ticket, text="missing") == 0.0


def test_search_tickets_returns_top_n_sorted() -> None:
    store = build_default_store()
    results = search_tickets(store.list_all(), text="boiler", limit=3)
    assert len(results) == 3
    # Top result must be the strongest match (asset_id target).
    assert results[0].id in {"TKT-1042", "TKT-1108"}


def test_search_tickets_respects_limit() -> None:
    store = build_default_store()
    results = search_tickets(store.list_all(), text="boiler", limit=2)
    assert len(results) == 2


def test_search_tickets_with_no_text_returns_zero_filtered() -> None:
    """Without a text query, zero-scored tickets are skipped."""
    store = build_default_store()
    results = search_tickets(store.list_all(), limit=10)
    # No text + no asset_id/site → all 0-scored → empty list.
    assert results == []


def test_search_tickets_asset_id_exact_match() -> None:
    store = build_default_store()
    results = search_tickets(store.list_all(), asset_id="asset-bfp-101", limit=10)
    assert all(t.asset_id == "asset-bfp-101" for t in results)
    assert len(results) == 2


def test_search_tickets_combines_filters() -> None:
    store = build_default_store()
    results = search_tickets(
        store.list_all(),
        asset_id="asset-bfp-101",
        site="EastRefinery",
        limit=10,
    )
    assert all(t.site == "EastRefinery" for t in results)
    assert all(t.asset_id == "asset-bfp-101" for t in results)
    assert len(results) == 2
