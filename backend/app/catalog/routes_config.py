"""Loads ``routes.yaml`` (travel modes and hazard thresholds)."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml

from app.models.route import RoutesConfig


@lru_cache
def load_routes_config(path: Path) -> RoutesConfig:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    for mode_id, mode in raw.get("modes", {}).items():
        mode.setdefault("id", mode_id)
    return RoutesConfig(**raw)
