"""Exact values at one location (map tap / POI info)."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Query, Request
from fastapi.concurrency import run_in_threadpool

from app.models.point import PointInfo

router = APIRouter(tags=["point"])


@router.get(
    "/point",
    response_model=PointInfo,
    response_model_by_alias=True,
    summary="Everything known about one location",
)
async def point_info(
    request: Request,
    lat: float = Query(..., ge=-90, le=90, description="Planetocentric latitude (degrees)"),
    lon: float = Query(..., ge=-360, le=360, description="East-positive longitude (degrees, wrapped to -180..180)"),
    ls: Optional[float] = Query(
        None, ge=0, lt=360, description="Solar longitude for the temperature estimate; default = today on Mars"
    ),
    tau: Optional[float] = Query(None, ge=0, le=5, description="Dust opacity for the temperature model (default 0.5)"),
) -> PointInfo:
    """Sections of values (location, terrain, thermal, surface, geology,
    safety). Each value has unit, source, resolution and method; modelled
    values are flagged ``estimate``; missing ones ``noData``.
    """
    service = request.app.state.point_service
    # Raster reads (and the thermal model) are blocking: keep them off the event loop.
    return await run_in_threadpool(service.query, lat, lon, ls, tau)
