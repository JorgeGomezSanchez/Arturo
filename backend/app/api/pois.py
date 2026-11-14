"""User POIs: CRUD as GeoJSON, backed by a swappable PoiRepository."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Request, Response, status

from app.api.features import parse_bbox
from app.catalog.map_config import get_poi_categories
from app.models.poi import PoiCategory, PoiFeature, PoiFeatureCollection, PoiInput
from app.repositories.features import lon_ranges
from app.repositories.pois import PoiNotFoundError, PoiRepository

router = APIRouter(tags=["pois"])


def _repo(request: Request) -> PoiRepository:
    return request.app.state.poi_repository


def _not_found(poi_id: str) -> HTTPException:
    return HTTPException(status.HTTP_404_NOT_FOUND, f"POI '{poi_id}' does not exist")


@router.get("/pois/categories", response_model=list[PoiCategory], response_model_by_alias=True,
            summary="Selectable POI types (icon ids, labels, colours)")
def poi_categories() -> list[PoiCategory]:
    return get_poi_categories()


@router.get("/pois", response_model=PoiFeatureCollection, response_model_by_alias=True,
            summary="List user POIs (GeoJSON)")
def list_pois(
    request: Request,
    bbox: Optional[str] = Query(None, description="Optional west,south,east,north filter"),
) -> PoiFeatureCollection:
    """All POIs, oldest first. Visibility by zoom is applied by the client
    using ``createdZoom`` and ``/api/map -> poiVisibility``."""
    pois = _repo(request).list()
    box = parse_bbox(bbox)
    if box:
        west, south, east, north = box
        ranges = lon_ranges(west, east)
        pois = [p for p in pois if south <= p.lat <= north and any(lo <= p.lon <= hi for lo, hi in ranges)]
    return PoiFeatureCollection(features=[PoiFeature.from_poi(p) for p in pois])


@router.get("/pois/{poi_id}", response_model=PoiFeature, response_model_by_alias=True,
            summary="One POI")
def get_poi(request: Request, poi_id: str) -> PoiFeature:
    try:
        return PoiFeature.from_poi(_repo(request).get(poi_id))
    except PoiNotFoundError:
        raise _not_found(poi_id)


@router.post("/pois", response_model=PoiFeature, response_model_by_alias=True,
             status_code=status.HTTP_201_CREATED, summary="Create a POI")
def create_poi(request: Request, body: PoiInput) -> PoiFeature:
    return PoiFeature.from_poi(_repo(request).create(body))


@router.put("/pois/{poi_id}", response_model=PoiFeature, response_model_by_alias=True,
            summary="Replace a POI's fields (name, category, notes, position, createdZoom)")
def update_poi(request: Request, poi_id: str, body: PoiInput) -> PoiFeature:
    try:
        return PoiFeature.from_poi(_repo(request).update(poi_id, body))
    except PoiNotFoundError:
        raise _not_found(poi_id)


@router.delete("/pois/{poi_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete a POI")
def delete_poi(request: Request, poi_id: str) -> Response:
    try:
        _repo(request).delete(poi_id)
    except PoiNotFoundError:
        raise _not_found(poi_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
