"""Raster source interface (the point-query twin of ``TileProvider``).

``GET /api/point`` needs a few real numbers around one location
(elevation, thermal inertia, albedo...). Where those numbers come from is
hidden behind :class:`RasterSource`:

* ``GeoTiffRasterSource`` — one GeoTIFF read with rasterio windowed
  reads. The SAME class reads a local file (Mars mode) or a remote file
  over HTTP range requests (``/vsicurl/``, Earth mode).
* ``MultiFileRasterSource`` — several local GeoTIFFs (e.g. 200 m crops
  of detail zones); uses the first one that covers the point.
* ``LayeredRasterSource`` — tries sources in priority order (best
  resolution first) and returns the first window with data. Remote
  sources that fail are skipped for a while (circuit breaker).

A future source (a habitat database, a Martian network service...)
implements :meth:`RasterSource.read` and is listed in
``app/catalog/rasters.yaml``; nothing else changes.
"""

from __future__ import annotations

import math
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

import numpy as np

MARS_RADIUS_M = 3_396_190.0


@dataclass(frozen=True)
class SourceInfo:
    """What a value came from (shown next to every number in the UI)."""

    id: str
    name: str
    resolution_m: float
    kind: str  # "local" | "remote"


@dataclass
class RasterWindow:
    """A (2r+1) x (2r+1) block of values centred on the query point.

    ``data`` is float64 with NaN for no data, scale/offset already applied.
    Row 0 is the northern row. ``dlat``/``dlon`` = pixel size in degrees.
    """

    data: np.ndarray
    dlat: float
    dlon: float
    source: SourceInfo
    band_names: list[str] = field(default_factory=list)

    @property
    def center(self) -> np.ndarray:
        """Centre pixel value(s): scalar array for 1 band, vector for N."""
        r = self.data.shape[-1] // 2
        return self.data[..., r, r]

    def pixel_size_m(self, lat: float) -> tuple[float, float]:
        """(dx, dy) in metres at latitude ``lat`` (east-west shrinks with cos)."""
        dy = MARS_RADIUS_M * math.radians(self.dlat)
        dx = MARS_RADIUS_M * math.radians(self.dlon) * max(math.cos(math.radians(lat)), 1e-6)
        return dx, dy


class RasterUnavailableError(Exception):
    """The source could not be read (file missing, network down, timeout)."""


class RasterSource(ABC):
    info: SourceInfo

    @abstractmethod
    def read(self, lat: float, lon: float, radius: int = 0) -> RasterWindow | None:
        """Window of ``2*radius+1`` pixels around (lat, lon).

        Returns ``None`` when the point is outside this source's coverage,
        raises :class:`RasterUnavailableError` when the source fails.
        """

    def close(self) -> None:  # pragma: no cover - default no-op
        pass
