"""Named features (map labels) as GeoJSON.

The public contract of ``GET /api/features`` is a standard GeoJSON
FeatureCollection of Points, so Leaflet (or any GIS tool) can read it
directly. Properties are camelCase like the rest of the API.
"""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel


class _Camel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class PointGeometry(BaseModel):
    type: Literal["Point"] = "Point"
    # [lon, lat]: east-positive longitude -180..180, planetocentric latitude
    coordinates: tuple[float, float]


class FeatureProperties(_Camel):
    name: str
    category: str = Field(..., description="crater, vallis, mons, landing_site, exploration_zone...")
    type_label: str = ""
    diameter_km: Optional[float] = None
    origin: Optional[str] = None
    source: str = ""
    link: Optional[str] = None
    # --- display rules, computed by the backend (services/features.py) ---
    min_zoom: int = Field(0, description="Lowest map zoom at which the label may be shown")
    priority: float = Field(0.0, description="Higher wins when labels collide on screen")


class NamedFeature(BaseModel):
    type: Literal["Feature"] = "Feature"
    id: str
    geometry: PointGeometry
    properties: FeatureProperties

    @property
    def lon(self) -> float:
        return self.geometry.coordinates[0]

    @property
    def lat(self) -> float:
        return self.geometry.coordinates[1]


class NamedFeatureCollection(BaseModel):
    type: Literal["FeatureCollection"] = "FeatureCollection"
    features: list[NamedFeature]
    # How many features matched before applying ``limit``.
    total: int = 0


class FeatureCategory(_Camel):
    id: str
    label: str
    count: int
