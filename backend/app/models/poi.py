"""User points of interest (POIs) placed by hand on the map.

Wire format: GeoJSON. A POI is a ``Feature`` with a ``Point`` geometry and
these properties (camelCase):

    name         visible label / tag (1-60 chars)
    category     resource | shelter | hazard | vehicle | unknown
    notes        free text (<= 2000 chars)
    createdZoom  map zoom at which it was placed. Drives label visibility:
                 world-view POIs (placed zoomed out) show from far away,
                 local POIs only near the zoom they were placed at
                 (rules in map.yaml -> poi_visibility).
    createdAt / updatedAt  ISO-8601 UTC timestamps (set by the backend)
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator
from pydantic.alias_generators import to_camel

PoiCategoryId = Literal["resource", "shelter", "hazard", "vehicle", "unknown"]


class _Camel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class PoiInput(_Camel):
    """Body of POST /api/pois and PUT /api/pois/{id} (full replace)."""

    name: str = Field(..., min_length=1, max_length=60)
    category: PoiCategoryId = "unknown"
    notes: str = Field("", max_length=2000)
    lat: float = Field(..., ge=-90, le=90)
    lon: float = Field(..., ge=-540, le=540, description="Normalised to -180..180")
    created_zoom: int = Field(..., ge=0, le=24)

    @field_validator("name")
    @classmethod
    def _strip_name(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("name must not be blank")
        return v

    @field_validator("lon")
    @classmethod
    def _wrap_lon(cls, v: float) -> float:
        # Leaflet may report unwrapped longitudes (e.g. 200 = -160).
        if -180.0 <= v <= 180.0:
            return v
        return round(((v + 180.0) % 360.0) - 180.0, 7)


class Poi(PoiInput):
    """Stored POI (internal + repository representation)."""

    id: str
    created_at: datetime
    updated_at: datetime


class PoiProperties(_Camel):
    name: str
    category: PoiCategoryId
    notes: str
    created_zoom: int
    created_at: datetime
    updated_at: datetime


class PoiGeometry(BaseModel):
    type: Literal["Point"] = "Point"
    coordinates: tuple[float, float]  # [lon, lat]


class PoiFeature(BaseModel):
    type: Literal["Feature"] = "Feature"
    id: str
    geometry: PoiGeometry
    properties: PoiProperties

    @classmethod
    def from_poi(cls, poi: Poi) -> "PoiFeature":
        return cls(
            id=poi.id,
            geometry=PoiGeometry(coordinates=(poi.lon, poi.lat)),
            properties=PoiProperties(
                name=poi.name,
                category=poi.category,
                notes=poi.notes,
                created_zoom=poi.created_zoom,
                created_at=poi.created_at,
                updated_at=poi.updated_at,
            ),
        )


class PoiFeatureCollection(BaseModel):
    type: Literal["FeatureCollection"] = "FeatureCollection"
    features: list[PoiFeature]


class PoiCategory(_Camel):
    """A selectable POI type (map.yaml -> poi_categories)."""

    id: PoiCategoryId
    label: str
    description: str = ""
    color: str = Field("#999999", pattern=r"^#[0-9a-fA-F]{6}$")


class PoiVisibility(_Camel):
    """Zoom-based visibility of user POIs (map.yaml -> poi_visibility).

    With z = current zoom and c = createdZoom:
      z >= c - label_zoom_margin                  -> icon + label
      c - marker_zoom_margin <= z < (above)       -> small dot only
      z <  c - marker_zoom_margin                 -> hidden
    POIs placed at or below ``world_zoom`` are "world-view" POIs and are
    always shown with their label.
    """

    label_zoom_margin: int = Field(2, ge=0)
    marker_zoom_margin: int = Field(5, ge=0)
    world_zoom: int = Field(3, ge=0)
    note: Optional[str] = None
