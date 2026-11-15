"""Routes drawn by hand (A -> waypoints -> B) and their analysis.

Wire format: GeoJSON. A route is a ``Feature`` with a ``LineString``
geometry ``[A, waypoint1, ..., B]`` ([lon, lat] pairs) and properties:

    name, notes     label and free text
    mode            travel mode id from routes.yaml (walking | rover)
    start, end      what A and B are: {kind: poi | feature | point,
                    refId, name, lat, lon}; the coordinates are a
                    snapshot taken when the route was saved
    createdZoom     map zoom when the route was created
    stats           summary of the last analysis (distance, duration,
                    dose, gain/loss, worst severity, hazard counts)
    createdAt / updatedAt
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from pydantic.alias_generators import to_camel

Severity = Literal["info", "warning", "danger"]
SegmentLevel = Literal["ok", "info", "warning", "danger"]
SEVERITY_ORDER = {"ok": 0, "info": 1, "warning": 2, "danger": 3}


class _Camel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


def _wrap(lon: float) -> float:
    return lon if -180.0 <= lon <= 180.0 else round(((lon + 180.0) % 360.0) - 180.0, 7)


# --------------------------------------------------------------- config
class SlopeThresholds(_Camel):
    difficult_deg: float
    impassable_deg: float


class TravelMode(_Camel):
    id: str = ""
    label: str
    speed_kmh: float = Field(..., gt=0)
    speed_model: Literal["tobler", "linear"] = "linear"
    slope: SlopeThresholds
    max_duration_h: float = Field(..., gt=0)
    walk_back_km: Optional[float] = None


class SamplingConfig(_Camel):
    min_spacing_m: float = 50
    max_samples: int = 2500
    remote_max_rows: int = 80
    remote_max_decimation: int = 2
    thermal_points: int = 16


class PlanningConfig(_Camel):
    """routes.yaml -> planning: automatic route planning (POST /api/routes/plan)."""

    margin_fraction: float = Field(0.3, ge=0, le=3)
    min_margin_km: float = Field(2.0, ge=0)
    max_cells: int = Field(1_000_000, ge=100, le=16_000_000)
    max_distance_km: float = Field(600, gt=0)
    max_abs_lat: float = Field(80, gt=0, le=90)
    difficult_multiplier: float = Field(3.0, ge=1)
    roughness_warning_multiplier: float = Field(1.5, ge=1)
    roughness_danger_multiplier: float = Field(4.0, ge=1)
    impassable_buffer_px: int = Field(1, ge=0, le=10)
    no_data: Literal["impassable", "penalty"] = "impassable"
    no_data_multiplier: float = Field(5.0, ge=1)
    simplify_cost_tolerance: float = Field(0.05, ge=0, le=1)
    max_waypoints: int = Field(25, ge=0, le=200)


class RoutesConfig(_Camel):
    """routes.yaml, also served as GET /api/routes/config."""

    sampling: SamplingConfig
    planning: PlanningConfig = PlanningConfig()
    modes: dict[str, TravelMode]
    hazards: dict[str, dict[str, float | str]]


# --------------------------------------------------------------- storage
class RouteEnd(_Camel):
    """Start or end of a route."""

    kind: Literal["poi", "feature", "point"] = "point"
    ref_id: Optional[str] = Field(None, description="POI id or feature id when kind is poi/feature")
    name: str = Field("", max_length=120)
    lat: float = Field(..., ge=-90, le=90)
    lon: float = Field(..., ge=-540, le=540)

    @field_validator("lon")
    @classmethod
    def _wrap_lon(cls, v: float) -> float:
        return _wrap(v)


class RouteInput(_Camel):
    """Body of POST /api/routes and PUT /api/routes/{id} (full replace)."""

    name: str = Field(..., min_length=1, max_length=60)
    notes: str = Field("", max_length=2000)
    mode: str = "walking"
    start: RouteEnd
    end: RouteEnd
    waypoints: list[tuple[float, float]] = Field(default_factory=list, max_length=200,
                                                 description="Intermediate [lon, lat] points")
    created_zoom: int = Field(0, ge=0, le=24)

    @field_validator("name")
    @classmethod
    def _strip(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("name must not be blank")
        return v

    @field_validator("waypoints")
    @classmethod
    def _check(cls, pts):
        out = []
        for lon, lat in pts:
            if not -90 <= lat <= 90:
                raise ValueError("waypoint latitude out of range")
            out.append((_wrap(lon), lat))
        return out

    def coordinates(self) -> list[tuple[float, float]]:
        return [(self.start.lon, self.start.lat), *self.waypoints, (self.end.lon, self.end.lat)]


class RouteStats(_Camel):
    """Summary of an analysis, stored with the route."""

    distance_m: float
    duration_h: float
    dose_msv: float
    gain_m: float
    loss_m: float
    max_slope_deg: Optional[float]
    max_severity: SegmentLevel
    hazard_counts: dict[str, int]
    mode: str
    resolution: str
    analyzed_at: datetime


class Route(RouteInput):
    id: str
    created_at: datetime
    updated_at: datetime
    stats: Optional[RouteStats] = None


class LineGeometry(BaseModel):
    type: Literal["LineString"] = "LineString"
    coordinates: list[tuple[float, float]]


class RouteProperties(_Camel):
    name: str
    notes: str
    mode: str
    start: RouteEnd
    end: RouteEnd
    created_zoom: int
    stats: Optional[RouteStats]
    created_at: datetime
    updated_at: datetime


class RouteFeature(BaseModel):
    type: Literal["Feature"] = "Feature"
    id: str
    geometry: LineGeometry
    properties: RouteProperties

    @classmethod
    def from_route(cls, r: Route) -> "RouteFeature":
        return cls(
            id=r.id,
            geometry=LineGeometry(coordinates=r.coordinates()),
            properties=RouteProperties(
                name=r.name, notes=r.notes, mode=r.mode, start=r.start, end=r.end,
                created_zoom=r.created_zoom, stats=r.stats, created_at=r.created_at, updated_at=r.updated_at,
            ),
        )


class RouteFeatureCollection(BaseModel):
    type: Literal["FeatureCollection"] = "FeatureCollection"
    features: list[RouteFeature]


# --------------------------------------------------------------- analysis
class AnalyzeRequest(_Camel):
    """Body of POST /api/routes/analyze."""

    coordinates: list[tuple[float, float]] = Field(..., min_length=2, max_length=202,
                                                   description="[lon, lat] vertices: A, waypoints, B")
    mode: str = "walking"
    ls: Optional[float] = Field(None, ge=0, lt=360, description="Season for the temperature model (default: today)")

    @model_validator(mode="after")
    def _check(self):
        for lon, lat in self.coordinates:
            if not -90 <= lat <= 90 or not -540 <= lon <= 540:
                raise ValueError("coordinate out of range")
        self.coordinates = [(_wrap(lon), lat) for lon, lat in self.coordinates]
        return self


class Hazard(_Camel):
    id: str
    type: str
    severity: Severity
    title: str
    description: str
    value: Optional[float] = None
    unit: str = ""
    threshold: Optional[float] = None
    scope: Literal["segment", "route"] = "segment"
    from_m: float
    to_m: float
    lat: float  # where it is worst
    lon: float
    coordinates: list[tuple[float, float]] = Field(default_factory=list, description="[lon, lat] of the stretch")


class RouteSegment(_Camel):
    """A stretch with one colour: the worst severity of the hazards on it."""

    from_m: float
    to_m: float
    level: SegmentLevel
    no_data: bool = False
    coordinates: list[tuple[float, float]]


class ProfilePoint(_Camel):
    d: float  # metres from A
    lat: float
    lon: float
    elevation: Optional[float]
    slope: Optional[float]  # terrain slope, degrees
    grade: Optional[float]  # along-track grade, degrees (+ = climbing)
    level: SegmentLevel


class DataUse(_Camel):
    name: str
    resolution_m: float
    share: float  # fraction of the route length


class RouteAnalysis(_Camel):
    mode: str
    mode_label: str
    ls: float
    distance_m: float
    duration_h: float
    dose_msv: float
    gain_m: float
    loss_m: float
    min_elevation_m: Optional[float]
    max_elevation_m: Optional[float]
    max_slope_deg: Optional[float]
    max_grade_deg: Optional[float]
    night_min_c: Optional[float]
    sample_spacing_m: float
    resolution: str
    data: list[DataUse]
    max_severity: SegmentLevel
    hazard_counts: dict[str, int]
    hazards: list[Hazard]
    segments: list[RouteSegment]
    profile: list[ProfilePoint]
    vertices: list[tuple[float, float]]
    vertex_distances_m: list[float]
    method: str


# --------------------------------------------------------------- planning
class PlanWeights(_Camel):
    """Optional per-request overrides of routes.yaml -> planning."""

    margin_fraction: Optional[float] = Field(None, ge=0, le=3)
    difficult_multiplier: Optional[float] = Field(None, ge=1)
    roughness_warning_multiplier: Optional[float] = Field(None, ge=1)
    roughness_danger_multiplier: Optional[float] = Field(None, ge=1)
    impassable_buffer_px: Optional[int] = Field(None, ge=0, le=10)
    no_data: Optional[Literal["impassable", "penalty"]] = None
    simplify_cost_tolerance: Optional[float] = Field(None, ge=0, le=1)
    max_waypoints: Optional[int] = Field(None, ge=0, le=200)


class PlanRequest(_Camel):
    """Body of POST /api/routes/plan."""

    start: tuple[float, float] = Field(..., description="[lon, lat] of A")
    end: tuple[float, float] = Field(..., description="[lon, lat] of B")
    mode: str = "walking"
    ls: Optional[float] = Field(None, ge=0, lt=360)
    weights: Optional[PlanWeights] = None

    @model_validator(mode="after")
    def _check(self):
        for lon, lat in (self.start, self.end):
            if not -90 <= lat <= 90 or not -540 <= lon <= 540:
                raise ValueError("coordinate out of range")
        self.start = (_wrap(self.start[0]), self.start[1])
        self.end = (_wrap(self.end[0]), self.end[1])
        return self


class RouteSummary(_Camel):
    """A few numbers of an analysis, e.g. the straight line for comparison."""

    distance_m: float
    duration_h: float
    max_slope_deg: Optional[float]
    max_severity: SegmentLevel
    hazard_counts: dict[str, int]


class PlanInfo(_Camel):
    """How the plan was computed (shown in the UI and the API docs)."""

    planner: str
    data: str  # DEM(s) used for the grid
    resolution_m: float  # grid pixel size (after any coarsening)
    native_resolution_m: float
    coarsened: int  # 1 = native resolution, k = k x k pixels merged
    rows: int
    cols: int
    excluded_share: float  # fraction of the grid that was impassable / no data
    path_cells: int
    estimated_hours: float  # from the cost surface (the analysis is authoritative)
    elapsed_ms: int
    timings_ms: dict[str, int]  # grid, search, simplify, analysis
    notes: list[str]


class PlanResponse(_Camel):
    """Waypoints of the planned route (A and B excluded) + its analysis."""

    waypoints: list[tuple[float, float]]
    analysis: RouteAnalysis
    straight: RouteSummary
    info: PlanInfo
