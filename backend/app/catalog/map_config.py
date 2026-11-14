"""Loads ``map.yaml`` (map configuration + detail zones)."""

from __future__ import annotations

from functools import lru_cache

import yaml

from app.core.config import get_settings
from app.models.map import MapConfig, Zone


@lru_cache
def _raw() -> dict:
    with open(get_settings().map_file, encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def get_map_config() -> MapConfig:
    return MapConfig(**_raw()["map"])


def get_zones() -> list[Zone]:
    return [Zone(**z) for z in _raw().get("zones", [])]
