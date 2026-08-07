"""Asset endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request

from ..auth import require_bearer
from ..errors import NotFoundError
from ..models import (
    AssetMetadataResponse,
    AssetSearchResponse,
    asset_out,
)

router = APIRouter(prefix="/assets", tags=["assets"], dependencies=[Depends(require_bearer)])


@router.get("/search", response_model=AssetSearchResponse)
def search_assets(
    request: Request,
    query: str = Query(..., min_length=1, max_length=200),
    limit: int = Query(10, ge=1, le=200),
    unit: str | None = Query(None),
) -> AssetSearchResponse:
    store = request.app.state.store
    matches = store.search_assets(query=query, limit=limit, unit=unit)
    return AssetSearchResponse(
        results=[asset_out(a) for a in matches],
        total=len(matches),
        query=query,
    )


@router.get("/{asset_id}/metadata", response_model=AssetMetadataResponse)
def asset_metadata(request: Request, asset_id: str) -> AssetMetadataResponse:
    store = request.app.state.store
    asset = store.get_asset(asset_id)
    if asset is None:
        raise NotFoundError(f"Asset {asset_id} not found", details={"asset_id": asset_id})
    return AssetMetadataResponse(asset=asset_out(asset))
