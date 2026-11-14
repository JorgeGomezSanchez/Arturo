"""Slope, aspect and roughness from a small DEM window.

* Slope/aspect: Horn (1981) finite differences on the 3x3 neighbourhood,
  with the true metric pixel size on Mars (east-west spacing shrinks with
  cos(latitude)).
* Roughness: RMS of the residuals after fitting a plane to the 5x5
  neighbourhood (detrended RMS height), plus the local relief (max - min).

Both depend strongly on the DEM resolution: a 3.7 km DEM smooths away
everything a rover or an astronaut would feel, so the baseline is always
reported with the value.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class SlopeResult:
    slope_deg: float
    aspect_deg: float | None  # downslope direction, 0 = north, clockwise; None if flat


def horn_slope(z: np.ndarray, dx: float, dy: float) -> SlopeResult | None:
    """``z``: 3x3 elevations (row 0 = north). ``dx``, ``dy`` in metres."""
    if z.shape != (3, 3) or not np.all(np.isfinite(z)):
        return None
    a, b, c = z[0]
    d, _, f = z[1]
    g, h, i = z[2]
    dzdx = ((c + 2 * f + i) - (a + 2 * d + g)) / (8 * dx)  # + = rises to the east
    dzdy = ((a + 2 * b + c) - (g + 2 * h + i)) / (8 * dy)  # + = rises to the north
    slope = math.degrees(math.atan(math.hypot(dzdx, dzdy)))
    if slope < 0.05:
        return SlopeResult(slope, None)
    # Downslope direction points against the gradient.
    aspect = (math.degrees(math.atan2(-dzdx, -dzdy)) + 360.0) % 360.0
    return SlopeResult(slope, aspect)


def detrended_rms(z: np.ndarray, dx: float, dy: float) -> tuple[float, float] | None:
    """(RMS height after removing the best-fit plane, max - min) in metres."""
    if not np.all(np.isfinite(z)):
        return None
    n = z.shape[0]
    yy, xx = np.mgrid[0:n, 0:n]
    A = np.column_stack([xx.ravel() * dx, yy.ravel() * dy, np.ones(n * n)])
    coef, *_ = np.linalg.lstsq(A, z.ravel(), rcond=None)
    resid = z.ravel() - A @ coef
    return float(np.sqrt(np.mean(resid**2))), float(z.max() - z.min())


COMPASS = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]


def compass(deg: float) -> str:
    return COMPASS[int(((deg + 22.5) % 360) // 45)]


def slope_class(deg: float) -> str:
    """Trafficability classes used in the panel (walking / rovers)."""
    if deg < 5:
        return "gentle"
    if deg < 15:
        return "moderate"
    if deg < 25:
        return "steep: hard for rovers"
    return "very steep: hazardous"
