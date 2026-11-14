"""Great-circle helpers on the Mars sphere (R = 3,396,190 m).

Routes are drawn as straight lines between vertices, but distances and
the sampled path follow great circles (the shortest path on the
sphere), so a long route bows toward the pole on the map as it should.
"""

from __future__ import annotations

import math

import numpy as np

from app.rasters.base import MARS_RADIUS_M


def haversine_m(lat1, lon1, lat2, lon2, radius: float = MARS_RADIUS_M):
    """Great-circle distance; works on scalars or numpy arrays."""
    p1, p2 = np.radians(lat1), np.radians(lat2)
    dp = p2 - p1
    dl = np.radians(np.asarray(lon2) - np.asarray(lon1))
    a = np.sin(dp / 2) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(dl / 2) ** 2
    return 2 * radius * np.arcsin(np.sqrt(np.clip(a, 0, 1)))


def _xyz(lat: float, lon: float) -> np.ndarray:
    p, l = math.radians(lat), math.radians(lon)
    return np.array([math.cos(p) * math.cos(l), math.cos(p) * math.sin(l), math.sin(p)])


def densify(vertices: list[tuple[float, float]], spacing_m: float, radius: float = MARS_RADIUS_M):
    """Sample a polyline of [lon, lat] vertices along great circles.

    Returns (lat, lon, d, vertex_d): arrays of sample latitudes,
    longitudes (-180..180) and distance from the start in metres, plus the
    distance of every vertex. Vertices are always samples.
    """
    lats, lons, ds, vertex_d = [vertices[0][1]], [vertices[0][0]], [0.0], [0.0]
    total = 0.0
    for (lon1, lat1), (lon2, lat2) in zip(vertices[:-1], vertices[1:]):
        seg = float(haversine_m(lat1, lon1, lat2, lon2, radius))
        n = max(1, int(math.ceil(seg / spacing_m)))
        a, b = _xyz(lat1, lon1), _xyz(lat2, lon2)
        omega = math.acos(max(-1.0, min(1.0, float(a @ b))))
        for k in range(1, n + 1):
            t = k / n
            if omega < 1e-12:
                v = a
            else:
                v = (math.sin((1 - t) * omega) * a + math.sin(t * omega) * b) / math.sin(omega)
            lats.append(math.degrees(math.asin(max(-1.0, min(1.0, v[2])))))
            lons.append(math.degrees(math.atan2(v[1], v[0])))
            ds.append(total + seg * t)
        total += seg
        vertex_d.append(total)
    return np.array(lats), np.array(lons), np.array(ds), vertex_d
