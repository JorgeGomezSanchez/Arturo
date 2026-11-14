"""Builds the raster sources from ``rasters.yaml`` + settings.

This is the point-query counterpart of ``providers/factory.py``: the one
place that knows Earth mode may go online and Mars mode may not.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import yaml

from app.core.config import Settings
from app.models.point import RasterDatasetConfig
from app.rasters.base import RasterSource, SourceInfo
from app.rasters.geotiff import GeoTiffRasterSource, LayeredRasterSource, MultiFileRasterSource, local_path

log = logging.getLogger(__name__)


@dataclass
class RasterDataset:
    id: str
    config: RasterDatasetConfig
    source: LayeredRasterSource | None  # None = not installed

    @property
    def installed(self) -> bool:
        return self.source is not None and bool(self.source.sources)


@lru_cache
def load_raster_catalog(path: Path) -> dict[str, RasterDatasetConfig]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return {k: RasterDatasetConfig(**v) for k, v in raw.get("datasets", {}).items()}


def build_raster_datasets(settings: Settings) -> dict[str, RasterDataset]:
    allow_remote = settings.data_source == "remote" and settings.point_remote_dem
    out: dict[str, RasterDataset] = {}
    for ds_id, cfg in load_raster_catalog(settings.rasters_file).items():
        sources: list[RasterSource] = []
        for s in cfg.sources:
            info = SourceInfo(id=s.id, name=s.name, resolution_m=s.resolution_m, kind=s.kind)
            kw = dict(scale=s.scale, offset=s.offset, bands=s.bands, band_names=s.band_names,
                      timeout_s=settings.point_remote_timeout_s)
            if s.kind == "remote":
                if allow_remote and s.url:
                    sources.append(GeoTiffRasterSource(s.url, info, **kw))
                continue
            path = local_path(settings.rasters_dir, s.path or "")
            if any(ch in path for ch in "*?["):
                multi = MultiFileRasterSource(path, info, **kw)
                if multi:
                    sources.append(multi)
            elif Path(path).is_file():
                sources.append(GeoTiffRasterSource(path, info, **kw))
            elif not cfg.optional:
                log.warning("raster %s for dataset %s not found (run scripts/build_rasters.py)", path, ds_id)
        out[ds_id] = RasterDataset(ds_id, cfg, LayeredRasterSource(sources) if sources else None)
    return out


def describe(datasets: dict[str, RasterDataset]) -> str:
    """Short summary for /api/health, e.g. 'local GeoTIFF (7/8) + remote DEM'."""
    n = sum(1 for d in datasets.values() if d.installed)
    remote = any(
        getattr(s, "remote", False) for d in datasets.values() if d.source for s in d.source.sources
    )
    return f"local GeoTIFF ({n}/{len(datasets)} datasets)" + (" + remote 200 m DEM (USGS)" if remote else "")
