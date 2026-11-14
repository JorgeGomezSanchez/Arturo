"""Loads ``map.yaml`` (map configuration + detail zones)."""

from __future__ import annotations

from functools import lru_cache

import yaml

from app.core.config import get_settings
from app.models.map import MapConfig, Zone
from app.models.poi import PoiCategory, PoiVisibility


@lru_cache
def _raw() -> dict:
    with open(get_settings().map_file, encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def get_map_config() -> MapConfig:
    raw = _raw()
    return MapConfig(**raw["map"], poi_visibility=PoiVisibility(**raw.get("poi_visibility", {})))


def get_zones() -> list[Zone]:
    return [Zone(**z) for z in _raw().get("zones", [])]


def get_poi_categories() -> list[PoiCategory]:
    return [PoiCategory(**c) for c in _raw().get("poi_categories", [])]
