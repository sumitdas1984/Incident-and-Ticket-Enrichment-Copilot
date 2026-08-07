"""Deterministic synthetic data for the alarm-api simulator.

A fixed seed produces the same data on every run so the Postman
chaining collection's asset_id / alarm_id / calculation_id variables
land on the same ids every time the simulator boots.
"""
from __future__ import annotations

from datetime import UTC, datetime

from core.domain import Alarm, Asset, Severity

# 5 assets across 3 sites / 3 units. The names mirror the examples
# the Postman collection uses (Boiler Feed Pump 101, Compressor C1,
# Motor M1, etc.) so `?query=Boiler`, `?query=compressor`, `?query=motor`
# each return at least one hit.
SEED_ASSETS: list[Asset] = [
    Asset(
        id="asset-bfp-101",
        name="Boiler Feed Pump 101",
        site="EastRefinery",
        unit="Unit 1",
        asset_class="pump",
    ),
    Asset(
        id="asset-bfp-102",
        name="Boiler Feed Pump 102",
        site="EastRefinery",
        unit="Unit 1",
        asset_class="pump",
    ),
    Asset(
        id="asset-comp-c1",
        name="Compressor C1",
        site="NorthPlant",
        unit="Unit 2",
        asset_class="compressor",
    ),
    Asset(
        id="asset-motor-m1",
        name="Motor M1",
        site="SouthPlant",
        unit="Unit 5",
        asset_class="motor",
    ),
    Asset(
        id="asset-bfp-201",
        name="Boiler Feed Pump 201",
        site="WestRefinery",
        unit="Unit 4",
        asset_class="pump",
    ),
]


# 8 alarms across the 5 assets, 5 severities represented, 2/3
# acknowledged — enough variety to make the summary / trend /
# correlation / flood / rationalization endpoints produce
# non-trivial responses.
SEED_ALARMS: list[Alarm] = [
    Alarm(
        id="alarm-bfp-101-001",
        asset_id="asset-bfp-101",
        severity=Severity.CRITICAL,
        message="BFP high temp",
        raised_at=datetime(2026, 6, 15, 8, 0, tzinfo=UTC),
        acknowledged=False,
    ),
    Alarm(
        id="alarm-bfp-101-002",
        asset_id="asset-bfp-101",
        severity=Severity.HIGH,
        message="BFP low flow",
        raised_at=datetime(2026, 6, 15, 9, 0, tzinfo=UTC),
        acknowledged=False,
    ),
    Alarm(
        id="alarm-bfp-101-003",
        asset_id="asset-bfp-101",
        severity=Severity.MEDIUM,
        message="BFP vibration",
        raised_at=datetime(2026, 6, 16, 10, 0, tzinfo=UTC),
        acknowledged=True,
    ),
    Alarm(
        id="alarm-comp-c1-001",
        asset_id="asset-comp-c1",
        severity=Severity.HIGH,
        message="Compressor surge",
        raised_at=datetime(2026, 6, 17, 11, 0, tzinfo=UTC),
        acknowledged=False,
    ),
    Alarm(
        id="alarm-comp-c1-002",
        asset_id="asset-comp-c1",
        severity=Severity.LOW,
        message="Compressor minor leak",
        raised_at=datetime(2026, 6, 18, 12, 0, tzinfo=UTC),
        acknowledged=True,
    ),
    Alarm(
        id="alarm-motor-m1-001",
        asset_id="asset-motor-m1",
        severity=Severity.MEDIUM,
        message="Motor temp rising",
        raised_at=datetime(2026, 6, 19, 13, 0, tzinfo=UTC),
        acknowledged=False,
    ),
    Alarm(
        id="alarm-bfp-201-001",
        asset_id="asset-bfp-201",
        severity=Severity.HIGH,
        message="BFP vibration",
        raised_at=datetime(2026, 6, 20, 14, 0, tzinfo=UTC),
        acknowledged=False,
    ),
    Alarm(
        id="alarm-bfp-201-002",
        asset_id="asset-bfp-201",
        severity=Severity.LOW,
        message="BFP noise",
        raised_at=datetime(2026, 6, 21, 15, 0, tzinfo=UTC),
        acknowledged=True,
    ),
]
