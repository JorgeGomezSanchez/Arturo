"""Named-feature repository (the "black box" for label data).

``FeatureRepository`` is the interface the API uses. The current
implementation, ``GeoJsonDirFeatureRepository``, loads every
``*.geojson`` file of ``FEATURES_DIR`` into memory at startup (a few
thousand points: microseconds to filter). A future implementation could
use SQLite/SpatiaLite or a habitat database without touching the API or
the frontend.

Because the data is shipped with the repo, the same repository serves
both Earth (remote) and Mars (local) modes.
"""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from collections import Counter
from pathlib import Path
from typing import Iterable, Optional

from app.models.feature import FeatureCategory, FeatureProperties, NamedFeature, PointGeometry
from app.services.features import min_zoom_for, priority_for

# west, south, east, north (GeoJSON bbox order), degrees
BBox = tuple[float, float, float, float]


class FeatureRepository(ABC):
    @abstractmethod
    def query(
        self,
        bbox: Optional[BBox] = None,
        zoom: Optional[float] = None,
        categories: Optional[set[str]] = None,
        limit: Optional[int] = None,
    ) -> tuple[list[NamedFeature], int]:
        """Features inside ``bbox`` whose ``minZoom <= zoom``, sorted by
        priority (highest first). Returns (features, total_before_limit)."""

    @abstractmethod
    def get(self, feature_id: str) -> Optional[NamedFeature]: ...

    @abstractmethod
    def categories(self) -> list[FeatureCategory]: ...


def lon_ranges(west: float, east: float) -> list[tuple[float, float]]:
    """Longitude intervals (in -180..180) covered by [west, east].

    Leaflet reports unwrapped longitudes when the view crosses the
    antimeridian (e.g. west=170, east=200), and GeoJSON allows west > east
    for the same case. Both are normalised into one or two intervals.
    """
    if east < west:  # GeoJSON antimeridian convention
        east += 360.0
    if east - west >= 360.0:
        return [(-180.0, 180.0)]
    w = ((west + 180.0) % 360.0) - 180.0
    e = w + (east - west)
    if e <= 180.0:
        return [(w, e)]
    return [(w, 180.0), (-180.0, e - 360.0)]


def in_bbox(f: NamedFeature, bbox: BBox) -> bool:
    west, south, east, north = bbox
    if not (south <= f.lat <= north):
        return False
    return any(lo <= f.lon <= hi for lo, hi in lon_ranges(west, east))


class GeoJsonDirFeatureRepository(FeatureRepository):
    def __init__(self, features: Iterable[NamedFeature], labels: dict[str, str] | None = None):
        self._features = sorted(features, key=lambda f: -f.properties.priority)
        self._by_id = {f.id: f for f in self._features}
        self._labels = labels or {}

    @classmethod
    def from_dir(cls, folder: Path, radius_m: float) -> "GeoJsonDirFeatureRepository":
        features: list[NamedFeature] = []
        labels: dict[str, str] = {}
        for path in sorted(Path(folder).glob("*.geojson")):
            with open(path, encoding="utf-8") as fh:
                data = json.load(fh)
            for raw in data.get("features", []):
                props = raw["properties"]
                cat = props["category"]
                diameter = props.get("diameterKm")
                labels.setdefault(cat, props.get("typeLabel", cat))
                features.append(
                    NamedFeature(
                        id=str(raw["id"]),
                        geometry=PointGeometry(coordinates=tuple(raw["geometry"]["coordinates"][:2])),
                        properties=FeatureProperties(
                            **props,
                            min_zoom=min_zoom_for(cat, diameter, radius_m),
                            priority=priority_for(cat, diameter),
                        ),
                    )
                )
        # Category labels: landing-site typeLabels carry agency/year, so use a
        # generic label for the category list.
        labels.update({"landing_site": "Landing site (robotic)",
                       "exploration_zone": "Candidate human exploration zone"})
        return cls(features, labels)

    def query(self, bbox=None, zoom=None, categories=None, limit=None):
        out = [
            f
            for f in self._features
            if (zoom is None or f.properties.min_zoom <= zoom)
            and (categories is None or f.properties.category in categories)
            and (bbox is None or in_bbox(f, bbox))
        ]
        total = len(out)
        return (out[:limit] if limit else out), total

    def get(self, feature_id):
        return self._by_id.get(feature_id)

    def categories(self):
        counts = Counter(f.properties.category for f in self._features)
        return [
            FeatureCategory(id=c, label=self._labels.get(c, c), count=n)
            for c, n in counts.most_common()
        ]
