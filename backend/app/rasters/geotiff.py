"""GeoTIFF-backed raster sources (local files or HTTP range reads)."""

from __future__ import annotations

import glob
import logging
import threading
import time
from dataclasses import replace
from pathlib import Path

import numpy as np
import rasterio
from rasterio.enums import Resampling
from rasterio.windows import Window

from app.rasters.base import RasterGrid, RasterSource, RasterUnavailableError, RasterWindow, SourceInfo

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

    def read_grids(self, south, west, north, east, pad_px=2, max_px=2000, remote_max_rows=80,
                   remote_max_decimation=2):
        west, east = _wrap_lon(west), _wrap_lon(east)
        if east < west:  # crossing the antimeridian is not supported (yet)
            west, east = -180.0, 180.0
        with self._lock:
            ds = self._open()
            b = ds.bounds
            if north < b.bottom or south > b.top or east < b.left or west > b.right:
                return []
            dlon, dlat = abs(ds.transform.a), abs(ds.transform.e)
            c0 = int(np.floor((max(west, b.left) - b.left) / dlon)) - pad_px
            c1 = int(np.ceil((min(east, b.right) - b.left) / dlon)) + pad_px
            r0 = int(np.floor((b.top - min(north, b.top)) / dlat)) - pad_px
            r1 = int(np.ceil((b.top - max(south, b.bottom)) / dlat)) + pad_px
            c0, r0 = max(c0, 0), max(r0, 0)
            c1, r1 = min(c1, ds.width), min(r1, ds.height)
            rows, cols = r1 - r0, c1 - c0
            if rows <= 0 or cols <= 0:
                return []
            # Remote GeoTIFFs like the USGS DEM have one row per strip, so
            # every row is one HTTP range request: big blocks are read
            # decimated (GDAL then uses the overviews) and blocks that
            # would need more decimation than allowed are skipped (the
            # caller falls back to the next, local, source).
            limit_r = min(max_px, remote_max_rows) if self.remote else max_px
            f = max(1, int(np.ceil(max(rows / limit_r, cols / max_px))))
            if self.remote and f > remote_max_decimation:
                log.info("remote block %dx%d too big for %s (x%d), skipped", rows, cols, self.info.id, f)
                return []
            out_shape = (len(self.bands), max(1, int(np.ceil(rows / f))), max(1, int(np.ceil(cols / f))))
            try:
                with self._env():
                    raw = ds.read(self.bands[:1], window=Window(c0, r0, cols, rows), out_shape=out_shape,
                                  resampling=Resampling.nearest)
            except Exception as exc:
                raise RasterUnavailableError(f"block read failed for {self.path}: {exc}") from exc
            nodata = ds.nodata
        data = raw[0].astype("float64")
        if nodata is not None:
            data[raw[0] == nodata] = np.nan
        data = data * self.scale + self.offset
        eff_dlat = rows * dlat / data.shape[0]
        eff_dlon = cols * dlon / data.shape[1]
        info = replace(self.info, resolution_m=self.info.resolution_m * eff_dlat / dlat) if f > 1 else self.info
        return [RasterGrid(data=data, north=b.top - r0 * dlat, west=b.left + c0 * dlon,
                           dlat=eff_dlat, dlon=eff_dlon, source=info)]

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

    def read_grids(self, south, west, north, east, pad_px=2, max_px=2000, **kw):
        out = []
        for f in self.files:
            out.extend(f.read_grids(south, west, north, east, pad_px, max_px, **kw))
        return out

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

    def read_grids(self, south, west, north, east, pad_px=2, max_px=2000, **kw):
        """All sources' blocks, best priority first (callers take, per
        sample, the first block with a value)."""
        out = []
        for i, src in enumerate(self.sources):
            if self._down_until.get(i, 0) > time.monotonic():
                continue
            try:
                out.extend(src.read_grids(south, west, north, east, pad_px, max_px, **kw))
            except RasterUnavailableError as exc:
                log.warning("raster source %s unavailable: %s", src.info.id, exc)
                self._down_until[i] = time.monotonic() + self.cooldown_s
        return out

    def close(self):
        for s in self.sources:
            s.close()


def local_path(root: Path, rel: str) -> str:
    p = Path(rel)
    return str(p if p.is_absolute() else root / p)
