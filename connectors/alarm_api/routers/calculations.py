"""POST /calculation-code/{generate,execute}."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from ..auth import require_bearer
from ..errors import NotFoundError
from ..models import (
    CalculationExecuteRequest,
    CalculationExecuteResponse,
    CalculationGenerateRequest,
    CalculationGenerateResponse,
)

router = APIRouter(prefix="/calculation-code", tags=["calculations"], dependencies=[Depends(require_bearer)])


@router.post("/generate", response_model=CalculationGenerateResponse)
def generate(request: Request, body: CalculationGenerateRequest) -> CalculationGenerateResponse:
    store = request.app.state.store
    cid = store.create_calculation(body.calculation_type, body.filters)
    return CalculationGenerateResponse(
        calculation_id=cid,
        calculation_type=body.calculation_type,
        code=f"# pseudo code for {body.calculation_type}\n# params: {body.filters}",
    )


@router.post("/execute", response_model=CalculationExecuteResponse)
def execute(request: Request, body: CalculationExecuteRequest) -> CalculationExecuteResponse:
    store = request.app.state.store
    try:
        result = store.execute_calculation(body.calculation_id, body.filters)
    except KeyError as err:
        raise NotFoundError(
            f"Calculation {body.calculation_id} not found",
            details={"calculation_id": body.calculation_id},
        ) from err
    return CalculationExecuteResponse(**result)
