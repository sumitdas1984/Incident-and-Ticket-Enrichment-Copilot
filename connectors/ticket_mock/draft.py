"""Ticket draft generation from an Incident-shaped payload.

The draft is composed of:

* ``title`` from ``incident.title`` (the orchestrator's title
  is already informative).
* ``body`` from ``incident.summary`` verbatim, with a numbered
  list of ``incident.recommended_actions`` appended.
* ``severity`` from ``incident.severity``.
* ``labels`` from ``incident.severity`` and any
  ``incident.similar_tickets`` ids.

The generated draft is deterministic for a given input
``incident`` — the test surface pins the exact text.
"""
from __future__ import annotations

from typing import Any

from .models import TicketDraftResponse, TicketSeverity


def build_draft(
    incident: dict[str, Any],
    *,
    approved: bool,
) -> TicketDraftResponse:
    """Compose a deterministic ticket draft from ``incident``."""
    title = str(incident.get("title") or "Incident").strip()
    summary = str(incident.get("summary") or "").strip()
    actions = list(incident.get("recommended_actions") or [])
    severity = _coerce_severity(incident.get("severity"))
    labels = _build_labels(incident, severity)
    body = _compose_body(summary, actions)

    return TicketDraftResponse(
        title=title,
        body=body,
        severity=severity,
        labels=labels,
        preview=not approved,
        ticket_id=None,
    )


def _compose_body(summary: str, actions: list[Any]) -> str:
    """``summary`` + a numbered list of ``actions`` if any."""
    if not actions:
        return summary
    action_lines = "\n".join(f"{i + 1}. {a}" for i, a in enumerate(actions))
    return f"{summary}\n\nRecommended actions:\n{action_lines}"


def _build_labels(incident: dict[str, Any], severity: TicketSeverity) -> list[str]:
    """Severity + similar-ticket ids as labels."""
    labels = [f"severity:{severity}"]
    for tid in incident.get("similar_tickets") or []:
        labels.append(f"related:{tid}")
    return labels


def _coerce_severity(raw: Any) -> TicketSeverity:
    """Map the orchestrator's severity to the ticket's severity band.

    Defaults to ``"medium"`` when the input is missing or invalid.
    """
    if not isinstance(raw, str):
        return "medium"
    raw_lower = raw.lower()
    if raw_lower in ("low", "medium", "high", "critical"):
        return raw_lower  # type: ignore[return-value]
    return "medium"


__all__ = ["build_draft"]
