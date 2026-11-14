"""Named features (map labels): IAU names, landing sites, exploration zones."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Request

from app.models.feature import FeatureCategory, NamedFeature, NamedFeatureCollection
from app.repositories.features import BBox, FeatureRepository

router = APIRouter(tags=["features"])


def _repo(request: Request) -> FeatureRepository:
    return request.app.state.feature_repository


def parse_bbox(raw: Optional[str]) -> Optional[BBox]:
    if not raw:
        return None
    try:
        west, south, east, north = (float(v) for v in raw.split(","))
    except ValueError:
        raise HTTPException(422, "bbox must be 'west,south,east,north' in degrees")
    if south > north:
        raise HTTPException(422, "bbox: south must be <= north")
    return west, south, east, north


@router.get(
    "/features",
    response_model=NamedFeatureCollection,
    response_model_by_alias=True,
    summary="Named features (labels) in a view",
)
def list_features(
    request: Request,
    bbox: Optional[str] = Query(
        None,
        description="west,south,east,north in degrees. Longitudes may be unwrapped "
        "(e.g. 170,-10,200,10) or west > east to cross the antimeridian.",
        examples=["130,-10,145,0"],
    ),
    zoom: Optional[float] = Query(
        None, ge=0, le=24, description="Current map zoom: only features with minZoom <= zoom"
    ),
    categories: Optional[str] = Query(
        None, description="Comma separated categories (see /api/features/categories)"
    ),
    limit: int = Query(500, ge=1, le=5000, description="Max features, highest priority first"),
) -> NamedFeatureCollection:
    """GeoJSON FeatureCollection of named points, highest priority first.

    The backend does the coarse filtering (view + zoom + limit); the
    frontend does the fine, on-screen collision decluttering.
    """
    cats = {c.strip() for c in categories.split(",") if c.strip()} if categories else None
    features, total = _repo(request).query(parse_bbox(bbox), zoom, cats, limit)
    return NamedFeatureCollection(features=features, total=total)


@router.get(
    "/features/categories",
    response_model=list[FeatureCategory],
    response_model_by_alias=True,
    summary="Feature categories and counts",
)
def feature_categories(request: Request) -> list[FeatureCategory]:
    return _repo(request).categories()


@router.get(
    "/features/{feature_id}",
    response_model=NamedFeature,
    response_model_by_alias=True,
    summary="One named feature",
)
def get_feature(request: Request, feature_id: str) -> NamedFeature:
    feature = _repo(request).get(feature_id)
    if feature is None:
        raise HTTPException(404, f"Feature '{feature_id}' does not exist")
    return feature
