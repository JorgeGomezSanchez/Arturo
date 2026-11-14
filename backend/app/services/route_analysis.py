"""Route analysis: elevation profile, statistics and hazards.

Input: the vertices of a hand-drawn route (A, waypoints, B) and a travel
mode. The line is sampled along great circles at the resolution of the
best elevation data available along it (200 m HRSC+MOLA crops, the live
USGS 200 m DEM in Earth mode, MOLA elsewhere), and at every sample:

* elevation (bilinear), terrain slope (Horn 3x3 on the DEM block, metric
  spacing), roughness (detrended RMS height in 5x5 pixels);
* along-track grade between consecutive samples;
* thermal inertia, dust cover index (nearest TES pixel);
* pressure and cosmic-ray dose rate from the elevation (environment.py);
* night minimum temperature from the thermal model, run at a few points
  and interpolated.

Travel time uses the mode speed with a grade penalty (Tobler for walking,
linear for rovers); the traversal dose integrates the dose rate over that
time. Hazards are contiguous stretches where a value crosses a threshold
from routes.yaml, plus route-wide ones (duration, total dose). Every
stretch gets the worst severity on it so the frontend can colour the line.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from numpy.lib.stride_tricks import sliding_window_view

from app.models.route import (
    SEVERITY_ORDER, AnalyzeRequest, DataUse, Hazard, ProfilePoint, RouteAnalysis, RoutesConfig, RouteSegment,
)
from app.rasters.base import MARS_RADIUS_M, RasterGrid
from app.rasters.factory import RasterDataset
from app.services import environment as env
from app.services.geodesy import densify, haversine_m
from app.services.mars_time import mars_time
from app.services.thermal import surface_temperature

LEVELS = ["ok", "info", "warning", "danger"]
DEFAULT_ALBEDO = 0.25
DEFAULT_INERTIA = 250.0
MAX_PROFILE_POINTS = 600


class RouteAnalysisError(ValueError):
    """Bad input (unknown mode, zero length, antimeridian...)."""


# ------------------------------------------------------------------ grids
def slope_grid(g: RasterGrid) -> np.ndarray:
    """Horn slope (degrees) of a DEM block; NaN on the border and next to no-data."""
    z = g.data
    out = np.full(z.shape, np.nan)
    if z.shape[0] < 3 or z.shape[1] < 3:
        return out
    dy = MARS_RADIUS_M * math.radians(g.dlat)
    lat = g.row_lats()[1:-1, None]
    dx = MARS_RADIUS_M * math.radians(g.dlon) * np.maximum(np.cos(np.radians(lat)), 1e-6)
    a, b, c = z[:-2, :-2], z[:-2, 1:-1], z[:-2, 2:]
    d, f = z[1:-1, :-2], z[1:-1, 2:]
    gg, h, i = z[2:, :-2], z[2:, 1:-1], z[2:, 2:]
    dzdx = ((c + 2 * f + i) - (a + 2 * d + gg)) / (8 * dx)
    dzdy = ((a + 2 * b + c) - (gg + 2 * h + i)) / (8 * dy)
    out[1:-1, 1:-1] = np.degrees(np.arctan(np.hypot(dzdx, dzdy)))
    return out


def roughness_grid(g: RasterGrid) -> np.ndarray:
    """RMS height (m) after removing the best-fit plane in 5x5 windows."""
    z = g.data
    out = np.full(z.shape, np.nan)
    if z.shape[0] < 5 or z.shape[1] < 5:
        return out
    w = sliding_window_view(z, (5, 5))
    k = np.arange(-2, 3, dtype=float)
    yy, xx = np.meshgrid(k, k, indexing="ij")
    mean = w.mean(axis=(-1, -2))
    bx = (w * xx).sum(axis=(-1, -2)) / 50.0  # sum(x^2) over the 5x5 grid = 50
    by = (w * yy).sum(axis=(-1, -2)) / 50.0
    resid = w - mean[..., None, None] - bx[..., None, None] * xx - by[..., None, None] * yy
    out[2:-2, 2:-2] = np.sqrt((resid**2).mean(axis=(-1, -2)))
    return out


def runs(mask: np.ndarray, gap: int = 1) -> list[tuple[int, int]]:
    """Inclusive index ranges where ``mask`` is true; gaps of <= ``gap``
    samples are bridged so one stretch is not split into crumbs."""
    idx = np.flatnonzero(mask)
    if idx.size == 0:
        return []
    out = []
    start = prev = int(idx[0])
    for i in idx[1:]:
        i = int(i)
        if i - prev > gap + 1:
            out.append((start, prev))
            start = i
        prev = i
    out.append((start, prev))
    return out


def fmt_km(m: float) -> str:
    return f"{m / 1000:.1f} km" if m >= 1000 else f"{m:.0f} m"


@dataclass
class _Samples:
    lat: np.ndarray
    lon: np.ndarray
    d: np.ndarray
    spacing: float


class RouteAnalyzer:
    def __init__(self, datasets: dict[str, RasterDataset], features, config: RoutesConfig):
        self.datasets = datasets
        self.config = config
        rim = config.hazards.get("crater_rim", {})
        dmin = float(rim.get("min_diameter_km", 1.0))
        feats, _ = features.query() if features is not None else ([], 0)
        craters = [f for f in feats if f.properties.category == "crater" and (f.properties.diameter_km or 0) >= dmin]
        self._craters = craters
        self._clat = np.array([f.lat for f in craters])
        self._clon = np.array([f.lon for f in craters])
        self._cdiam = np.array([f.properties.diameter_km for f in craters])

    # --------------------------------------------------------------
    def _grids(self, ds_id: str, box, pad: int = 3) -> list[RasterGrid]:
        ds = self.datasets.get(ds_id)
        if ds is None or not ds.installed:
            return []
        s = self.config.sampling
        return ds.source.read_grids(*box, pad_px=pad, remote_max_rows=s.remote_max_rows,
                                    remote_max_decimation=s.remote_max_decimation)

    @staticmethod
    def _sample_first(grids: list[RasterGrid], lat, lon, arrays=None, bilinear=False):
        """Per sample, the value from the first block that has one.
        Returns (values, index of the block used or -1)."""
        vals = np.full(lat.shape, np.nan)
        used = np.full(lat.shape, -1)
        for gi, g in enumerate(grids):
            need = np.isnan(vals)
            if not need.any():
                break
            data = None if arrays is None else arrays[gi]
            if bilinear and data is None:
                v = g.sample_bilinear(lat[need], lon[need])
            else:
                v = g.sample_nearest(lat[need], lon[need], data)
            ok = np.isfinite(v)
            sel = np.flatnonzero(need)[ok]
            vals[sel] = v[ok]
            used[sel] = gi
        return vals, used

    # --------------------------------------------------------------
    def analyze(self, req: AnalyzeRequest) -> RouteAnalysis:
        cfg = self.config
        mode = cfg.modes.get(req.mode)
        if mode is None:
            raise RouteAnalysisError(f"unknown travel mode '{req.mode}' (known: {', '.join(cfg.modes)})")
        verts = [(float(lon), float(lat)) for lon, lat in req.coordinates]
        lons = [v[0] for v in verts]
        if max(lons) - min(lons) > 180:
            raise RouteAnalysisError("routes crossing the ±180° meridian are not supported yet")
        _, _, _, vd = densify(verts, 1e12)
        total = vd[-1]
        if total < 1.0:
            raise RouteAnalysisError("start and end are the same point")
        ls = mars_time().ls if req.ls is None else req.ls

        # Bounding box from a coarse great-circle sampling (long legs bow).
        clat, clon, _, _ = densify(verts, max(total / 200, 10.0))
        box = (float(clat.min()), float(clon.min()), float(clat.max()), float(clon.max()))

        dem = self._grids("elevation", box)
        useful = [g for g in dem if np.isfinite(g.sample_nearest(clat, clon)).any()]
        best_res = min((g.source.resolution_m for g in useful), default=None)
        s = cfg.sampling
        spacing = max(s.min_spacing_m, best_res or 0.0, total / s.max_samples)
        if best_res is None:
            spacing = max(spacing, total / 500)
        lat, lon, d, vertex_d = densify(verts, spacing)
        n = lat.size
        spacing = total / max(n - 1, 1)

        # --- terrain from the DEM blocks
        elev, used = self._sample_first(dem, lat, lon, bilinear=True)
        slope = np.full(n, np.nan)
        rough = np.full(n, np.nan)
        res_m = np.full(n, np.nan)
        for gi, g in enumerate(dem):
            sel = used == gi
            if not sel.any():
                continue
            slope[sel] = g.sample_nearest(lat[sel], lon[sel], slope_grid(g))
            rough[sel] = g.sample_nearest(lat[sel], lon[sel], roughness_grid(g))
            res_m[sel] = g.source.resolution_m

        seg_len = np.diff(d)
        dz = np.diff(elev)
        grade_seg = np.degrees(np.arctan2(dz, np.maximum(seg_len, 1e-6)))
        grade = np.append(grade_seg, grade_seg[-1] if grade_seg.size else np.nan)

        # --- surface properties
        ti, _ = self._sample_first(self._grids("thermal_inertia_night", box, 1), lat, lon)
        albedo, _ = self._sample_first(self._grids("albedo", box, 1), lat, lon)
        dci, _ = self._sample_first(self._grids("dust_cover_index", box, 1), lat, lon)

        # --- environment
        pressure = np.where(np.isfinite(elev), env.P0_PA * np.exp(-elev / env.SCALE_HEIGHT_M), np.nan)
        column = pressure / env.G_MARS / 10.0
        dose_rate = env.RAD_TOP_MSV_DAY * np.exp(-column / env.ATTENUATION_G_CM2)

        night = np.full(n, np.nan)
        k = min(s.thermal_points, n)
        pts = np.unique(np.linspace(0, n - 1, k).round().astype(int))
        tvals = []
        for i in pts:
            if not np.isfinite(pressure[i]):
                continue
            a = albedo[i] if np.isfinite(albedo[i]) else DEFAULT_ALBEDO
            ine = ti[i] if np.isfinite(ti[i]) else DEFAULT_INERTIA
            tr = surface_temperature(round(float(lat[i]), 1), round(ls), round(float(a), 2),
                                     round(float(ine), -1), round(float(pressure[i]), -1), 0.5)
            tvals.append((d[i], tr.t_min - 273.15))
        if tvals:
            night = np.interp(d, [t[0] for t in tvals], [t[1] for t in tvals])

        # --- travel time and dose
        g_rad = np.radians(np.nan_to_num(grade_seg))
        if mode.speed_model == "tobler":
            factor = np.exp(-3.5 * np.abs(np.tan(g_rad) + 0.05)) / math.exp(-3.5 * 0.05)
        else:
            factor = np.maximum(0.2, 1 - 0.8 * np.minimum(1.0, np.abs(np.degrees(g_rad)) / mode.slope.impassable_deg))
        dt_h = seg_len / 1000.0 / (mode.speed_kmh * factor) if n > 1 else np.zeros(0)
        duration = float(dt_h.sum())
        rate_mid = (dose_rate[:-1] + dose_rate[1:]) / 2
        rate_mid = np.where(np.isfinite(rate_mid), rate_mid, env.RAD_TOP_MSV_DAY)  # unknown: assume worst
        dose = float((rate_mid * dt_h / 24.0).sum())

        # --- hazards
        level = np.zeros(n, dtype=int)
        hazards: list[Hazard] = []
        samples = _Samples(lat, lon, d, spacing)
        H = cfg.hazards

        def add(htype, mask, values, sev_fn, title_fn, desc_fn, unit="", threshold=None, worst="max",
                colour=True, scope="segment"):
            for i0, i1 in runs(mask):
                seg = values[i0:i1 + 1]
                if np.all(np.isnan(seg)):
                    j = i0
                else:
                    j = i0 + int(np.nanargmax(seg) if worst == "max" else np.nanargmin(seg))
                v = values[j]
                sev_idx = max(sev_fn(x) for x in seg) if not np.all(np.isnan(seg)) else sev_fn(v)
                if sev_idx <= 0:
                    continue
                if colour:
                    for ii in range(i0, i1 + 1):
                        level[ii] = max(level[ii], sev_fn(values[ii]) if np.isfinite(values[ii]) else sev_idx)
                # threshold: one value, or {severity index: value} to report the limit that was crossed
                thr = threshold.get(sev_idx) if isinstance(threshold, dict) else threshold
                hazards.append(self._hazard(samples, htype, len(hazards), LEVELS[sev_idx], title_fn(v, sev_idx),
                                            desc_fn(v, sev_idx, i0, i1), v, unit, thr, i0, i1, j, scope))

        def tier(v, warn=None, danger=None, info=None, below=False):
            if not np.isfinite(v):
                return 0
            cmp = (lambda x, t: x <= t) if below else (lambda x, t: x >= t)
            if danger is not None and cmp(v, danger):
                return 3
            if warn is not None and cmp(v, warn):
                return 2
            if info is not None and cmp(v, info):
                return 1
            return 0

        sd, si = mode.slope.difficult_deg, mode.slope.impassable_deg
        res_txt = lambda i0, i1: fmt_km(3 * float(np.nanmax(res_m[i0:i1 + 1]))) if np.isfinite(res_m[i0:i1 + 1]).any() else "?"
        add("slope", np.nan_to_num(slope) >= sd, slope, lambda v: tier(v, sd, si),
            lambda v, t: "Impassable slope" if t == 3 else "Steep slope",
            lambda v, t, i0, i1: (f"Terrain slope up to {v:.0f}° ({mode.label}: difficult from {sd:g}°, "
                                  f"impassable from {si:g}°). Measured over a {res_txt(i0, i1)} baseline: "
                                  "local slopes can be steeper."),
            "°", {2: sd, 3: si})

        gi_, gw_ = H["grade_deg"]["info"], H["grade_deg"]["warning"]
        agr = np.abs(grade)
        add("grade", np.nan_to_num(agr) >= gi_, agr, lambda v: tier(v, gw_, None, gi_),
            lambda v, t: "Steep climb or descent",
            lambda v, t, i0, i1: (f"Along the route the ground rises or falls up to {v:.0f}° "
                                  f"({'climb' if np.nanmax(grade[i0:i1 + 1]) >= -np.nanmin(grade[i0:i1 + 1]) else 'descent'}): "
                                  "slower and more tiring; braking matters on descents."),
            "°", {1: gi_, 2: gw_})

        # Roughness thresholds scale with the window size (see routes.yaml).
        rcfg = H["roughness_m"]
        scale = np.where(np.isfinite(res_m), (5 * np.nan_to_num(res_m, nan=200.0) / float(rcfg.get(
            "reference_window_m", 1000))) ** float(rcfg.get("hurst", 0.7)), 1.0)
        rough_n = rough / scale  # equivalent RMS height in a 1 km window
        rw, rd = float(rcfg["warning"]), float(rcfg["danger"])
        add("roughness", np.nan_to_num(rough_n) >= rw, rough_n, lambda v: tier(v, rw, rd),
            lambda v, t: "Very rough terrain" if t == 3 else "Rough terrain",
            lambda v, t, i0, i1: (f"Height variations of {v:.0f} m RMS around the local trend, scaled to a 1 km "
                                  f"window (measured over {fmt_km(5 * float(np.nanmax(res_m[i0:i1 + 1])))}): "
                                  "ridges, gullies or blocky ground."),
            "m", {2: rw, 3: rd})

        tiw = H["soft_ground_ti"]["warning"]
        soft_sev = 2 if req.mode == "rover" else 1
        add("soft_ground", np.isfinite(ti) & (ti < tiw), ti, lambda v: soft_sev if np.isfinite(v) and v < tiw else 0,
            lambda v, t: "Soft, fine-grained ground",
            lambda v, t, i0, i1: (f"Thermal inertia {v:.0f} J m⁻² K⁻¹ s⁻½ (< {tiw:g}): loose dust or fine sand, "
                                  "poor traction; wheels can sink (Spirit was trapped in soft soil)."),
            "J m⁻² K⁻¹ s⁻½", tiw, worst="min")

        dw = H["dust_dci"]["warning"]
        add("dust", np.isfinite(dci) & (dci <= dw), dci, lambda v: 1 if np.isfinite(v) and v <= dw else 0,
            lambda v, t: "Dust-covered surface",
            lambda v, t, i0, i1: (f"Dust cover index {v:.3f} (≤ {dw:g}): fine dust that gets into seals and "
                                  "joints, hides holes and rocks, and lifts in wind."),
            "", dw, worst="min")

        tw, tdg = H["night_temperature_c"]["warning"], H["night_temperature_c"]["danger"]
        add("cold", np.nan_to_num(night, nan=99) <= tw, night, lambda v: tier(v, tw, tdg, below=True),
            lambda v, t: "Extreme night cold",
            lambda v, t, i0, i1: (f"Nights reach about {v:.0f} °C here at Ls {ls:.0f}° (thermal-model estimate). "
                                  "Do not get stranded overnight; plan shelter and power for heating."),
            "°C", {2: tw, 3: tdg}, worst="min")

        pi_, pw = H["low_pressure_pa"]["info"], H["low_pressure_pa"]["warning"]
        add("low_pressure", np.nan_to_num(pressure, nan=1e9) < pi_, pressure, lambda v: tier(v, pw, None, pi_, below=True),
            lambda v, t: "High altitude, very thin air",
            lambda v, t, i0, i1: (f"Estimated pressure {v:.0f} Pa: less atmosphere above you means more radiation, "
                                  "and vehicles that need aerobraking or parachutes cannot land here."),
            "Pa", {1: pi_, 2: pw}, worst="min")

        drw = H["dose_rate_msv_day"]["warning"]
        add("radiation_rate", np.nan_to_num(dose_rate) >= drw, dose_rate, lambda v: tier(v, drw),
            lambda v, t: "Higher radiation",
            lambda v, t, i0, i1: (f"Cosmic-ray dose rate about {v:.2f} mSv/day (Gale floor: 0.67): thin air "
                                  "shields less. Estimate scaled from Curiosity RAD."),
            "mSv/day", drw)

        nd = np.isnan(elev).astype(float)
        nd_sev = LEVELS.index(str(H["no_data"].get("severity", "warning")))
        add("no_data", nd > 0, nd, lambda v: nd_sev if v > 0 else 0,
            lambda v, t: "Unknown terrain (no elevation data)",
            lambda v, t, i0, i1: "No elevation data here: slope, roughness and hazards cannot be checked.",
            "", None)

        ci = H["coarse_data_m"]["info"]
        add("coarse_data", np.nan_to_num(res_m) > ci, res_m, lambda v: 1 if np.isfinite(v) and v > ci else 0,
            lambda v, t: "Coarse elevation data",
            lambda v, t, i0, i1: (f"Elevation only known at {fmt_km(v)} per pixel here: rocks, small craters "
                                  "and steep rims smaller than that are invisible to this analysis."),
            "m", ci, colour=False)

        self._rim_hazards(samples, hazards, level, H.get("crater_rim", {}))

        if mode.walk_back_km:
            from_a = haversine_m(lat[0], lon[0], lat, lon) / 1000.0
            wb = mode.walk_back_km
            add("walk_back", from_a > wb, from_a, lambda v: 2 if v > wb else 0,
                lambda v, t: "Beyond walk-back distance",
                lambda v, t, i0, i1: (f"Up to {v:.1f} km from the start (limit {wb:g} km): if the rover fails "
                                      "here the crew may not be able to walk back."),
                "km", wb, colour=False)

        # Route-wide hazards
        if duration > mode.max_duration_h:
            hazards.append(self._route_hazard(samples, "duration", len(hazards), "warning",
                                              "Longer than one excursion",
                                              f"Estimated {duration:.1f} h at {mode.speed_kmh:g} km/h ({mode.label}); "
                                              f"planned maximum {mode.max_duration_h:g} h. Plan a stop or shelter.",
                                              duration, "h", mode.max_duration_h))
        rdw, rdd = H["route_dose_msv"]["warning"], H["route_dose_msv"]["danger"]
        rsev = tier(dose, rdw, rdd)
        if rsev:
            hazards.append(self._route_hazard(samples, "route_dose", len(hazards), LEVELS[rsev],
                                              "Radiation dose for the trip",
                                              f"About {dose:.2f} mSv during the traversal (unshielded, quiet Sun).",
                                              dose, "mSv", rdw))

        hazards.sort(key=lambda h: (h.scope != "route", h.from_m, -SEVERITY_ORDER[h.severity]))
        counts = {sv: sum(1 for h in hazards if h.severity == sv) for sv in ("info", "warning", "danger")}
        max_sev = max([h.severity for h in hazards], key=lambda x: SEVERITY_ORDER[x], default="ok")

        # --- colour segments (worst severity per sample)
        segments: list[RouteSegment] = []
        key = list(zip(level.tolist(), np.isnan(elev).tolist()))
        i0 = 0
        for i in range(1, n + 1):
            if i == n or key[i] != key[i0]:
                j1 = min(i, n - 1)
                coords = [(float(lon[t]), float(lat[t])) for t in range(i0, j1 + 1)]
                if len(coords) == 1:
                    coords.append(coords[0])
                lv = LEVELS[key[i0][0]]
                segments.append(RouteSegment(from_m=float(d[i0]), to_m=float(d[j1]),
                                             level="ok" if lv == "info" else lv, no_data=key[i0][1],
                                             coordinates=coords))
                i0 = i

        # --- profile (downsampled)
        step = max(1, math.ceil(n / MAX_PROFILE_POINTS))
        profile = []
        for b in range(0, n, step):
            sl = slice(b, min(b + step, n))
            j = b
            profile.append(ProfilePoint(
                d=float(d[j]), lat=float(lat[j]), lon=float(lon[j]),
                elevation=_f(elev[j]), slope=_f(np.nanmax(slope[sl]) if np.isfinite(slope[sl]).any() else np.nan),
                grade=_f(grade[j]), level=LEVELS[int(level[sl].max())],
            ))
        if profile[-1].d < d[-1]:
            profile.append(ProfilePoint(d=float(d[-1]), lat=float(lat[-1]), lon=float(lon[-1]), elevation=_f(elev[-1]),
                                        slope=_f(slope[-1]), grade=_f(grade[-1]), level=LEVELS[int(level[-1])]))

        # --- data used
        data = []
        names = {}
        for gi, g in enumerate(dem):
            share = float(seg_weight(used == gi, d))
            if share > 0:
                key2 = (g.source.name, g.source.resolution_m)
                names[key2] = names.get(key2, 0) + share
        data = [DataUse(name=k[0], resolution_m=k[1], share=round(v, 3)) for k, v in
                sorted(names.items(), key=lambda kv: -kv[1])]
        if data:
            resolution = " · ".join(f"{fmt_km(x.resolution_m)}/px {x.name} ({x.share * 100:.0f} %)" for x in data)
        else:
            resolution = "no elevation data"

        fin = np.isfinite(elev)
        dz_f = np.diff(elev[fin]) if fin.sum() > 1 else np.zeros(0)
        return RouteAnalysis(
            mode=req.mode, mode_label=mode.label, ls=round(ls, 1), distance_m=round(total, 1),
            duration_h=round(duration, 2), dose_msv=round(dose, 4),
            gain_m=round(float(dz_f[dz_f > 0].sum()), 1), loss_m=round(float(-dz_f[dz_f < 0].sum()), 1),
            min_elevation_m=_f(np.nanmin(elev)) if fin.any() else None,
            max_elevation_m=_f(np.nanmax(elev)) if fin.any() else None,
            max_slope_deg=_f(np.nanmax(slope)) if np.isfinite(slope).any() else None,
            max_grade_deg=_f(np.nanmax(agr)) if np.isfinite(agr).any() else None,
            night_min_c=_f(np.nanmin(night)) if np.isfinite(night).any() else None,
            sample_spacing_m=round(spacing, 1), resolution=resolution, data=data,
            max_severity=max_sev, hazard_counts=counts, hazards=hazards, segments=segments, profile=profile,
            vertices=verts, vertex_distances_m=[round(x, 1) for x in vertex_d],
            method=("Samples every ~" + fmt_km(spacing) + " along great circles; slope (Horn 3×3) and roughness "
                    "(detrended RMS, 5×5) from the DEM; grade between samples; time from the mode speed with a "
                    f"{'Tobler' if mode.speed_model == 'tobler' else 'linear'} grade penalty; dose from the "
                    "Curiosity-RAD scaling; night cold from the thermal model. Thresholds: routes.yaml."),
        )

    # --------------------------------------------------------------
    def _rim_hazards(self, s: _Samples, hazards: list[Hazard], level: np.ndarray, cfg: dict) -> None:
        if not len(self._craters):
            return
        warn_d = float(cfg.get("warning_diameter_km", 5.0))
        # Only craters whose rim can be reached from the route's box.
        mid_lat, mid_lon = float(np.mean(s.lat)), float(np.mean(s.lon))
        reach = float(np.max(haversine_m(mid_lat, mid_lon, s.lat, s.lon)))
        dc = haversine_m(mid_lat, mid_lon, self._clat, self._clon)
        near = np.flatnonzero(dc <= reach + self._cdiam * 500 + 1000)
        for ci in near:
            r = self._cdiam[ci] * 500
            inside = haversine_m(self._clat[ci], self._clon[ci], s.lat, s.lon) <= r
            cross = np.flatnonzero(inside[1:] != inside[:-1])
            for c in cross:
                j = int(c)
                f = self._craters[ci]
                sev = "warning" if self._cdiam[ci] >= warn_d else "info"
                i0, i1 = max(j - 1, 0), min(j + 2, s.lat.size - 1)
                if sev == "warning":
                    level[i0:i1 + 1] = np.maximum(level[i0:i1 + 1], 2)
                going = "Leaves" if inside[j] else "Enters"
                hazards.append(self._hazard(
                    s, "crater_rim", len(hazards), sev, f"Crosses the rim of {f.properties.name} crater",
                    (f"{going} {f.properties.name} ({self._cdiam[ci]:.0f} km) across its rim. Crater rims are "
                     "steep and blocky; position from the IAU centre and diameter (±10 % of the radius)."),
                    float(self._cdiam[ci]), "km", float(cfg.get("min_diameter_km", 1.0)), i0, i1, j, "segment"))

    @staticmethod
    def _hazard(s: _Samples, htype, idx, sev, title, desc, value, unit, threshold, i0, i1, j, scope) -> Hazard:
        half = s.spacing / 2
        c0, c1 = max(i0 - 1, 0), min(i1 + 1, s.lat.size - 1)
        return Hazard(
            id=f"{htype}-{idx}", type=htype, severity=sev, title=title, description=desc,
            value=_f(value), unit=unit, threshold=threshold, scope=scope,
            from_m=round(max(float(s.d[i0]) - (half if i0 == i1 else 0), 0.0), 1),
            to_m=round(min(float(s.d[i1]) + (half if i0 == i1 else 0), float(s.d[-1])), 1),
            lat=float(s.lat[j]), lon=float(s.lon[j]),
            coordinates=[(float(s.lon[t]), float(s.lat[t])) for t in range(c0, c1 + 1)],
        )

    @staticmethod
    def _route_hazard(s: _Samples, htype, idx, sev, title, desc, value, unit, threshold) -> Hazard:
        return Hazard(id=f"{htype}-{idx}", type=htype, severity=sev, title=title, description=desc,
                      value=_f(value), unit=unit, threshold=threshold, scope="route", from_m=0.0,
                      to_m=round(float(s.d[-1]), 1), lat=float(s.lat[0]), lon=float(s.lon[0]))


def seg_weight(mask: np.ndarray, d: np.ndarray) -> float:
    """Fraction of the route length covered by samples where mask is true."""
    if d[-1] <= 0:
        return 0.0
    w = np.zeros(d.size)
    seg = np.diff(d)
    w[:-1] += seg / 2
    w[1:] += seg / 2
    return float(w[mask].sum() / d[-1])


def _f(v) -> float | None:
    try:
        v = float(v)
    except (TypeError, ValueError):
        return None
    return round(v, 3) if math.isfinite(v) else None
