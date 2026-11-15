"""Automatic route planning: least-cost path over a slope-based cost grid.

1. **Search area**: the A-B bounding box grown by ``margin_fraction`` of
   the route's size (``routes.yaml -> planning``).
2. **Grid**: every elevation source of the area is read through the
   RasterSource abstraction (200 m crops, the live USGS DEM in Earth
   mode, MOLA), slope (Horn) and roughness are computed on each native
   block, and the blocks are composited on a lattice at the finest
   resolution found, in source priority order. Grids above ``max_cells``
   are coarsened by k x k with the steepest slope of each block kept, so
   a coarse grid never hides an impassable pixel.
3. **Cost** of a cell = time to cross one metre of it: the mode's flat
   speed slowed by the terrain slope (Tobler's hiking function on foot,
   the linear slowdown for rovers - the same models the analysis uses),
   times penalties for difficult slope and roughness. Cells at or above
   the impassable slope (plus a clearance buffer) and, by default, cells
   without data are excluded.
4. **Search**: a :class:`GridPlanner`. Today scikit-image's
   ``MCP_Geometric`` (Dijkstra on the 8-connected grid with geometric edge
   lengths); the interface lets an A* with direction-aware edge costs
   replace it later.
5. **Simplification**: the pixel staircase becomes a few waypoints by
   greedy line-of-sight: a shortcut is taken only if its straight line
   crosses no excluded cell and costs at most (1 + tolerance) x the
   pixels it replaces.
6. The waypoints go through the normal :class:`RouteAnalyzer`, so the
   result is an ordinary, editable manual route.
"""

from __future__ import annotations

import logging
import math
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass

import numpy as np
from scipy import ndimage

from app.models.route import (
    AnalyzeRequest, PlanInfo, PlanningConfig, PlanRequest, PlanResponse, RouteAnalysis, RouteSummary, TravelMode,
)
from app.rasters.base import MARS_RADIUS_M
from app.services.geodesy import haversine_m
from app.services.route_analysis import RouteAnalysisError, RouteAnalyzer, fmt_km, roughness_grid, slope_grid

log = logging.getLogger(__name__)
DEG_M = MARS_RADIUS_M * math.pi / 180.0

EXCLUDED_SLOPE, EXCLUDED_BUFFER, EXCLUDED_NO_DATA = 1, 2, 3


class RoutePlanningError(RouteAnalysisError):
    """No plan possible. ``info`` explains why (shown to the astronaut)."""

    def __init__(self, reason: str, message: str, **info):
        super().__init__(message)
        self.reason = reason
        self.info = {"reason": reason, "message": message, **info}


# ------------------------------------------------------------- planners
@dataclass
class GridPath:
    cells: np.ndarray  # (n, 2) int rows/cols from start to end
    cumulative: np.ndarray  # (n,) cost from the start along the path
    total: float


class GridPlanner(ABC):
    """Least-cost path on a cost grid (cost per metre, inf = excluded)."""

    name: str = "grid planner"

    @abstractmethod
    def search(self, cost: np.ndarray, start: tuple[int, int], end: tuple[int, int],
               sampling: tuple[float, float]) -> tuple[GridPath | None, np.ndarray]:
        """Return (path or None if unreachable, cumulative cost grid from the
        start - inf where not reached - for diagnostics). ``sampling`` is
        the (row, column) pixel size in metres."""


class SkimageMcpPlanner(GridPlanner):
    """scikit-image ``MCP_Geometric``: Dijkstra, 8 neighbours, edge cost =
    mean of the two cells x the geometric edge length (diagonals √2)."""

    name = "scikit-image MCP_Geometric (Dijkstra, 8-connected)"

    def search(self, cost, start, end, sampling):
        from skimage.graph import MCP_Geometric  # imported lazily: heavy module

        mcp = MCP_Geometric(cost, fully_connected=True, sampling=sampling)
        cum, _ = mcp.find_costs([start], [end])
        if not np.isfinite(cum[end]):
            return None, cum
        cells = np.asarray(mcp.traceback(end), dtype=int)
        return GridPath(cells, cum[cells[:, 0], cells[:, 1]], float(cum[end])), cum


# ------------------------------------------------------------ cost grid
@dataclass
class CostSurface:
    cost: np.ndarray  # seconds per metre; inf = excluded
    slope: np.ndarray
    excluded: np.ndarray  # 0 or EXCLUDED_*
    north: float
    west: float
    dlat: float
    dlon: float
    dy_m: float
    dx_m: float
    data: str
    resolution_m: float
    native_resolution_m: float
    coarsened: int

    @property
    def shape(self):
        return self.cost.shape

    def rc(self, lat: float, lon: float) -> tuple[int, int]:
        r = int(np.clip(np.floor((self.north - lat) / self.dlat), 0, self.shape[0] - 1))
        c = int(np.clip(np.floor((lon - self.west) / self.dlon), 0, self.shape[1] - 1))
        return r, c

    def lonlat(self, r, c) -> tuple[np.ndarray, np.ndarray]:
        return self.west + (np.asarray(c) + 0.5) * self.dlon, self.north - (np.asarray(r) + 0.5) * self.dlat


def _block_max(a: np.ndarray, k: int) -> np.ndarray:
    """Running k x k maximum ignoring NaN (NaN only where all are NaN)."""
    if k <= 1:
        return a
    filled = np.where(np.isfinite(a), a, -np.inf)
    out = ndimage.maximum_filter(filled, size=k, mode="nearest")
    return np.where(np.isfinite(out), out, np.nan)


def speed_factor(slope_deg: np.ndarray, mode: TravelMode) -> np.ndarray:
    """Fraction of the flat-ground speed on a slope (same models as the analysis).

    The grid is isotropic (no travel direction), so the terrain slope is
    used as an uphill grade: Tobler exp(-3.5·tan s) normalised to 1 on flat
    ground for walking, max(0.2, 1 - 0.8·s/impassable) for rovers."""
    s = np.radians(np.clip(slope_deg, 0, 89))
    if mode.speed_model == "tobler":
        return np.exp(-3.5 * np.tan(s))
    return np.maximum(0.2, 1 - 0.8 * np.minimum(1.0, np.degrees(s) / mode.slope.impassable_deg))


# --------------------------------------------------------------- planner
class RoutePlanner:
    def __init__(self, analyzer: RouteAnalyzer, planner: GridPlanner | None = None):
        self.analyzer = analyzer
        self.planner = planner or SkimageMcpPlanner()

    @property
    def config(self):
        return self.analyzer.config

    # ----------------------------------------------------------------
    def _settings(self, req: PlanRequest) -> PlanningConfig:
        base = self.config.planning
        if req.weights is None:
            return base
        return base.model_copy(update=req.weights.model_dump(exclude_none=True))

    def _area(self, req: PlanRequest, p: PlanningConfig) -> tuple[float, float, float, float, list[str]]:
        (lon_a, lat_a), (lon_b, lat_b) = req.start, req.end
        notes = []
        if abs(lon_a - lon_b) > 180:
            raise RoutePlanningError("antimeridian", "Routes crossing the ±180° meridian cannot be planned yet. "
                                     "Plan each side separately.")
        dist = float(haversine_m(lat_a, lon_a, lat_b, lon_b))
        if dist < 1.0:
            raise RoutePlanningError("same_point", "A and B are the same point.")
        if dist > p.max_distance_km * 1000:
            raise RoutePlanningError("too_long", f"A and B are {fmt_km(dist)} apart; automatic planning is limited "
                                     f"to {p.max_distance_km:g} km. Add an intermediate stop and plan each leg.",
                                     distanceM=dist, limitM=p.max_distance_km * 1000)
        lat_mid = (lat_a + lat_b) / 2
        coslat = max(math.cos(math.radians(lat_mid)), 0.05)
        span_km = max(abs(lat_a - lat_b) * DEG_M, abs(lon_a - lon_b) * DEG_M * coslat) / 1000
        m_km = max(p.margin_fraction * span_km, p.min_margin_km)
        m_lat = m_km * 1000 / DEG_M
        m_lon = m_km * 1000 / (DEG_M * coslat)
        south, north = min(lat_a, lat_b) - m_lat, max(lat_a, lat_b) + m_lat
        west, east = min(lon_a, lon_b) - m_lon, max(lon_a, lon_b) + m_lon
        if max(abs(south), abs(north)) > p.max_abs_lat:
            raise RoutePlanningError("polar", f"The search area reaches {max(abs(south), abs(north)):.1f}° of "
                                     f"latitude; planning is limited to ±{p.max_abs_lat:g}° because the lat/lon "
                                     "grid is too distorted near the poles.", maxAbsLat=p.max_abs_lat)
        if west < -180 or east > 180:
            west, east = max(west, -180.0), min(east, 180.0)
            notes.append("The search area was clipped at the ±180° meridian.")
        return south, west, north, east, notes

    def _surface(self, box, mode: TravelMode, p: PlanningConfig, notes: list[str]) -> CostSurface:
        south, west, north, east = box
        grids = [g for g in self.analyzer._grids("elevation", box, pad=3) if np.isfinite(g.data).any()]
        if not grids:
            raise RoutePlanningError("no_data", "There is no elevation data in this area.")
        finest = min(grids, key=lambda g: g.dlat)
        dlat, dlon = finest.dlat, finest.dlon
        rows = max(3, math.ceil((north - south) / dlat))
        cols = max(3, math.ceil((east - west) / dlon))
        k = max(1, math.ceil(math.sqrt(rows * cols / p.max_cells)))
        if k > 1:
            dlat, dlon = dlat * k, dlon * k
            rows, cols = max(3, math.ceil((north - south) / dlat)), max(3, math.ceil((east - west) / dlon))
            notes.append(f"Large area: the {finest.source.resolution_m:.0f} m grid was coarsened {k}×{k} "
                         f"(steepest slope of each block kept).")
            log.info("plan grid coarsened x%d to %dx%d", k, rows, cols)
        lon_c = west + (np.arange(cols) + 0.5) * dlon
        lat_c = north - (np.arange(rows) + 0.5) * dlat
        LAT, LON = np.meshgrid(lat_c, lon_c, indexing="ij")

        slope = np.full((rows, cols), np.nan)
        rough = np.full((rows, cols), np.nan)
        used = np.full((rows, cols), -1)
        rcfg = self.config.hazards.get("roughness_m", {})
        ref_w, hurst = float(rcfg.get("reference_window_m", 1000)), float(rcfg.get("hurst", 0.7))
        for gi, g in enumerate(grids):
            need = np.isnan(slope)
            if not need.any():
                break
            ratio = max(1, int(round(dlat / g.dlat)))
            s = _block_max(slope_grid(g), ratio)
            r = _block_max(roughness_grid(g), ratio) / ((5 * g.source.resolution_m / ref_w) ** hurst)
            sv = g.sample_nearest(LAT[need], LON[need], s)
            rv = g.sample_nearest(LAT[need], LON[need], r)
            ok = np.isfinite(sv)
            idx = np.flatnonzero(need)[ok]
            slope.flat[idx] = sv[ok]
            rough.flat[idx] = rv[ok]
            used.flat[idx] = gi

        # Data description: share of the grid per source.
        parts = []
        for gi, g in enumerate(grids):
            share = float((used == gi).mean())
            if share > 0.005:
                parts.append(f"{g.source.resolution_m:.0f} m/px {g.source.name} ({share * 100:.0f} %)")
        native = min(grids[gi].source.resolution_m for gi in np.unique(used[used >= 0])) if (used >= 0).any() \
            else finest.source.resolution_m

        # --- cost (seconds per metre)
        base = 3.6 / mode.speed_kmh
        cost = base / speed_factor(np.nan_to_num(slope), mode)
        cost = np.where(slope >= mode.slope.difficult_deg, cost * p.difficult_multiplier, cost)
        hz = self.config.hazards.get("roughness_m", {})
        if "warning" in hz:
            cost = np.where(np.nan_to_num(rough) >= float(hz["warning"]), cost * p.roughness_warning_multiplier, cost)
        if "danger" in hz:
            cost = np.where(np.nan_to_num(rough) >= float(hz["danger"]), cost * p.roughness_danger_multiplier, cost)
        excluded = np.zeros((rows, cols), dtype=np.int8)
        steep = np.nan_to_num(slope) >= mode.slope.impassable_deg
        if p.impassable_buffer_px > 0 and steep.any():
            buf = ndimage.binary_dilation(steep, structure=np.ones((3, 3), bool), iterations=p.impassable_buffer_px)
            excluded[buf & ~steep] = EXCLUDED_BUFFER
        excluded[steep] = EXCLUDED_SLOPE
        nod = np.isnan(slope)
        if p.no_data == "impassable":
            excluded[nod] = EXCLUDED_NO_DATA
        else:
            cost = np.where(nod, base * p.no_data_multiplier, cost)
        cost = np.where(excluded > 0, np.inf, cost)

        lat_mid = (north + south) / 2
        return CostSurface(
            cost=cost, slope=slope, excluded=excluded, north=north, west=west, dlat=dlat, dlon=dlon,
            dy_m=DEG_M * dlat, dx_m=DEG_M * dlon * max(math.cos(math.radians(lat_mid)), 0.05),
            data="; ".join(parts) or finest.source.name, resolution_m=native * k, native_resolution_m=native,
            coarsened=k,
        )

    def _open_end(self, surf: CostSurface, cell, which: str, mode: TravelMode, p: PlanningConfig):
        """A or B on an excluded cell: refuse if it is the terrain itself,
        clear the clearance buffer around it otherwise."""
        r, c = cell
        ex = surf.excluded[r, c]
        if ex == EXCLUDED_SLOPE:
            raise RoutePlanningError(f"{which}_blocked", f"{which.upper()} is on terrain steeper than the "
                                     f"{mode.label.lower()} limit ({surf.slope[r, c]:.0f}° ≥ "
                                     f"{mode.slope.impassable_deg:g}°). Move it to gentler ground.",
                                     slopeDeg=float(surf.slope[r, c]), limitDeg=mode.slope.impassable_deg)
        if ex == EXCLUDED_NO_DATA:
            raise RoutePlanningError(f"{which}_blocked", f"There is no elevation data at {which.upper()}.")
        b = p.impassable_buffer_px + 1
        r0, r1, c0, c1 = max(r - b, 0), r + b + 1, max(c - b, 0), c + b + 1
        win = surf.excluded[r0:r1, c0:c1]
        clear = win == EXCLUDED_BUFFER
        if clear.any():
            base = 3.6 / mode.speed_kmh
            sub = surf.cost[r0:r1, c0:c1]
            sub[clear] = base / speed_factor(np.nan_to_num(surf.slope[r0:r1, c0:c1][clear]), mode) * p.difficult_multiplier
            win[clear] = 0

    def _no_path(self, surf: CostSurface, cum: np.ndarray, end, mode: TravelMode, p: PlanningConfig):
        reach = np.isfinite(cum)
        rr, cc = np.nonzero(reach)
        er, ec = end
        dist = np.hypot((rr - er) * surf.dy_m, (cc - ec) * surf.dx_m)
        i = int(np.argmin(dist))
        lon, lat = surf.lonlat(rr[i], cc[i])
        touches = reach[0].any() or reach[-1].any() or reach[:, 0].any() or reach[:, -1].any()
        steep = float((surf.excluded == EXCLUDED_SLOPE).mean())
        nod = float((surf.excluded == EXCLUDED_NO_DATA).mean())
        cause = "slopes ≥ {:g}°".format(mode.slope.impassable_deg) if steep >= nod else "missing elevation data"
        msg = (f"No passable path for {mode.label.lower()} inside the search area: B is cut off by {cause}. "
               f"The closest reachable point is {fmt_km(float(dist[i]))} from B.")
        if touches:
            msg += " The reachable area touches the edge of the search area: a larger margin may find a way around."
        raise RoutePlanningError(
            "no_path", msg, closestReachable=[float(lon), float(lat)], gapM=float(dist[i]),
            impassableShare=steep, noDataShare=nod, limitDeg=mode.slope.impassable_deg,
            reachableTouchesEdge=bool(touches), marginFraction=p.margin_fraction,
        )

    # ------------------------------------------------------- simplify
    @staticmethod
    def _segment_cost(surf: CostSurface, a, b) -> float:
        (r0, c0), (r1, c1) = a, b
        length = math.hypot((r1 - r0) * surf.dy_m, (c1 - c0) * surf.dx_m)
        n = max(2, int(math.ceil(max(abs(r1 - r0), abs(c1 - c0)) * 2)) + 1)
        t = np.linspace(0, 1, n)
        rr = np.rint(r0 + (r1 - r0) * t).astype(int)
        cc = np.rint(c0 + (c1 - c0) * t).astype(int)
        v = surf.cost[rr, cc]
        if not np.all(np.isfinite(v)):
            return math.inf
        return float(v.mean() * length)

    def _simplify(self, surf: CostSurface, path: GridPath, tol: float) -> list[int]:
        """Indices of path cells kept as vertices (first and last included)."""
        cells, cum = path.cells, path.cumulative
        n = len(cells)
        keep = [0]
        i = 0
        while i < n - 1:
            j = i + 1
            # extend while the shortcut i->j+1 is allowed
            while j + 1 < n:
                c = self._segment_cost(surf, cells[i], cells[j + 1])
                if c > (cum[j + 1] - cum[i]) * (1 + tol) + 1e-9:
                    break
                j += 1
            keep.append(j)
            i = j
        return keep

    # ------------------------------------------------------------ plan
    def plan(self, req: PlanRequest) -> PlanResponse:
        t0 = time.perf_counter()
        mode = self.config.modes.get(req.mode)
        if mode is None:
            raise RoutePlanningError("unknown_mode", f"unknown travel mode '{req.mode}' "
                                     f"(known: {', '.join(self.config.modes)})")
        p = self._settings(req)
        south, west, north, east, notes = self._area(req, p)
        surf = self._surface((south, west, north, east), mode, p, notes)
        t_grid = time.perf_counter()
        (lon_a, lat_a), (lon_b, lat_b) = req.start, req.end
        start, end = surf.rc(lat_a, lon_a), surf.rc(lat_b, lon_b)
        self._open_end(surf, start, "a", mode, p)
        self._open_end(surf, end, "b", mode, p)

        path, cum = self.planner.search(surf.cost, start, end, (surf.dy_m, surf.dx_m))
        t_search = time.perf_counter()
        if path is None:
            self._no_path(surf, cum, end, mode, p)

        tol = p.simplify_cost_tolerance
        keep = self._simplify(surf, path, tol)
        while len(keep) - 2 > p.max_waypoints and tol < 1.0:
            tol = min(1.0, max(tol * 2, 0.02))
            keep = self._simplify(surf, path, tol)
        if len(keep) - 2 > p.max_waypoints:
            notes.append(f"The path needed {len(keep) - 2} waypoints; only the first {p.max_waypoints} were kept.")
        inner = keep[1:-1][: p.max_waypoints]
        if tol != p.simplify_cost_tolerance:
            notes.append(f"Simplified with a {tol * 100:.0f} % cost tolerance to stay within "
                         f"{p.max_waypoints} waypoints.")
        lons, lats = surf.lonlat(path.cells[inner, 0], path.cells[inner, 1]) if inner else ([], [])
        waypoints = [(float(lo), float(la)) for lo, la in zip(lons, lats)]
        if not waypoints:
            notes.append("The straight line is already the best path found.")

        t_simplify = time.perf_counter()
        analysis: RouteAnalysis = self.analyzer.analyze(AnalyzeRequest(
            coordinates=[req.start, *waypoints, req.end], mode=req.mode, ls=req.ls))
        straight = self.analyzer.analyze(AnalyzeRequest(coordinates=[req.start, req.end], mode=req.mode, ls=req.ls))
        t_end = time.perf_counter()
        elapsed = int((t_end - t0) * 1000)
        ms = lambda a, b: int(round((b - a) * 1000))
        log.info("planned %s route %d waypoints, grid %dx%d, %d ms", req.mode, len(waypoints), *surf.shape, elapsed)
        return PlanResponse(
            waypoints=waypoints,
            analysis=analysis,
            straight=RouteSummary(distance_m=straight.distance_m, duration_h=straight.duration_h,
                                  max_slope_deg=straight.max_slope_deg, max_severity=straight.max_severity,
                                  hazard_counts=straight.hazard_counts),
            info=PlanInfo(
                planner=self.planner.name, data=surf.data, resolution_m=surf.resolution_m,
                native_resolution_m=surf.native_resolution_m, coarsened=surf.coarsened,
                rows=surf.shape[0], cols=surf.shape[1], excluded_share=float((surf.excluded > 0).mean()),
                path_cells=len(path.cells), estimated_hours=path.total / 3600.0, elapsed_ms=elapsed,
                timings_ms={"grid": ms(t0, t_grid), "search": ms(t_grid, t_search),
                            "simplify": ms(t_search, t_simplify), "analysis": ms(t_simplify, t_end)},
                notes=notes,
            ),
        )
