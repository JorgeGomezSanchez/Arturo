"""Map configuration and detail-zone endpoints."""

from __future__ import annotations

from fastapi import APIRouter

from app.catalog.map_config import get_map_config, get_zones
from app.models.map import MapConfig, Zone

router = APIRouter(tags=["map"])


@router.get("/map", response_model=MapConfig, response_model_by_alias=True,
            summary="Map configuration (CRS, initial view, zoom limits)")
def map_config() -> MapConfig:
    return get_map_config()


@router.get("/zones", response_model=list[Zone], response_model_by_alias=True,
            summary="Detail zones for the side menu")
def zones() -> list[Zone]:
    return get_zones()
