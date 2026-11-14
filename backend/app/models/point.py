"""Models for ``GET /api/point`` (values at one location).

The response is deliberately generic: sections of items, each item a
value with its unit, source, resolution and method. The frontend renders
whatever comes back, so adding a value never needs frontend code.
"""

from __future__ import annotations

from typing import Optional, Union

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel


class _Camel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class RasterSourceConfig(BaseModel):
    id: str
    kind: str = "local"  # local | remote
    path: Optional[str] = None
    url: Optional[str] = None
    name: str
    resolution_m: float
    scale: float = 1.0
    offset: float = 0.0
    bands: list[int] = [1]
    band_names: list[str] = []


class RasterDatasetConfig(BaseModel):
    title: str
    units: str = ""
    citation: str = ""
    optional: bool = False
    legend: Optional[str] = None
    sources: list[RasterSourceConfig]


class SeriesPoint(_Camel):
    """One sample of a curve (e.g. temperature over a sol)."""

    x: float
    y: float


class PointItem(_Camel):
    id: str
    label: str
    # Number (rounded to `precision`) or text; None when no data.
    value: Union[float, str, None] = None
    unit: str = ""
    precision: int = 0
    no_data: bool = False
    estimate: bool = False  # True = modelled, not measured
    source: str = ""
    resolution: str = ""
    method: str = ""
    notes: str = ""
    # Optional small curve (x/y labels in series_x / unit)
    series: Optional[list[SeriesPoint]] = None
    series_x: str = ""


class PointSection(_Camel):
    id: str
    title: str
    items: list[PointItem]


class PointQueryInfo(_Camel):
    lat: float
    lon: float
    ls: float = Field(description="Solar longitude used for the seasonal estimates (degrees)")
    ls_source: str = Field(description="'current' (today on Mars) or 'query'")
    mars_year: Optional[int] = None
    local_solar_time: Optional[str] = Field(None, description="Local mean solar time now at this longitude (hh:mm)")
    data_source: str


class PointInfo(_Camel):
    query: PointQueryInfo
    sections: list[PointSection]
