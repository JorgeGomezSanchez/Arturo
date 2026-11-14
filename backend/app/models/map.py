"""Models for the map configuration and the detail zones."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

from app.models.poi import PoiVisibility


class _Camel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class LatLon(_Camel):
    lat: float = Field(..., ge=-90, le=90)
    lon: float = Field(..., ge=-180, le=180)


class Bounds(_Camel):
    south: float = Field(..., ge=-90, le=90)
    west: float = Field(..., ge=-180, le=180)
    north: float = Field(..., ge=-90, le=90)
    east: float = Field(..., ge=-180, le=180)


class MapConfig(_Camel):
    body: str = "Mars"
    radius_m: float
    crs: Literal["EPSG4326"] = "EPSG4326"
    center: LatLon
    zoom: int
    min_zoom: int
    max_zoom: int
    bounds: Bounds
    # Zoom-based visibility rules for user POIs (see map.yaml).
    poi_visibility: PoiVisibility = PoiVisibility()
    # Credit line per map-label group (names / landing_site /
    # exploration_zone), shown in the frontend's Credits panel while that
    # group of labels is on.
    label_credits: dict[str, str] = {}


class Zone(_Camel):
    id: str
    name: str
    description: str = ""
    status: Literal["planned", "available"] = "planned"
    center: LatLon
    bounds: Bounds
    tags: list[str] = []
