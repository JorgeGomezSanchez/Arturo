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


@dataclass
class RasterGrid:
    """A block of a raster covering a bounding box (for route sampling).

    ``data`` is 2-D float64 (NaN = no data, scale/offset applied), row 0
    at the north edge ``north``, column 0 at the west edge ``west``.
    ``dlat``/``dlon`` are the EFFECTIVE pixel size in degrees (larger
    than the file's when the block was read decimated), and
    ``source.resolution_m`` is the matching effective ground resolution.
    """

    data: np.ndarray
    north: float
    west: float
    dlat: float
    dlon: float
    source: SourceInfo

    def _rc(self, lat: np.ndarray, lon: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        r = (self.north - np.asarray(lat)) / self.dlat - 0.5
        c = (np.asarray(lon) - self.west) / self.dlon - 0.5
        return r, c

    def sample_nearest(self, lat, lon, data: np.ndarray | None = None) -> np.ndarray:
        """Value of the pixel containing each point (NaN outside)."""
        grid = self.data if data is None else data
        r, c = self._rc(lat, lon)
        ri, ci = np.rint(r).astype(int), np.rint(c).astype(int)
        ok = (ri >= 0) & (ri < grid.shape[0]) & (ci >= 0) & (ci < grid.shape[1])
        out = np.full(ri.shape, np.nan)
        out[ok] = grid[ri[ok], ci[ok]]
        return out

    def sample_bilinear(self, lat, lon) -> np.ndarray:
        """Bilinear interpolation; falls back to nearest next to no-data."""
        r, c = self._rc(lat, lon)
        h, w = self.data.shape
        r0 = np.clip(np.floor(r).astype(int), 0, max(h - 2, 0))
        c0 = np.clip(np.floor(c).astype(int), 0, max(w - 2, 0))
        fr = np.clip(r - r0, 0, 1)
        fc = np.clip(c - c0, 0, 1)
        r1 = np.minimum(r0 + 1, h - 1)
        c1 = np.minimum(c0 + 1, w - 1)
        z = self.data
        out = (z[r0, c0] * (1 - fr) * (1 - fc) + z[r0, c1] * (1 - fr) * fc
               + z[r1, c0] * fr * (1 - fc) + z[r1, c1] * fr * fc)
        near = self.sample_nearest(lat, lon)
        inside = (r >= -0.5) & (r <= h - 0.5) & (c >= -0.5) & (c <= w - 0.5)
        out = np.where(np.isfinite(out), out, near)
        return np.where(inside, out, np.nan)

    def row_lats(self) -> np.ndarray:
        return self.north - (np.arange(self.data.shape[0]) + 0.5) * self.dlat


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

    def read_grids(self, south: float, west: float, north: float, east: float,
                   pad_px: int = 2, max_px: int = 2000, **kw) -> list[RasterGrid]:
        """Blocks covering the bounding box (padded by ``pad_px`` pixels),
        decimated so no side exceeds ``max_px``. Remote sources also take
        ``remote_max_rows`` / ``remote_max_decimation`` (HTTP budget). Empty list when the box is
        outside the source. Raises :class:`RasterUnavailableError` on failure.
        """
        return []

    def close(self) -> None:  # pragma: no cover - default no-op
        pass
