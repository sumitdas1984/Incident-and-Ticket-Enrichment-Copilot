"""POST /recommendations/operator-actions — operator recommendations for an alarm."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from core.domain import OperatorRecommendation

from ..auth import require_bearer
from ..errors import NotFoundError
from ..models import RecommendationRequest

router = APIRouter(prefix="/recommendations", tags=["recommendations"], dependencies=[Depends(require_bearer)])


@router.post("/operator-actions", response_model=OperatorRecommendation)
def operator_actions(request: Request, body: RecommendationRequest) -> OperatorRecommendation:
    store = request.app.state.store
    try:
        rec = store.recommendation(body.alarm_id)
    except KeyError as err:
        raise NotFoundError(
            f"Alarm {body.alarm_id} not found", details={"alarm_id": body.alarm_id}
        ) from err
    return rec
