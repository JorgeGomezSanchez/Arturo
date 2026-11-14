"""Label display rules for named features (pure functions, unit-tested).

Two numbers decide whether a label is drawn:

* ``min_zoom`` — the label is not even sent below this zoom. It is the
  first zoom at which the feature is at least ``LABEL_MIN_PX`` pixels
  across on screen, so a 150 km crater (Gale) appears around zoom 3 and a
  10 km crater around zoom 7. Features without a size use a per-category
  default.
* ``priority`` — when labels overlap on screen the frontend keeps the
  highest priority one (decluttering). It grows with the feature size
  (log10 of the diameter) plus a category bonus: landing sites always win,
  regional names (terra, planitia...) get a small boost, classical albedo
  names a small penalty.

Tune here; the data files never need rebuilding.
"""

from __future__ import annotations

import math
from typing import Optional

# Minimum on-screen size (pixels) of a feature before its name is shown.
LABEL_MIN_PX = 24.0
MAX_ZOOM = 18

# Fixed minimum zoom for some categories (overrides the size rule).
CATEGORY_MIN_ZOOM: dict[str, int] = {
    "landing_site": 1,      # always useful context, even from far away
    "exploration_zone": 3,  # regional human-mission candidates
}
# Minimum zoom when the diameter is unknown.
DEFAULT_MIN_ZOOM = 7
CATEGORY_BONUS: dict[str, float] = {
    "landing_site": 5.0,
    "exploration_zone": 0.3,
    "terra": 0.3,
    "planitia": 0.3,
    "vastitas": 0.3,
    "planum": 0.2,
    "mons": 0.2,
    "albedo": -0.5,
}


def pixels_across(diameter_km: float, zoom: float, radius_m: float) -> float:
    """On-screen size of a feature at ``zoom`` (equirectangular CRS: the
    360° circumference is 512 * 2^zoom pixels wide)."""
    circumference_km = 2 * math.pi * radius_m / 1000.0
    return diameter_km * (512 * 2**zoom) / circumference_km


def min_zoom_for(category: str, diameter_km: Optional[float], radius_m: float) -> int:
    if category in CATEGORY_MIN_ZOOM:
        return CATEGORY_MIN_ZOOM[category]
    if not diameter_km or diameter_km <= 0:
        return DEFAULT_MIN_ZOOM
    circumference_km = 2 * math.pi * radius_m / 1000.0
    # Solve diameter * 512 * 2^z / circumference >= LABEL_MIN_PX for z.
    z = math.log2(LABEL_MIN_PX * circumference_km / (512 * diameter_km))
    zoom = max(0, math.ceil(z - 1e-9))
    if category == "albedo":
        zoom += 1  # classical albedo names are huge but less useful
    return min(MAX_ZOOM, zoom)


def priority_for(category: str, diameter_km: Optional[float]) -> float:
    size = math.log10(max(diameter_km or 1.0, 1.0))
    return round(size + CATEGORY_BONUS.get(category, 0.0), 4)
