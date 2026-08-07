"""Deterministic synthetic data for the alarm-api simulator.

A fixed seed produces the same data on every run so the Postman
chaining collection's asset_id / alarm_id / calculation_id variables
land on the same ids every time the simulator boots.
"""
from __future__ import annotations

from datetime import UTC, datetime

from core.domain import Alarm, Asset, Severity

# 7 assets across 4 sites / 4 units. The names mirror the examples
# the Postman collection uses (Boiler Feed Pump 101, Compressor C1,
# Motor M1, etc.) so `?query=Boiler`, `?query=compressor`, `?query=motor`
# each return at least one hit. Three motors live in Unit 5 so that
# CHAIN-08 (Motor Correlation) can chain through three distinct ids.
#
# Every asset populates `metadata["unit"]` because the store's
# search_assets() filter reads from `asset.metadata.get("unit")`,
# not from the top-level `unit` field. Keeping the two in sync is
# regression-tested in tests/integration/alarm_api/test_seed.py.
SEED_ASSETS: list[Asset] = [
    Asset(
        id="asset-bfp-101",
        name="Boiler Feed Pump 101",
        site="EastRefinery",
        unit="Unit 1",
        asset_class="pump",
        metadata={"unit": "Unit 1"},
    ),
    Asset(
        id="asset-bfp-102",
        name="Boiler Feed Pump 102",
        site="EastRefinery",
        unit="Unit 1",
        asset_class="pump",
        metadata={"unit": "Unit 1"},
    ),
    Asset(
        id="asset-comp-c1",
        name="Compressor C1",
        site="NorthPlant",
        unit="Unit 2",
        asset_class="compressor",
        metadata={"unit": "Unit 2"},
    ),
    Asset(
        id="asset-motor-m1",
        name="Motor M1",
        site="SouthPlant",
        unit="Unit 5",
        asset_class="motor",
        metadata={"unit": "Unit 5"},
    ),
    Asset(
        id="asset-motor-m2",
        name="Motor M2",
        site="SouthPlant",
        unit="Unit 5",
        asset_class="motor",
        metadata={"unit": "Unit 5"},
    ),
    Asset(
        id="asset-motor-m3",
        name="Motor M3",
        site="SouthPlant",
        unit="Unit 5",
        asset_class="motor",
        metadata={"unit": "Unit 5"},
    ),
    Asset(
        id="asset-bfp-201",
        name="Boiler Feed Pump 201",
        site="WestRefinery",
        unit="Unit 4",
        asset_class="pump",
        metadata={"unit": "Unit 4"},
    ),
]


# 10 alarms across the 7 assets, 5 severities represented, 4/10
# acknowledged — enough variety to make the summary / trend /
# correlation / flood / rationalization endpoints produce
# non-trivial responses. The two extra motor alarms (M2, M3) give
# CHAIN-08's later summary call real data to aggregate.
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
        id="alarm-motor-m2-001",
        asset_id="asset-motor-m2",
        severity=Severity.MEDIUM,
        message="Motor bearing wear",
        raised_at=datetime(2026, 6, 22, 9, 30, tzinfo=UTC),
        acknowledged=False,
    ),
    Alarm(
        id="alarm-motor-m3-001",
        asset_id="asset-motor-m3",
        severity=Severity.LOW,
        message="Motor noise",
        raised_at=datetime(2026, 6, 23, 14, 15, tzinfo=UTC),
        acknowledged=True,
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
