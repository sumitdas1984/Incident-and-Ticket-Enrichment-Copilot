"""Alarm endpoints: list, by-id, summary, trends, correlation, flood, rationalization, priority-score."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request

from core.domain import Severity

from ..auth import require_bearer
from ..errors import NotFoundError
from ..models import (
    AlarmListResponse,
    AlarmSummaryRequest,
    AlarmSummaryResponse,
    AlarmTrendsRequest,
    AlarmTrendsResponse,
    CorrelationRequest,
    CorrelationResponse,
    FloodAnalysisRequest,
    FloodAnalysisResponse,
    PriorityScoreRequest,
    PriorityScoreResponse,
    RationalizationRequest,
    RationalizationResponse,
    alarm_out,
)

router = APIRouter(prefix="/alarms", tags=["alarms"], dependencies=[Depends(require_bearer)])


@router.get("", response_model=AlarmListResponse)  # noqa: B008 (FastAPI Depends/Query in default is the documented pattern)
def list_alarms(
    request: Request,
    asset_id: str | None = Query(None),
    unit: str | None = Query(None),
    site: str | None = Query(None),
    status: str | None = Query(None, pattern="^(active|acknowledged)?$"),
    severity: Severity | None = Query(None),  # noqa: B008
    start_time: str | None = Query(None),
    end_time: str | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
    sort_by: str = Query("raised_at"),
    sort_order: str = Query("desc", pattern="^(asc|desc)$"),
) -> AlarmListResponse:
    from datetime import datetime

    store = request.app.state.store
    start = datetime.fromisoformat(start_time.replace("Z", "+00:00")) if start_time else None
    end = datetime.fromisoformat(end_time.replace("Z", "+00:00")) if end_time else None
    rows, total = store.list_alarms(
        asset_id=asset_id,
        unit=unit,
        site=site,
        status=status,
        severity=severity,
        start_time=start,
        end_time=end,
        page=page,
        page_size=page_size,
        sort_by=sort_by,
        sort_order=sort_order,
    )
    return AlarmListResponse(
        data=[alarm_out(a) for a in rows],
        page=page,
        page_size=page_size,
        total=total,
    )


@router.get("/{alarm_id}")
def get_alarm(request: Request, alarm_id: str) -> dict:
    store = request.app.state.store
    alarm = store.get_alarm(alarm_id)
    if alarm is None:
        raise NotFoundError(f"Alarm {alarm_id} not found", details={"alarm_id": alarm_id})
    return alarm_out(alarm)


@router.post("/summary", response_model=AlarmSummaryResponse)
def alarm_summary(request: Request, body: AlarmSummaryRequest) -> AlarmSummaryResponse:
    store = request.app.state.store
    summary = store.summarize(
        asset_ids=body.asset_ids,
        site=body.site,
        unit=body.unit,
        start_time=body.time_range.start_time,
        end_time=body.time_range.end_time,
        severity=body.severity,
        group_by=body.group_by,
    )
    kpis: dict[str, int] = {}
    for a in summary.items:
        kpis.setdefault(a.severity.value, 0)
        kpis[a.severity.value] += 1
    return AlarmSummaryResponse(
        groups=[{"alarm_count": len(summary.items)}],
        total=summary.total,
        kpis=kpis,
    )


@router.post("/trends", response_model=AlarmTrendsResponse)
def alarm_trends(request: Request, body: AlarmTrendsRequest) -> AlarmTrendsResponse:
    store = request.app.state.store
    buckets = store.trends(
        asset_ids=body.asset_ids,
        site=body.site,
        unit=body.unit,
        start_time=body.time_range.start_time,
        end_time=body.time_range.end_time,
        bucket=body.bucket,
    )
    return AlarmTrendsResponse(buckets=buckets)


@router.post("/correlation", response_model=CorrelationResponse)
def alarm_correlation(request: Request, body: CorrelationRequest) -> CorrelationResponse:
    store = request.app.state.store
    result = store.correlation(
        asset_ids=body.asset_ids,
        start_time=body.time_range.start_time,
        end_time=body.time_range.end_time,
        severity_threshold=body.severity_threshold,
    )
    return CorrelationResponse(pairs=result["pairs"], method=result["method"])


@router.post("/flood-analysis", response_model=FloodAnalysisResponse)
def flood_analysis(request: Request, body: FloodAnalysisRequest) -> FloodAnalysisResponse:
    store = request.app.state.store
    result = store.flood_analysis(
        unit=body.unit,
        start_time=body.time_range.start_time,
        end_time=body.time_range.end_time,
        threshold_count=body.threshold_count,
        rolling_window_minutes=body.rolling_window_minutes,
    )
    return FloodAnalysisResponse(flood_windows=result["flood_windows"], unit=result["unit"])


@router.post("/rationalization-candidates", response_model=RationalizationResponse)
def rationalization(request: Request, body: RationalizationRequest) -> RationalizationResponse:
    store = request.app.state.store
    candidates = store.rationalization_candidates(
        asset_ids=body.asset_ids,
        site=body.site,
        unit=body.unit,
        start_time=body.time_range.start_time,
        end_time=body.time_range.end_time,
        recurrence_threshold=body.recurrence_threshold,
        stale_minutes_threshold=body.stale_minutes_threshold,
    )
    return RationalizationResponse(candidates=candidates)


@router.post("/priority-score", response_model=PriorityScoreResponse)
def priority_score(request: Request, body: PriorityScoreRequest) -> PriorityScoreResponse:
    store = request.app.state.store
    try:
        score = store.priority_score(body.alarm_id)
    except KeyError as err:
        raise NotFoundError(
            f"Alarm {body.alarm_id} not found", details={"alarm_id": body.alarm_id}
        ) from err
    return PriorityScoreResponse(alarm_id=body.alarm_id, priority_score=score, factors={})
