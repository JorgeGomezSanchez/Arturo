"""Everything known about one location: ``GET /api/point``.

Combines (1) numeric rasters read through the RasterSource abstraction,
(2) the named-feature repository and (3) small physical models
(pressure, temperature, radiation). Every value carries its unit, source,
resolution and method so the UI can show where it came from; modelled
values are flagged ``estimate``.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np

from app.models.point import PointInfo, PointItem, PointQueryInfo, PointSection, SeriesPoint
from app.rasters.base import RasterWindow
from app.rasters.factory import RasterDataset
from app.repositories.features import FeatureRepository
from app.services import environment as env
from app.services.mars_time import hhmm, local_true_solar_hours, mars_time, season_name
from app.services.terrain import compass, detrended_rms, horn_slope, slope_class
from app.services.thermal import surface_temperature

DEFAULT_TAU = 0.5
DEFAULT_ALBEDO = 0.25
DEFAULT_INERTIA = 250.0
REGION_CATEGORIES = {"terra", "planitia", "planum", "vastitas", "palus"}
NOT_PLACES = {"landing_site", "exploration_zone", "albedo"}
# Roughly circular features: "inside" is meaningful for them. Elongated
# ones (valles, fossae, mensae...) are only reported as "nearest".
ROUND_CATEGORIES = {"crater", "patera"}
# Volcanoes and mountains: "on" when well inside their IAU circle.
EDIFICE_CATEGORIES = {"mons", "tholus"}
EDIFICE_INNER = 0.8

MINERAL_LABELS = {
    "plagioclase": "Plagioclase feldspar",
    "high_ca_pyroxene": "High-Ca pyroxene",
    "hematite": "Hematite",
    "sheet_silicates_glass": "Sheet silicates / high-Si glass",
    "surface_dust": "Surface dust (spectral endmember)",
}

PERIODS = {"A": "Amazonian", "H": "Hesperian", "N": "Noachian"}
EPOCH = {"e": "Early", "m": "Middle", "l": "Late"}


def fmt_lat(lat: float) -> str:
    return f"{abs(lat):.4f}° {'N' if lat >= 0 else 'S'}"


def fmt_lon(lon: float) -> str:
    return f"{abs(lon):.4f}° {'E' if lon >= 0 else 'W'}"


def resolution_text(m: float) -> str:
    return f"~{m / 1000:.1f} km/px" if m >= 1000 else f"~{m:.0f} m/px"


def geologic_age(code: str) -> str:
    """'lHb' -> 'Late Hesperian', 'AHi' -> 'Amazonian to Hesperian'."""
    epoch = EPOCH.get(code[0], "") if code and code[0].islower() else ""
    letters = [PERIODS[ch] for ch in code if ch in PERIODS]
    # Period letters come first in the code (after the epoch prefix).
    periods = []
    for ch in code[1:] if epoch else code:
        if ch in PERIODS:
            periods.append(PERIODS[ch])
        else:
            break
    periods = periods or letters[:1]
    if not periods:
        return "unknown"
    text = " to ".join(periods)
    return f"{epoch} {text}".strip()


class PointService:
    def __init__(self, datasets: dict[str, RasterDataset], features: FeatureRepository, radius_m: float,
                 data_source: str, rasters_dir: Path):
        self.datasets = datasets
        self.features = features
        self.radius_m = radius_m
        self.data_source = data_source
        self.geology_units = self._load_geology_legend(rasters_dir)
        self._feature_arrays()

    # ------------------------------------------------------------------
    def _load_geology_legend(self, rasters_dir: Path) -> dict[int, dict]:
        ds = self.datasets.get("geologic_unit")
        name = ds.config.legend if ds else None
        path = rasters_dir / name if name else None
        if not path or not path.is_file():
            return {}
        return {u["value"]: u for u in json.loads(path.read_text())["units"]}

    def _feature_arrays(self) -> None:
        feats, _ = self.features.query()
        self._feats = feats
        self._flat = np.radians(np.array([f.lat for f in feats])) if feats else np.zeros(0)
        self._flon = np.radians(np.array([f.lon for f in feats])) if feats else np.zeros(0)

    def _distances_km(self, lat: float, lon: float) -> np.ndarray:
        p1, l1 = math.radians(lat), math.radians(lon)
        a = (np.sin((self._flat - p1) / 2) ** 2
             + math.cos(p1) * np.cos(self._flat) * np.sin((self._flon - l1) / 2) ** 2)
        return 2 * self.radius_m / 1000 * np.arcsin(np.sqrt(np.clip(a, 0, 1)))

    def _read(self, ds_id: str, lat: float, lon: float, radius: int = 0) -> tuple[RasterWindow | None, RasterDataset | None]:
        ds = self.datasets.get(ds_id)
        if ds is None or not ds.installed:
            return None, ds
        return ds.source.read(lat, lon, radius), ds

    @staticmethod
    def _missing(item_id: str, label: str, ds: RasterDataset | None, unit: str = "", why: str = "") -> PointItem:
        if ds is None or not ds.installed:
            why = why or "Dataset not installed on this server (run scripts/build_rasters.py)."
        return PointItem(id=item_id, label=label, unit=unit, no_data=True,
                         source=(ds.config.sources[-1].name if ds else ""), notes=why or "No data at this location.")

    # ------------------------------------------------------------------
    def query(self, lat: float, lon: float, ls: float | None = None, tau: float | None = None) -> PointInfo:
        lon = ((lon + 180.0) % 360.0) - 180.0
        now = mars_time()
        ls_used = now.ls if ls is None else ls % 360.0
        tau = DEFAULT_TAU if tau is None else tau
        lst_now = local_true_solar_hours(now, lon)

        location = self._location(lat, lon, ls_used, now.mars_year if ls is None else None, lst_now, ls is None)
        terrain, elevation = self._terrain(lat, lon)
        surface, albedo, inertia = self._surface(lat, lon)
        thermal = self._thermal(lat, lon, ls_used, tau, elevation, albedo, inertia, lst_now if ls is None else None)
        geology = self._geology(lat, lon)
        safety = self._safety(elevation)

        return PointInfo(
            query=PointQueryInfo(
                lat=lat, lon=lon, ls=round(ls_used, 2), ls_source="current" if ls is None else "query",
                mars_year=now.mars_year if ls is None else None, local_solar_time=hhmm(lst_now),
                data_source=self.data_source,
            ),
            sections=[
                PointSection(id="location", title="Location", items=location),
                PointSection(id="terrain", title="Terrain", items=terrain),
                PointSection(id="thermal", title="Thermal & climate", items=thermal),
                PointSection(id="surface", title="Surface & composition", items=surface),
                PointSection(id="geology", title="Geology", items=geology),
                PointSection(id="safety", title="Radiation & safety", items=safety),
            ],
        )

    # ------------------------------------------------------------------
    def _location(self, lat, lon, ls, my, lst_now, is_now) -> list[PointItem]:
        items = [PointItem(
            id="coordinates", label="Coordinates", value=f"{fmt_lat(lat)}, {fmt_lon(lon)}",
            method="Planetocentric latitude, east-positive longitude (-180…180), IAU 2000 / MOLA frame, as in NASA Mars Trek.",
        )]
        if len(self._feats):
            dist = self._distances_km(lat, lon)
            inside, region, nearest, on = None, None, None, None
            for i in np.argsort(dist):
                f = self._feats[i]
                p = f.properties
                d = float(dist[i])
                if p.category in NOT_PLACES:
                    continue
                is_region = p.category in REGION_CATEGORIES
                if nearest is None and not is_region:
                    nearest = (f, d)
                r = (p.diameter_km or 0) / 2
                if r and d <= r:
                    if is_region:
                        if region is None or p.diameter_km < region[0].properties.diameter_km:
                            region = (f, d)
                    elif p.category in EDIFICE_CATEGORIES and d <= EDIFICE_INNER * r:
                        if on is None or p.diameter_km < on[0].properties.diameter_km:
                            on = (f, d)
                    elif p.category in ROUND_CATEGORIES and (
                            inside is None or p.diameter_km < inside[0].properties.diameter_km):
                        inside = (f, d)
            src = "IAU Gazetteer of Planetary Nomenclature (USGS)"
            if inside:
                f, d = inside
                items.append(PointItem(
                    id="inside", label="Inside", value=f"{f.properties.name} ({f.properties.type_label.lower()}, {f.properties.diameter_km:.0f} km)",
                    source=src, notes=f"{d:.0f} km from its centre.",
                    method="Smallest named crater or patera whose circle (IAU centre and diameter) contains the point.",
                ))
            if on:
                f, d = on
                items.append(PointItem(
                    id="on", label="On", value=f"{f.properties.name} ({f.properties.type_label.lower()}, {f.properties.diameter_km:.0f} km)",
                    source=src, notes=f"{d:.0f} km from its centre.",
                    method="Smallest named mons / tholus whose IAU circle (centre, diameter) contains the point well inside (80 % of its radius).",
                ))
            if nearest and all(nearest[0].id != x[0].id for x in (inside, on) if x):
                f, d = nearest
                items.append(PointItem(
                    id="nearest_feature", label="Nearest named feature",
                    value=f"{f.properties.name} ({f.properties.type_label.lower()})", source=src,
                    notes=f"{d:.0f} km to its centre.", method="Great-circle distance to IAU feature centres.",
                ))
            if region:
                f, _ = region
                items.append(PointItem(id="region", label="Region", value=f.properties.name, source=src,
                                       method="Smallest terra / planitia / planum / vastitas / palus whose IAU circle contains the point (approximate: real outlines are not circles)."))
            for cat, label in (("landing_site", "Nearest landing site"), ("exploration_zone", "Nearest exploration zone")):
                idx = [i for i, f in enumerate(self._feats) if f.properties.category == cat]
                if idx:
                    j = min(idx, key=lambda i: dist[i])
                    f = self._feats[j]
                    items.append(PointItem(
                        id=f"nearest_{cat}", label=label, value=f.properties.name.replace("EZ: ", ""),
                        notes=f"{dist[j]:.0f} km away (great-circle).", source=f.properties.source or "",
                    ))
        season = season_name(ls, lat)
        items.append(PointItem(
            id="season", label="Season used for estimates",
            value=f"Ls {ls:.0f}° · {season}" + (f" · Mars Year {my}" if my else ""),
            method=("Solar longitude today on Mars (Allison & McEwen 2000, Mars24 algorithm)." if is_now
                    else "Solar longitude chosen in the request."),
        ))
        items.append(PointItem(id="local_time", label="Local solar time now", value=hhmm(lst_now),
                               method="Local true solar time at this longitude (Mars24 algorithm)."))
        return items

    # ------------------------------------------------------------------
    def _terrain(self, lat, lon) -> tuple[list[PointItem], float | None]:
        win, ds = self._read("elevation", lat, lon, radius=2)
        if win is None:
            return [self._missing("elevation", "Elevation", ds, "m")], None
        src = win.source
        elev = float(win.center)
        res = resolution_text(src.resolution_m)
        live = " (read live over the Internet)" if src.kind == "remote" and "live" not in src.name else ""
        items = [PointItem(
            id="elevation", label="Elevation", value=round(elev), unit="m", source=src.name + live, resolution=res,
            method="Height above the Mars areoid (MOLA datum, the 'sea level' of Mars).",
        )]
        dx, dy = win.pixel_size_m(lat)
        sl = horn_slope(win.data[1:4, 1:4], dx, dy)
        base = f"{3 * src.resolution_m / 1000:.1f} km" if src.resolution_m >= 1000 else f"{3 * src.resolution_m:.0f} m"
        if sl:
            facing = f", facing {compass(sl.aspect_deg)}" if sl.aspect_deg is not None else ""
            items.append(PointItem(
                id="slope", label="Slope", value=round(sl.slope_deg, 1), precision=1, unit="°", source=src.name,
                resolution=res, notes=f"{slope_class(sl.slope_deg).capitalize()}{facing}. Measured over a {base} baseline: local slopes (rocks, crater rims, dunes) can be much steeper.",
                method="Horn (1981) 3×3 finite differences with metric pixel spacing on the Mars sphere.",
            ))
        else:
            items.append(PointItem(id="slope", label="Slope", unit="°", no_data=True, source=src.name,
                                   notes="Not enough valid DEM pixels around the point."))
        rough = detrended_rms(win.data, dx, dy)
        if rough:
            rms, relief = rough
            b5 = f"{5 * src.resolution_m / 1000:.1f} km" if src.resolution_m >= 1000 else f"{5 * src.resolution_m:.0f} m"
            items.append(PointItem(
                id="roughness", label="Roughness (RMS height)", value=round(rms, 1), precision=1, unit="m",
                source=src.name, resolution=res,
                method=f"RMS of the heights after removing the best-fit plane over a 5×5 window ({b5} across).",
                notes=f"Local relief (max − min) in the same window: {relief:.0f} m. Kilometre-scale roughness; boulders are far below this resolution.",
            ))
        return items, elev

    # ------------------------------------------------------------------
    def _surface(self, lat, lon) -> tuple[list[PointItem], float | None, float | None]:
        items: list[PointItem] = []
        albedo = inertia = None
        win, ds = self._read("albedo", lat, lon)
        if win is not None:
            albedo = float(win.center)
            items.append(PointItem(
                id="albedo", label="Albedo", value=round(albedo, 3), precision=3, source=win.source.name,
                resolution=resolution_text(win.source.resolution_m),
                method="Lambert albedo (0.3-2.9 µm), share of sunlight reflected.",
                notes="Bright (>0.25) usually means dust; dark (<0.15) sand or rock."
                + (" 0.32 is the ceiling of this mosaic: the real value may be higher (ice)." if albedo >= 0.319 else ""),
            ))
        else:
            items.append(self._missing("albedo", "Albedo", ds))

        win, ds = self._read("dust_cover_index", lat, lon)
        if win is not None:
            dci = float(win.center)
            meaning = ("little or no dust" if dci >= 0.96 else "some dust" if dci >= 0.94 else "dust-covered")
            items.append(PointItem(
                id="dust_cover_index", label="Dust cover index", value=round(dci, 3), precision=3,
                source=win.source.name, resolution=resolution_text(win.source.resolution_m),
                method="Average TES emissivity at 1350-1400 cm⁻¹; fine dust lowers it.",
                notes=f"{meaning.capitalize()} (≥0.96 dust-free, ≤0.94 dusty; Ruff & Christensen 2002).",
            ))
        else:
            items.append(self._missing("dust_cover_index", "Dust cover index", ds,
                                       why="No TES observation here (polar regions and gaps are not mapped)."))

        win, ds = self._read("minerals", lat, lon)
        if win is not None:
            vals = np.atleast_1d(win.center)
            for name, v in zip(win.band_names, vals):
                items.append(PointItem(
                    id=f"mineral_{name}", label=MINERAL_LABELS.get(name, name), value=round(float(v) * 100, 1),
                    precision=1, unit="%", source=win.source.name, resolution=resolution_text(win.source.resolution_m),
                    method="Areal fraction from deconvolution of atmospherically corrected TES spectra.",
                    notes="Detection limit ~10-15 %: smaller values are not significant." if name != "surface_dust" else
                    "Fraction of the spectrum explained by the dust endmember.",
                ))
        else:
            items.append(self._missing("minerals", "TES mineral abundances", ds,
                                       why="No TES mineral retrieval here (high latitudes and dusty areas are masked)."))
        return items, albedo, inertia

    # ------------------------------------------------------------------
    def _thermal(self, lat, lon, ls, tau, elevation, albedo, inertia, lst_now) -> list[PointItem]:
        items: list[PointItem] = []
        win, ds = self._read("thermal_inertia_night", lat, lon)
        if win is not None:
            inertia = float(win.center)
            kind = ("loose dust" if inertia < 100 else "sand and fine regolith" if inertia < 350
                    else "coarse sand, crusts, rocks" if inertia < 800 else "rock / bedrock or ice")
            items.append(PointItem(
                id="thermal_inertia", label="Thermal inertia (night)", value=round(inertia), unit="J m⁻² K⁻¹ s⁻½",
                source=win.source.name, resolution=resolution_text(win.source.resolution_m),
                method="Fitted to TES night-time surface temperatures with a thermal model (Putzig & Mellon 2007).",
                notes=f"Typical of {kind}. High inertia = surface stays warmer at night.",
            ))
        else:
            items.append(self._missing("thermal_inertia", "Thermal inertia (night)", ds, "J m⁻² K⁻¹ s⁻½"))
        win, ds = self._read("thermal_inertia_day", lat, lon)
        if win is not None:
            items.append(PointItem(
                id="thermal_inertia_day", label="Thermal inertia (day)", value=round(float(win.center)),
                unit="J m⁻² K⁻¹ s⁻½", source=win.source.name, resolution=resolution_text(win.source.resolution_m),
                notes="Differences from the night value hint at layering or mixed surfaces.",
            ))

        pressure = env.surface_pressure_pa(elevation) if elevation is not None else None
        if pressure is not None:
            items.append(PointItem(
                id="pressure", label="Surface pressure (annual mean)", value=round(pressure), unit="Pa", estimate=True,
                source="Model from the elevation above (scale height: NASA Mars Fact Sheet)",
                method=f"P = {env.P0_PA:.0f} Pa × exp(−h / {env.SCALE_HEIGHT_M / 1000:.1f} km), from the elevation.",
                notes="Changes ±10-15 % over the year as CO₂ freezes onto and returns from the polar caps. Earth sea level: 101,325 Pa.",
            ))

        a_used = albedo if albedo is not None else DEFAULT_ALBEDO
        i_used = inertia if inertia is not None else DEFAULT_INERTIA
        p_used = pressure if pressure is not None else env.P0_PA
        tr = surface_temperature(round(lat, 2), round(ls, 1), round(a_used, 3), round(i_used), round(p_used), tau)
        caveats = []
        if albedo is None or inertia is None:
            caveats.append("Missing map values replaced by Mars averages (albedo 0.25, thermal inertia 250).")
        if abs(lat) > 55:
            caveats.append("High latitude: the model has no seasonal memory, so seasonal CO₂ frost (which keeps "
                           "the real surface near the frost point through autumn, winter and early spring) and "
                           "polar ice are not represented.")
        assumptions = (f"Inputs: latitude, Ls {ls:.0f}°, albedo {a_used:.2f}, thermal inertia {i_used:.0f}, "
                       f"pressure {p_used:.0f} Pa, dust opacity τ = {tau}. Flat ground, clear weather." + "".join(" " + c for c in caveats))
        method = ("1-D heat-conduction model of the ground over one sol with the surface energy balance "
                  "(sunlight through dust, CO₂ atmosphere infrared, thermal radiation, CO₂ frost point). "
                  "Error typically ±10-20 K. Not a measurement.")
        model_src = "Arturo 1-D thermal model, inputs from the TES and MOLA maps above"
        series = [SeriesPoint(x=h, y=round(t - 273.15, 1)) for h, t in tr.hourly]
        for key, label, val in (("t_max", "Surface temperature, daytime max", tr.t_max),
                                ("t_min", "Surface temperature, night min", tr.t_min)):
            items.append(PointItem(
                id=key, label=label, value=round(val - 273.15), unit="°C", estimate=True,
                method=method, source=model_src, notes=f"{val:.0f} K. {assumptions}",
                series=series if key == "t_max" else None, series_x="local solar hour" if key == "t_max" else "",
            ))
        if lst_now is not None:
            t_now = tr.at_hour(lst_now)
            items.append(PointItem(
                id="t_now", label="Surface temperature now", value=round(t_now - 273.15), unit="°C", estimate=True,
                source=model_src,
                method="Same model, at the current local solar time.", notes=f"{t_now:.0f} K at {hhmm(lst_now)} local solar time.",
            ))
        items.append(PointItem(
            id="co2_frost_point", label="CO₂ frost point", value=round(tr.frost_point - 273.15), unit="°C", estimate=True,
            source="James et al. 1992 (Mars, Univ. Arizona Press), at the estimated pressure",
            method="James et al. (1992) at the local pressure.",
            notes="Below this the atmosphere itself freezes out as CO₂ frost.",
        ))
        items.append(PointItem(
            id="themis", label="THEMIS day / night IR", no_data=True,
            source="Mars Odyssey THEMIS controlled mosaics (100 m)",
            notes="The THEMIS global mosaics are contrast-stretched images, not calibrated temperatures, so no absolute value can be read from them. Use the map layers to compare places; thermal inertia above is the quantitative product.",
        ))
        return items

    # ------------------------------------------------------------------
    def _geology(self, lat, lon) -> list[PointItem]:
        win, ds = self._read("geologic_unit", lat, lon)
        if win is None:
            return [self._missing("geologic_unit", "Geologic unit", ds)]
        unit = self.geology_units.get(int(win.center))
        if not unit:
            return [self._missing("geologic_unit", "Geologic unit", ds)]
        src = win.source.name
        return [
            PointItem(id="geologic_unit", label="Geologic unit", value=f"{unit['name']} ({unit['code']})", source=src,
                      resolution="1:20,000,000 map; contacts ±5-10 km",
                      method="Unit of the USGS global geologic map at this point."),
            PointItem(id="geologic_age", label="Age", value=geologic_age(unit["code"]), source=src,
                      notes="Noachian > 3.7 Ga, Hesperian ~3.7-3.0 Ga, Amazonian < ~3.0 Ga (approximate)."),
        ]

    # ------------------------------------------------------------------
    def _safety(self, elevation) -> list[PointItem]:
        if elevation is None:
            return [PointItem(id="radiation", label="Radiation (GCR)", no_data=True, notes="Needs the elevation.")]
        p = env.surface_pressure_pa(elevation)
        dose = env.gcr_dose_msv_day(p)
        x = env.column_mass_g_cm2(p)
        items = [
            PointItem(
                id="radiation_dose", label="Radiation dose, cosmic rays", value=round(dose, 2), precision=2,
                unit="mSv/day", estimate=True,
                source="Model anchored to MSL Curiosity RAD (Hassler et al. 2014, Zeitlin et al. 2013)",
                method=(f"D = {env.RAD_TOP_MSV_DAY:.2f} × exp(−x / {env.ATTENUATION_G_CM2:.0f} g/cm²) with x = P/g = "
                        f"{x:.1f} g/cm² of air above you; anchored to Curiosity RAD at Gale (0.67 mSv/day, "
                        "Hassler et al. 2014) and RAD in cruise (1.84 mSv/day, halved for the planet's shadow)."),
                notes="Average for quiet Sun. Uncertainty at least ±50 %; ±30 % over the solar cycle; solar storms not included. Earth average: ~0.008 mSv/day.",
            ),
            PointItem(
                id="radiation_year", label="Dose over one Earth year here", value=round(dose * 365.25), unit="mSv",
                estimate=True, method="Daily dose × 365.25.", source="Same radiation model",
                notes=f"NASA career limit: {env.NASA_CAREER_LIMIT_MSV:.0f} mSv (NASA-STD-3001, 2022), reached after ~{env.NASA_CAREER_LIMIT_MSV / max(dose, 1e-9):,.0f} days unshielded.",
            ),
        ]
        boil = env.water_boiling_point_k(p)
        items.append(PointItem(
            id="water_boiling", label="Water boils at", value=None if boil is None else round(boil - 273.15, 1),
            precision=1, unit="°C", estimate=True, no_data=boil is None,
            source="Clausius-Clapeyron, at the estimated pressure",
            method="Clausius-Clapeyron from water's triple point (611.657 Pa, 0.01 °C) at the estimated pressure.",
            notes=("Pressure is below water's triple point: ice sublimates, liquid water cannot exist." if boil is None
                   else "Liquid water could only exist briefly between 0 °C and this temperature."),
        ))
        items.append(PointItem(
            id="pressure_suit", label="Pressure suit", value="Required", estimate=False,
            source="Armstrong limit (human physiology)",
            notes=f"Pressure ~{p:.0f} Pa is far below the Armstrong limit (6,300 Pa), where body fluids boil at 37 °C.",
        ))
        return items
