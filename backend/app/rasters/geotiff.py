"""GeoTIFF-backed raster sources (local files or HTTP range reads)."""

from __future__ import annotations

import glob
import logging
import threading
import time
from pathlib import Path

import numpy as np
import rasterio
from rasterio.windows import Window

from app.rasters.base import RasterSource, RasterUnavailableError, RasterWindow, SourceInfo

log = logging.getLogger(__name__)


def _wrap_lon(lon: float) -> float:
    return ((lon + 180.0) % 360.0) - 180.0


class GeoTiffRasterSource(RasterSource):
    """One GeoTIFF on a lat/lon grid. ``path`` may be a file path or an
    ``https://`` URL (read with GDAL's ``/vsicurl/`` HTTP range requests).

    The dataset is opened lazily and kept open; reads are serialised with
    a lock because rasterio datasets are not thread-safe (FastAPI runs
    sync endpoints in a thread pool).
    """

    def __init__(self, path: str, info: SourceInfo, *, scale: float = 1.0, offset: float = 0.0,
                 bands: list[int] | None = None, band_names: list[str] | None = None,
                 timeout_s: float = 8.0):
        self.path = path
        self.info = info
        self.scale = scale
        self.offset = offset
        self.bands = bands or [1]
        self.band_names = band_names or []
        self.remote = path.startswith(("http://", "https://"))
        self.timeout_s = timeout_s
        self._ds = None
        self._lock = threading.Lock()

    # -- internals ---------------------------------------------------
    def _env(self) -> rasterio.Env:
        if not self.remote:
            return rasterio.Env()
        return rasterio.Env(
            GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR",
            CPL_VSIL_CURL_ALLOWED_EXTENSIONS=".tif,.tiff",
            GDAL_HTTP_TIMEOUT=str(int(max(1, self.timeout_s))),
            GDAL_HTTP_CONNECTTIMEOUT=str(int(max(1, self.timeout_s / 2))),
            GDAL_HTTP_MAX_RETRY="1",
            VSI_CACHE="TRUE",
        )

    def _open(self):
        if self._ds is None:
            target = "/vsicurl/" + self.path if self.remote else self.path
            try:
                with self._env():
                    self._ds = rasterio.open(target)
            except Exception as exc:  # rasterio raises several types
                raise RasterUnavailableError(f"cannot open {self.path}: {exc}") from exc
        return self._ds

    # -- RasterSource ------------------------------------------------
    def covers(self, lat: float, lon: float) -> bool:
        ds = self._open()
        b = ds.bounds
        lon = _wrap_lon(lon)
        return b.bottom <= lat <= b.top and b.left <= lon <= b.right

    def read(self, lat: float, lon: float, radius: int = 0) -> RasterWindow | None:
        lon = _wrap_lon(lon)
        with self._lock:
            ds = self._open()
            b = ds.bounds
            if not (b.bottom <= lat <= b.top and b.left <= lon <= b.right):
                return None
            row, col = ds.index(lon, lat)
            row = min(max(row, 0), ds.height - 1)
            col = min(max(col, 0), ds.width - 1)
            size = 2 * radius + 1
            # Clip the window to the raster and pad the rest with NaN
            # (only happens at the poles / the +-180 seam).
            r0, c0 = row - radius, col - radius
            rr0, cc0 = max(r0, 0), max(c0, 0)
            rr1, cc1 = min(r0 + size, ds.height), min(c0 + size, ds.width)
            try:
                with self._env():
                    raw = ds.read(self.bands, window=Window(cc0, rr0, cc1 - cc0, rr1 - rr0))
            except Exception as exc:
                raise RasterUnavailableError(f"read failed for {self.path}: {exc}") from exc
            nodata = ds.nodata
            dlon, dlat = abs(ds.transform.a), abs(ds.transform.e)
        data = np.full((len(self.bands), size, size), np.nan)
        block = raw.astype("float64")
        if nodata is not None:
            block[raw == nodata] = np.nan
        data[:, rr0 - r0: rr0 - r0 + block.shape[1], cc0 - c0: cc0 - c0 + block.shape[2]] = block
        data = data * self.scale + self.offset
        if len(self.bands) == 1:
            data = data[0]
        return RasterWindow(data=data, dlat=dlat, dlon=dlon, source=self.info, band_names=self.band_names)

    def close(self) -> None:
        if self._ds is not None:
            self._ds.close()
            self._ds = None


class MultiFileRasterSource(RasterSource):
    """Several local GeoTIFFs matched by a glob (e.g. ``zones/*_200m.tif``);
    the first file whose extent contains the whole window is used."""

    def __init__(self, pattern: str, info: SourceInfo, **kwargs):
        self.info = info
        self.files = [GeoTiffRasterSource(p, info, **kwargs) for p in sorted(glob.glob(pattern))]

    def __bool__(self) -> bool:
        return bool(self.files)

    def read(self, lat, lon, radius=0):
        for f in self.files:
            win = f.read(lat, lon, radius)
            if win is not None and not np.isnan(win.data).any():
                return win
        return None

    def close(self):
        for f in self.files:
            f.close()


class LayeredRasterSource(RasterSource):
    """Priority list of sources: the first one with a valid centre value wins.

    A source that raises (e.g. the remote DEM times out) is skipped for
    ``cooldown_s`` seconds so one slow server does not make every click slow.
    """

    def __init__(self, sources: list[RasterSource], cooldown_s: float = 300.0):
        self.sources = sources
        self.cooldown_s = cooldown_s
        self._down_until: dict[int, float] = {}
        self.info = sources[0].info if sources else None

    def read(self, lat, lon, radius=0):
        errors = []
        for i, src in enumerate(self.sources):
            if self._down_until.get(i, 0) > time.monotonic():
                continue
            try:
                win = src.read(lat, lon, radius)
            except RasterUnavailableError as exc:
                log.warning("raster source %s unavailable: %s", src.info.id, exc)
                self._down_until[i] = time.monotonic() + self.cooldown_s
                errors.append(str(exc))
                continue
            if win is not None and np.all(np.isfinite(np.atleast_1d(win.center))):
                return win
        return None

    def close(self):
        for s in self.sources:
            s.close()


def local_path(root: Path, rel: str) -> str:
    p = Path(rel)
    return str(p if p.is_absolute() else root / p)
