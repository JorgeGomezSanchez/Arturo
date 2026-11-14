"""GET /api/point and the models behind it. Offline: tiny fixture
GeoTIFFs written into a temp folder (no committed data, no network)."""

from __future__ import annotations

import importlib
import math
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pytest
import rasterio
from fastapi.testclient import TestClient
from rasterio.transform import from_origin

from app.rasters.base import MARS_RADIUS_M, SourceInfo
from app.rasters.geotiff import GeoTiffRasterSource, LayeredRasterSource
from app.services import environment as env
from app.services.mars_time import local_true_solar_hours, mars_time
from app.services.terrain import detrended_rms, horn_slope
from app.services.thermal import co2_frost_point, surface_temperature

RISE_PER_PX = 2000.0  # fixture DEM rises 2 km per 1° pixel towards the east


def write_tif(path: Path, data: np.ndarray, ppd: float, nodata) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(
        path, "w", driver="GTiff", width=data.shape[1], height=data.shape[0], count=1, dtype=data.dtype,
        crs="+proj=longlat +R=3396190 +no_defs", transform=from_origin(-180, 90, 1 / ppd, 1 / ppd), nodata=nodata,
    ) as dst:
        dst.write(data, 1)


@pytest.fixture
def rasters_dir(tmp_path: Path) -> Path:
    root = tmp_path / "rasters"
    cols = np.arange(360, dtype=np.float32)
    elev = np.tile(cols * RISE_PER_PX - 360_000, (180, 1)).astype(np.float32)
    write_tif(root / "mola_megdr_16ppd_elevation.tif", elev, 1, -99999.0)
    # Albedo only covers the southern hemisphere: north = no data.
    alb = np.full((180, 360), 65535, np.uint16)
    alb[90:, :] = 2500  # 0.25 with scale 1e-4
    write_tif(root / "tes_albedo_8ppd.tif", alb, 1, 65535)
    return root


@pytest.fixture
def point_client(tiles_dir: Path, rasters_dir: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("DATA_SOURCE", "local")
    monkeypatch.setenv("LOCAL_TILES_DIR", str(tiles_dir))
    monkeypatch.setenv("RASTERS_DIR", str(rasters_dir))
    monkeypatch.setenv("POI_STORE", "memory")
    from app.catalog import map_config, registry
    from app.core import config

    config.get_settings.cache_clear()
    registry.get_registry.cache_clear()
    map_config._raw.cache_clear()
    import app.main

    importlib.reload(app.main)
    with TestClient(app.main.app) as c:
        yield c
    config.get_settings.cache_clear()


def items(body: dict) -> dict[str, dict]:
    return {i["id"]: i for s in body["sections"] for i in s["items"]}


# ---------------------------------------------------------------- API
def test_point_shape_and_units(point_client):
    r = point_client.get("/api/point", params={"lat": -10, "lon": 20.5})
    assert r.status_code == 200
    body = r.json()
    assert [s["id"] for s in body["sections"]] == ["location", "terrain", "thermal", "surface", "geology", "safety"]
    assert body["query"]["lsSource"] == "current"
    assert 0 <= body["query"]["ls"] < 360
    it = items(body)
    for item in it.values():  # every item carries the generic fields
        assert {"value", "unit", "source", "resolution", "method", "notes", "noData", "estimate"} <= item.keys()
    elev = it["elevation"]
    assert elev["unit"] == "m" and elev["noData"] is False
    assert elev["value"] == pytest.approx(200 * RISE_PER_PX - 360_000, abs=1)
    assert "MOLA" in elev["source"] and elev["resolution"]
    assert it["pressure"]["estimate"] is True
    assert it["albedo"]["value"] == pytest.approx(0.25)
    assert it["t_max"]["estimate"] and it["t_max"]["series"]


def test_point_slope_on_tilted_plane(point_client):
    for lat in (0.5, 60.5):
        it = items(point_client.get("/api/point", params={"lat": lat, "lon": 20.5}).json())
        dx = MARS_RADIUS_M * math.radians(1) * math.cos(math.radians(lat))
        expected = math.degrees(math.atan(RISE_PER_PX / dx))
        assert it["slope"]["value"] == pytest.approx(expected, abs=0.1)
        assert "facing W" in it["slope"]["notes"]  # rises to the east -> faces west
        assert it["roughness"]["value"] == pytest.approx(0, abs=0.1)  # a plane is perfectly smooth


def test_point_no_data_outside_coverage_and_missing_datasets(point_client):
    it = items(point_client.get("/api/point", params={"lat": 30.5, "lon": 0.5}).json())
    assert it["albedo"]["noData"] is True and it["albedo"]["value"] is None
    # Datasets not installed in the fixture folder are reported, not crashed on.
    assert it["thermal_inertia"]["noData"] is True
    assert "build_rasters" in it["thermal_inertia"]["notes"]
    assert it["geologic_unit"]["noData"] is True
    assert it["themis"]["noData"] is True
    # The temperature model still runs with Mars-average inputs.
    assert it["t_max"]["value"] is not None and "Mars averages" in it["t_max"]["notes"]


def test_point_query_ls_and_validation(point_client):
    body = point_client.get("/api/point", params={"lat": -4.6, "lon": 137.4, "ls": 270}).json()
    assert body["query"]["ls"] == 270 and body["query"]["lsSource"] == "query"
    assert "t_now" not in items(body)  # "now" only makes sense for today's Ls
    assert point_client.get("/api/point", params={"lat": 91, "lon": 0}).status_code == 422
    assert point_client.get("/api/point", params={"lat": 0, "lon": 0, "ls": 400}).status_code == 422
    # Longitudes are wrapped to -180..180
    assert point_client.get("/api/point", params={"lat": 0, "lon": 200}).json()["query"]["lon"] == pytest.approx(-160)


def test_health_reports_point_rasters(point_client):
    assert "local GeoTIFF" in point_client.get("/api/health").json()["pointRaster"]


# ---------------------------------------------------------- raster layer
def test_window_padding_and_layering(rasters_dir):
    info = SourceInfo("a", "A", 3705, "local")
    src = GeoTiffRasterSource(str(rasters_dir / "tes_albedo_8ppd.tif"), info, scale=1e-4)
    win = src.read(-89.9, 179.9, radius=2)  # corner: window padded with NaN
    assert win.data.shape == (5, 5)
    assert np.isnan(win.data[0, 4]) and win.center == pytest.approx(0.25)
    assert np.isnan(src.read(45, 0).center)  # nodata pixels come back as NaN
    layered = LayeredRasterSource([src])  # ...and the layer treats NaN as 'not covered'
    assert layered.read(45, 0) is None and layered.read(-45, 0) is not None
    src.close()


# ----------------------------------------------------------- formulas
def test_pressure_and_boiling():
    assert env.surface_pressure_pa(0) == pytest.approx(610)
    assert 80 < env.surface_pressure_pa(21_200) < 100  # Olympus Mons summit
    assert 1100 < env.surface_pressure_pa(-7_000) < 1250  # Hellas floor
    assert env.water_boiling_point_k(500) is None  # below the triple point
    assert env.water_boiling_point_k(env.TRIPLE_P * 1.0001) == pytest.approx(273.16, abs=0.05)
    assert 278 < env.water_boiling_point_k(1160) < 285  # ~9 °C in Hellas
    assert env.water_boiling_point_k(101_325) == pytest.approx(373, abs=4)  # sanity on Earth


def test_radiation_anchored_to_curiosity():
    p_gale = env.surface_pressure_pa(env.CURIOSITY_ELEVATION_M)
    assert env.gcr_dose_msv_day(p_gale) == pytest.approx(0.67, abs=1e-6)
    assert env.gcr_dose_msv_day(0) == pytest.approx(0.92)
    assert env.gcr_dose_msv_day(env.surface_pressure_pa(21_000)) > env.gcr_dose_msv_day(p_gale)


def test_horn_slope_and_roughness():
    dx = dy = 100.0
    z = np.array([[0, 10, 20]] * 3, dtype=float)  # rises 10 m per 100 m eastwards
    s = horn_slope(z, dx, dy)
    assert s.slope_deg == pytest.approx(math.degrees(math.atan(0.1)))
    assert s.aspect_deg == pytest.approx(270)
    north = horn_slope(np.array([[20] * 3, [10] * 3, [0] * 3], dtype=float), dx, dy)
    assert north.aspect_deg == pytest.approx(180)  # rises north -> faces south
    assert horn_slope(np.full((3, 3), np.nan), dx, dy) is None
    rms, relief = detrended_rms(np.add.outer(np.arange(5.0), np.arange(5.0)) * 3, dx, dy)
    assert rms == pytest.approx(0, abs=1e-9) and relief == 24


def test_mars_time_reference_epoch():
    # Mars24 worked example (Allison & McEwen 2000): 2000-01-06 00:00 UTC
    t = mars_time(datetime(2000, 1, 6, tzinfo=timezone.utc))
    assert t.ls == pytest.approx(277.187, abs=0.05)
    assert t.mars_year == 24
    assert t.mtc_hours == pytest.approx(23.99, abs=0.05)
    assert 0 <= local_true_solar_hours(t, 137.4) < 24


def test_thermal_model_ranges():
    gale = surface_temperature(-4.6, 270, 0.23, 390, 915)
    assert 255 < gale.t_max < 295 and 180 < gale.t_min < 205  # REMS-like
    assert gale.t_min < gale.t_mean < gale.t_max
    dusty = surface_temperature(0, 0, 0.28, 60, 300)  # low inertia: wider swing
    assert dusty.t_max - dusty.t_min > gale.t_max - gale.t_min
    winter = surface_temperature(-85, 90, 0.35, 300, 600)  # south polar night
    assert winter.t_max == pytest.approx(co2_frost_point(600), abs=0.5)
    assert 140 < co2_frost_point(610) < 150
