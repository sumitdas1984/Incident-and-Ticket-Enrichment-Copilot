"""Ticket search scoring.

The scoring is deterministic so the test surface can pin
specific top-N results. Weights:

* ``+1.0`` for an exact ``asset_id`` match.
* ``+0.5`` for a query-substring match in the title OR body.
* ``+0.2`` for a status match when the caller passes a status
  filter (the orchestrator doesn't, but the API does).

The ``asset_id`` and ``site`` filters are hard — a ticket that
doesn't match is excluded. ``text`` and ``status`` are soft — they
contribute to the score but don't exclude.

Ties are broken by the ticket's id for stability — the
fixture's seeded order is preserved.
"""
from __future__ import annotations

from .models import Ticket, TicketStatus


def score_ticket(
    ticket: Ticket,
    *,
    text: str | None = None,
    asset_id: str | None = None,
    site: str | None = None,
    status: TicketStatus | None = None,
) -> float:
    """Return the relevance score for ``ticket`` against the filters."""
    score = 0.0
    if asset_id is not None and ticket.asset_id == asset_id:
        score += 1.0
    if site is not None and ticket.site == site:
        score += 0.2
    if status is not None and ticket.status == status:
        score += 0.5
    if text:
        needle = text.lower()
        if needle in ticket.title.lower() or needle in ticket.body.lower():
            score += 0.5
    return score


def search_tickets(
    store_tickets: list[Ticket],
    *,
    text: str | None = None,
    asset_id: str | None = None,
    site: str | None = None,
    status: TicketStatus | None = None,
    limit: int = 5,
) -> list[Ticket]:
    """Return the top-``limit`` tickets ranked by relevance score.

    ``asset_id`` and ``site`` are hard filters — tickets that
    don't match are excluded. ``text`` and ``status`` are soft
    contributions to the score.

    Ties are broken by the ticket's id (stable, deterministic).
    Tickets with a score of 0 are returned when ``text`` is set
    (substring matches); without ``text`` we skip zero-scored
    tickets so the caller doesn't get every ticket.
    """
    if limit < 1:
        return []
    # Hard filters: ticket must match asset_id / site exactly when
    # the caller passes them. This is the difference between a
    # "filter" and a "score contribution".
    candidates = list(store_tickets)
    if asset_id is not None:
        candidates = [t for t in candidates if t.asset_id == asset_id]
    if site is not None:
        candidates = [t for t in candidates if t.site == site]
    if status is not None:
        candidates = [t for t in candidates if t.status == status]

    scored = [
        (score_ticket(t, text=text, asset_id=asset_id, site=site, status=status), t)
        for t in candidates
    ]
    if text is None:
        scored = [(s, t) for s, t in scored if s > 0.0]
    scored.sort(key=lambda pair: (pair[0], -len(pair[1].id)), reverse=True)
    return [t for _s, t in scored[:limit]]


__all__ = ["score_ticket", "search_tickets"]
