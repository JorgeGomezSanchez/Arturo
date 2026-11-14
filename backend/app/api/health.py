"""Health endpoint: used to check that the backend is alive."""

from __future__ import annotations

from fastapi import APIRouter, Request

from app.core.config import get_settings

router = APIRouter(tags=["system"])


@router.get("/health", summary="Backend status")
def health(request: Request) -> dict:
    settings = get_settings()
    return {
        "status": "ok",
        "app": settings.app_name,
        "version": settings.app_version,
        # "remote" (Earth) or "local" (Mars)
        "dataSource": settings.data_source,
        "tileProvider": request.app.state.tile_provider.describe(),
        "poiStore": request.app.state.poi_repository.describe(),
        "pointRaster": request.app.state.point_raster,
    }
