"""GET /analytics/kpi-definitions."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from ..auth import require_bearer
from ..models import KPIDefinitionsResponse

router = APIRouter(prefix="/analytics", tags=["analytics"], dependencies=[Depends(require_bearer)])


@router.get("/kpi-definitions", response_model=KPIDefinitionsResponse)
def kpi_definitions(request: Request) -> KPIDefinitionsResponse:
    store = request.app.state.store
    return KPIDefinitionsResponse(kpis=store.kpi_definitions())
