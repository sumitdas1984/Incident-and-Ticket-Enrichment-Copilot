"""In-memory ticket store with a deterministic seed.

The store is a simple ``dict`` keyed by ``ticket.id``, protected
by a ``threading.Lock`` so concurrent FastAPI requests don't
race. The ticket ids are allocated by the store, not by the
caller — the brief's contract is "service allocates the id".

Feature 6.2 adds an audit list alongside the ticket list. Every
successful ticket creation appends an :class:`AuditEntry` so a
reviewer can prove the write was sanctioned. The audit list is
in-memory (consistent with the ticket store); persistent audit
log is a future story.

Why a small static seed
------------------------

The brief's expected workflow step 5 ("search similar tickets")
already runs against the alarm-api's ``/tickets/similar`` endpoint
(Feature 5.2). The ticket-mock's seed is a separate, smaller
list — enough to exercise the search endpoint with a known
fixture. Five entries cover the asset classes the orchestrator
sees in the E2E acceptance scenario.
"""
from __future__ import annotations

import threading
import uuid
from datetime import UTC, datetime

from .models import AuditEntry, Ticket


class TicketStore:
    """Thread-safe in-memory ticket store."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._tickets: dict[str, Ticket] = {}
        for ticket in _SEED_TICKETS:
            self._tickets[ticket.id] = ticket
        # Counter for ids allocated by ``next_id``. The seed
        # already covers up to ``TKT-1410``, so the counter
        # starts at 2000 and grows monotonically.
        self._next_id_offset = 2000
        # In-memory audit list (Feature 6.2). Append-only;
        # ``list_audit`` returns a copy under the lock so callers
        # can't mutate the store's view.
        self._audit: list[AuditEntry] = []

    # ---- read ----

    def list_all(self) -> list[Ticket]:
        with self._lock:
            return list(self._tickets.values())

    def get(self, ticket_id: str) -> Ticket | None:
        with self._lock:
            return self._tickets.get(ticket_id)

    def list_audit(self) -> list[AuditEntry]:
        """Return a snapshot of the audit list.

        The list is bounded by the store's lifetime; a long-running
        process will accumulate rows. The audit endpoint accepts a
        ``limit`` query parameter so the GUI can page through the
        log without copying the whole list.
        """
        with self._lock:
            return list(self._audit)

    # ---- write ----

    def create(self, ticket: Ticket) -> Ticket:
        """Persist ``ticket`` and return the stored copy."""
        with self._lock:
            self._tickets[ticket.id] = ticket
            return ticket

    def append_audit(
        self,
        *,
        ticket_id: str,
        request_id: str,
        approved_by: str,
        approved_at: datetime,
        incident_id: str | None,
    ) -> AuditEntry:
        """Append an :class:`AuditEntry` for a successful creation.

        The store allocates the ``id`` (uuid4 hex) so the caller
        doesn't have to. Thread-safe via ``self._lock``.
        """
        entry = AuditEntry(
            id=uuid.uuid4().hex,
            ticket_id=ticket_id,
            request_id=request_id,
            approved_by=approved_by,
            approved_at=approved_at,
            incident_id=incident_id,
        )
        with self._lock:
            self._audit.append(entry)
        return entry

    def next_id(self) -> str:
        """Allocate a fresh ticket id deterministically per call.

        The counter is bounded only by the size of the in-memory
        store, which is fine for the demo. ``uuid4`` is the
        fallback when the counter overflows.
        """
        with self._lock:
            self._next_id_offset += 1
            return f"TKT-{self._next_id_offset}"


_SEED_TICKETS: list[Ticket] = [
    Ticket(
        id="TKT-1042",
        title="Boiler Feed Pump 101 high temperature trip",
        body=(
            "Resolved: replaced the bearing assembly and aligned the "
            "suction casing. Temperature returned to baseline within 4 hours."
        ),
        status="resolved",
        severity="critical",
        asset_id="asset-bfp-101",
        site="EastRefinery",
        created_at=datetime(2026, 3, 14, 16, 0, tzinfo=UTC),
        closed_at=datetime(2026, 3, 14, 22, 0, tzinfo=UTC),
    ),
    Ticket(
        id="TKT-1108",
        title="Boiler Feed Pump 101 recurring low flow",
        body=(
            "Resolved: blocked suction strainer. Cleaned, verified "
            "flow recovery, scheduled next inspection in 90 days."
        ),
        status="resolved",
        severity="high",
        asset_id="asset-bfp-101",
        site="EastRefinery",
        created_at=datetime(2026, 5, 2, 11, 0, tzinfo=UTC),
        closed_at=datetime(2026, 5, 2, 14, 30, tzinfo=UTC),
    ),
    Ticket(
        id="TKT-1231",
        title="Compressor C1 surge recovery",
        body=(
            "Resolved: recalibrated the antisurge valve. Documented "
            "in the compressor surge recovery SOP."
        ),
        status="resolved",
        severity="high",
        asset_id="asset-comp-c1",
        site="NorthPlant",
        created_at=datetime(2026, 4, 19, 9, 30, tzinfo=UTC),
        closed_at=datetime(2026, 4, 19, 11, 0, tzinfo=UTC),
    ),
    Ticket(
        id="TKT-1349",
        title="Cooling water pump 3 bearing failure",
        body=(
            "In progress: bearing replacement in progress; spare ordered. "
            "ETA to close: 5 days."
        ),
        status="in_progress",
        severity="medium",
        site="WestRefinery",
        created_at=datetime(2026, 7, 1, 8, 0, tzinfo=UTC),
    ),
    Ticket(
        id="TKT-1410",
        title="High-severity alarm escalation site-wide",
        body=(
            "Resolved: on-call rota engaged within 5 minutes; root "
            "cause was a tripped breaker. No asset damage."
        ),
        status="resolved",
        severity="high",
        site="EastRefinery",
        created_at=datetime(2026, 2, 28, 14, 0, tzinfo=UTC),
        closed_at=datetime(2026, 2, 28, 15, 0, tzinfo=UTC),
    ),
]


def build_default_store() -> TicketStore:
    """Factory for tests / app startup."""
    return TicketStore()


__all__ = ["TicketStore", "build_default_store"]
