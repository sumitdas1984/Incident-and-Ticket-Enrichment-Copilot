"""Pydantic request / response models for the alarm-api simulator.

These are intentionally separate from core.domain (which is the
domain layer) — these are HTTP transport shapes and may diverge
from the canonical domain types as the API evolves.

The Postman collection's chaining scripts reference `body.results[0].
asset_id` and `body.data[0].alarm_id` — so the response shapes here
alias the domain field `id` to the transport field `asset_id` /
`alarm_id` via a `by_alias=True` serialization + `populate_by_name=
True`. Internal code keeps using `id`; the wire format uses
`asset_id` / `alarm_id`.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from core.domain import Alarm, Asset, Severity


class AssetOut(Asset):
    """Asset response shape. Serializes 'id' as 'asset_id' on the wire."""

    model_config = ConfigDict(populate_by_name=True)


class AlarmOut(Alarm):
    """Alarm response shape. Serializes 'id' as 'alarm_id' on the wire."""

    model_config = ConfigDict(populate_by_name=True)


# Wire-format aliases for the response fields. We use `by_alias=True`
# at serialization time to emit `asset_id` / `alarm_id` in the JSON.
# Keep these as module-level constants so routers and tests can use them.
ALIAS_ASSET_ID = "asset_id"
ALIAS_ALARM_ID = "alarm_id"


def _alias_dump(model: BaseModel) -> dict[str, Any]:
    """Serialize a response model with `id` -> `asset_id` / `alarm_id` aliases."""
    data = model.model_dump(mode="json")
    if "id" in data and "asset_id" not in data:
        data["asset_id"] = data.pop("id")
    if "id" in data and "alarm_id" not in data:
        # Already renamed by previous branch.
        data["alarm_id"] = data.pop("id")
    return data


def asset_out(asset: Asset) -> dict[str, Any]:
    return _alias_dump(AssetOut.model_validate(asset.model_dump()))


def alarm_out(alarm: Alarm) -> dict[str, Any]:
    return _alias_dump(AlarmOut.model_validate(alarm.model_dump()))


class AssetSearchResponse(BaseModel):
    results: list[dict[str, Any]]
    total: int
    query: str


class AssetMetadataResponse(BaseModel):
    asset: dict[str, Any]
    extra: dict[str, Any] = Field(default_factory=dict)


class AlarmListResponse(BaseModel):
    data: list[dict[str, Any]]
    page: int
    page_size: int
    total: int


class TimeRange(BaseModel):
    model_config = ConfigDict(extra="forbid")
    start_time: datetime
    end_time: datetime


class AlarmSummaryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    asset_ids: list[str] | None = None
    site: str | None = None
    unit: str | None = None
    time_range: TimeRange
    severity: list[Severity] | None = None
    group_by: list[str] | None = None
    kpis: list[str] | None = None
    alarm_types: list[str] | None = None


class AlarmSummaryResponse(BaseModel):
    groups: list[dict[str, Any]]
    total: int
    kpis: dict[str, Any] = Field(default_factory=dict)


class AlarmTrendsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    asset_ids: list[str] | None = None
    site: str | None = None
    unit: str | None = None
    time_range: TimeRange
    bucket: Literal["daily", "hourly"] = "daily"
    metrics: list[str] = Field(default_factory=list)


class AlarmTrendsResponse(BaseModel):
    buckets: list[dict[str, Any]]


class CorrelationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    asset_ids: list[str] = Field(default_factory=list)
    time_range: TimeRange
    correlation_method: Literal["cooccurrence"] = "cooccurrence"
    lag_window_minutes: int = 15
    severity_threshold: Severity | None = None
    min_support: int = 1


class CorrelationResponse(BaseModel):
    pairs: list[dict[str, Any]]
    method: str


class FloodAnalysisRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    unit: str
    time_range: TimeRange
    threshold_count: int = 10
    rolling_window_minutes: int = 10


class FloodAnalysisResponse(BaseModel):
    flood_windows: list[dict[str, Any]]
    unit: str


class RationalizationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    asset_ids: list[str] | None = None
    site: str | None = None
    unit: str | None = None
    time_range: TimeRange
    recurrence_threshold: int = 5
    stale_minutes_threshold: int = 180


class RationalizationResponse(BaseModel):
    candidates: list[dict[str, Any]]


class PriorityScoreRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    alarm_id: str


class PriorityScoreResponse(BaseModel):
    alarm_id: str
    priority_score: int = Field(ge=0, le=100)
    factors: dict[str, Any] = Field(default_factory=dict)


class RecommendationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    alarm_id: str
    include_related: bool = False
    include_asset_context: bool = False
    include_historical_pattern: bool = False


class CalculationGenerateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    calculation_type: str
    filters: dict[str, Any] = Field(default_factory=dict)


class CalculationGenerateResponse(BaseModel):
    calculation_id: str
    calculation_type: str
    code: str


class CalculationExecuteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    calculation_id: str
    filters: dict[str, Any] = Field(default_factory=dict)


class CalculationExecuteResponse(BaseModel):
    calculation_id: str
    result: dict[str, Any]


class KPIDefinitionsResponse(BaseModel):
    kpis: list[dict[str, Any]]


class HealthResponse(BaseModel):
    status: str
    service: str
    version: str = "0.1.0"
