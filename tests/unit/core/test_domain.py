"""Tests for core.domain: round-trip, frozen models, enums, validation."""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from core.domain import (
    Alarm,
    AlarmSummary,
    Asset,
    Citation,
    Incident,
    OperatorRecommendation,
    Severity,
    TicketDraft,
    TraceStep,
)


def test_severity_enum_values() -> None:
    assert Severity.LOW.value == "low"
    assert Severity.MEDIUM.value == "medium"
    assert Severity.HIGH.value == "high"
    assert Severity.CRITICAL.value == "critical"


def test_asset_round_trip() -> None:
    a = Asset(id="a-1", name="Boiler Feed Pump 101", site="EastRefinery", asset_class="pump")
    dumped = a.model_dump_json()
    reloaded = Asset.model_validate_json(dumped)
    assert a == reloaded


def test_asset_is_frozen() -> None:
    """Asset and Alarm are emitted from the alarm API and must not be mutated."""
    a = Asset(id="a-1", name="Boiler", site="EastRefinery")
    with pytest.raises(ValidationError):
        a.name = "Changed"  # type: ignore[misc]


def test_alarm_requires_fields() -> None:
    with pytest.raises(ValidationError):
        Alarm.model_validate({"id": "al-1"})  # missing asset_id, severity, message, raised_at


def test_alarm_severity_accepts_string() -> None:
    """Severity is a str enum; Pydantic v2 coerces strings on validate."""
    a = Alarm.model_validate(
        {
            "id": "al-1",
            "asset_id": "a-1",
            "severity": "high",  # str, not enum
            "message": "BFP high temp",
            "raised_at": "2026-08-07T10:00:00Z",
        }
    )
    assert a.severity == Severity.HIGH


def test_alarm_summary_default_items() -> None:
    s = AlarmSummary()
    assert s.items == []
    assert s.total == 0
    assert s.severity is None


def test_alarm_summary_with_alarms() -> None:
    a1 = Alarm(
        id="al-1",
        asset_id="a-1",
        severity=Severity.HIGH,
        message="BFP high temp",
        raised_at="2026-08-07T10:00:00Z",  # type: ignore[arg-type]
    )
    a2 = Alarm(
        id="al-2",
        asset_id="a-1",
        severity=Severity.LOW,
        message="BFP low flow",
        raised_at="2026-08-07T10:01:00Z",  # type: ignore[arg-type]
    )
    s = AlarmSummary(items=[a1, a2], total=2)
    dumped = s.model_dump_json()
    reloaded = AlarmSummary.model_validate_json(dumped)
    assert reloaded.total == 2
    assert len(reloaded.items) == 2
    assert reloaded.items[0].id == "al-1"


def test_operator_recommendation_priority_score_bounds() -> None:
    OperatorRecommendation(alarm_id="al-1", priority_score=50)
    OperatorRecommendation(alarm_id="al-1", priority_score=0)
    OperatorRecommendation(alarm_id="al-1", priority_score=100)
    with pytest.raises(ValidationError):
        OperatorRecommendation(alarm_id="al-1", priority_score=101)
    with pytest.raises(ValidationError):
        OperatorRecommendation(alarm_id="al-1", priority_score=-1)


def test_citation_optional_score() -> None:
    c = Citation(doc_id="doc-1")
    assert c.section is None
    assert c.page is None
    assert c.score is None
    assert c.excerpt is None
    dumped = c.model_dump_json()
    reloaded = Citation.model_validate_json(dumped)
    assert c == reloaded


def test_citation_full() -> None:
    c = Citation(doc_id="doc-1", section="4.2", page=12, score=0.87, excerpt="...")
    assert c.page == 12
    assert 0.0 <= c.score <= 1.0


def test_incident_round_trip() -> None:
    i = Incident(
        id="inc-1",
        title="BFP overheat",
        summary="Boiler Feed Pump 101 tripped on high temp.",
        severity=Severity.CRITICAL,
        likely_cause="Pressure sensor drift",
        recommended_actions=["Replace sensor", "Reset pump"],
        citations=[Citation(doc_id="doc-1"), Citation(doc_id="doc-2")],
        similar_tickets=["TKT-100", "TKT-101"],
        created_at="2026-08-07T10:00:00Z",  # type: ignore[arg-type]
    )
    dumped = i.model_dump_json()
    reloaded = Incident.model_validate_json(dumped)
    assert reloaded.id == i.id
    assert reloaded.severity == Severity.CRITICAL
    assert len(reloaded.citations) == 2


def test_ticket_draft_round_trip() -> None:
    t = TicketDraft(
        title="Replace pressure sensor on BFP 101",
        body="Sensor drifting, triggering false high-temp alarms.",
        severity=Severity.HIGH,
        incident_id="inc-1",
        assignee="ops-team",
        labels=["sensor", "bfp-101"],
    )
    dumped = t.model_dump_json()
    reloaded = TicketDraft.model_validate_json(dumped)
    assert t == reloaded


def test_trace_step_outcome_default() -> None:
    step = TraceStep(server="alarm-management", tool="search_asset", duration_ms=120)
    assert step.outcome == "success"
    assert step.retry_count == 0
    assert step.error is None
    assert step.api_status_code is None
    assert step.output is None


def test_trace_step_error_outcome() -> None:
    step = TraceStep(
        server="alarm-management",
        tool="get_alarm",
        duration_ms=5000,
        outcome="timeout",
        error="Connection refused",
        retry_count=3,
        api_status_code=503,
    )
    dumped = step.model_dump_json()
    reloaded = TraceStep.model_validate_json(dumped)
    assert reloaded.outcome == "timeout"
    assert reloaded.error == "Connection refused"
    assert reloaded.retry_count == 3
    assert reloaded.api_status_code == 503


def test_all_models_round_trip_via_json() -> None:
    """Every model survives a JSON dump + parse round-trip with no data loss."""
    import json

    samples = [
        Asset(id="a", name="Pump", site="SiteA"),
        Alarm(
            id="al",
            asset_id="a",
            severity=Severity.HIGH,
            message="x",
            raised_at="2026-08-07T10:00:00Z",  # type: ignore[arg-type]
        ),
        AlarmSummary(items=[], total=0),
        OperatorRecommendation(alarm_id="al", priority_score=10, actions=["a"]),
        Citation(doc_id="d"),
        Incident(
            id="i",
            title="t",
            summary="s",
            severity=Severity.LOW,
            created_at="2026-08-07T10:00:00Z",  # type: ignore[arg-type]
        ),
        TicketDraft(title="t", body="b", severity=Severity.MEDIUM),
        TraceStep(server="s", tool="t", duration_ms=1),
    ]
    for sample in samples:
        # dump -> parse -> compare as plain dict
        original = sample.model_dump(mode="json")
        cls = type(sample)
        reloaded = cls.model_validate_json(json.dumps(original))
        assert reloaded.model_dump(mode="json") == original
