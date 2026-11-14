"""Layer data models.

There are TWO views of a layer and it matters not to mix them up:

* :class:`LayerConfig` — the internal definition, exactly as written in
  ``catalog/layers.yaml``. It includes private details such as the
  remote source URL, which the frontend never sees.
* :class:`LayerOut` — what ``GET /api/layers`` returns. It is already
  "pre-chewed" for the viewer (Leaflet option names, tile URL pointing to
  OUR backend...). This is the contract with the frontend: as long as it
  doesn't change, the frontend doesn't need to change.
"""

from __future__ import annotations

import math
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

# Logical tile size of the viewer (Leaflet, CRS EPSG:4326: the world is
# 512x256 px at zoom 0, i.e. 2x1 tiles of 256 px).
VIEWER_TILE_SIZE = 256


class LevelRange(BaseModel):
    min: int = Field(0, ge=0)
    max: int = Field(..., ge=0)


class DisplayRange(BaseModel):
    min_zoom: int = Field(0, ge=0)
    max_zoom: int = Field(18, ge=0)


class LayerTransform(BaseModel):
    nodata_to_transparent: bool = False


class LayerSource(BaseModel):
    """Remote source data. Only used by the remote provider."""

    url_template: Optional[str] = None


class LayerConfig(BaseModel):
    """Internal definition of a layer (one entry of layers.yaml)."""

    id: str = Field(..., pattern=r"^[a-z0-9_\-]+$")
    name: str
    description: str = ""
    group: Literal["base", "overlay"] = "base"
    format: Literal["jpg", "png"] = "jpg"
    tile_size: Literal[256, 512] = 256
    levels: LevelRange
    display: DisplayRange = DisplayRange()
    opacity: float = Field(1.0, ge=0.0, le=1.0)
    z_index: int = 1
    attribution: str = ""
    transform: LayerTransform = LayerTransform()
    source: LayerSource = LayerSource()

    @property
    def zoom_offset(self) -> int:
        """Offset between map zoom and source level.

        A 512 px tile covers the same area as 2x2 tiles of 256 px, so level
        N of a 512 px source matches viewer zoom N+1.
        """
        return -int(math.log2(self.tile_size // VIEWER_TILE_SIZE))

    @property
    def media_type(self) -> str:
        return "image/png" if self.format == "png" else "image/jpeg"

    def is_valid_tile(self, z: int, x: int, y: int) -> bool:
        """Does tile (z, x, y) exist in the 2:1 equirectangular grid?"""
        if not (self.levels.min <= z <= self.levels.max):
            return False
        cols, rows = 2 * 2**z, 2**z
        return 0 <= x < cols and 0 <= y < rows


class LayerOut(BaseModel):
    """A layer as seen by the frontend (public contract, camelCase)."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    id: str
    name: str
    description: str
    group: str
    tile_url: str = Field(
        ..., description="Template relative to the backend, with {z}/{x}/{y}"
    )
    tile_size: int
    zoom_offset: int
    min_native_zoom: int
    max_native_zoom: int
    min_zoom: int
    max_zoom: int
    opacity: float
    z_index: int
    attribution: str

    @classmethod
    def from_config(cls, layer: LayerConfig, api_prefix: str = "/api") -> "LayerOut":
        off = layer.zoom_offset
        return cls(
            id=layer.id,
            name=layer.name,
            description=layer.description,
            group=layer.group,
            tile_url=f"{api_prefix}/tiles/{layer.id}/{{z}}/{{x}}/{{y}}",
            tile_size=layer.tile_size,
            zoom_offset=off,
            # Leaflet expresses native levels in MAP zoom units
            min_native_zoom=layer.levels.min - off,
            max_native_zoom=layer.levels.max - off,
            min_zoom=layer.display.min_zoom,
            max_zoom=layer.display.max_zoom,
            opacity=layer.opacity,
            z_index=layer.z_index,
            attribution=layer.attribution,
        )
