"""Routes: analyser (on a synthetic slope ramp), storage and API.

Offline: fixture GeoTIFF, raster catalog and feature file are written to
a temp folder; nothing committed is used and no network is touched."""

from __future__ import annotations

import importlib
import json
import math
from pathlib import Path

import numpy as np
import pytest
import rasterio
from fastapi.testclient import TestClient
from rasterio.transform import from_origin

from app.models.route import RouteEnd, RouteInput
from app.rasters.base import MARS_RADIUS_M
from app.repositories.routes import JsonFileRouteRepository, MemoryRouteRepository, RouteNotFoundError
from app.services.geodesy import densify, haversine_m
from app.services.route_analysis import runs

PPD = 100  # fixture DEM: 0.01° pixels (~593 m)
DEG_M = MARS_RADIUS_M * math.pi / 180  # metres per degree on the equator
RAMP = (0.40, 0.50)  # 30° ramp between these longitudes, flat elsewhere
RAMP_DEG = 30.0
START, END = 0.05, 0.95  # route along the equator
CRATER = (0.75, 10.0)  # lon, diameter km (centre on the equator)


def ramp_dem() -> np.ndarray:
    lons = (np.arange(PPD) + 0.5) / PPD  # 0..1 degrees east
    rise = np.clip((lons - RAMP[0]) / (RAMP[1] - RAMP[0]), 0, 1) * (RAMP[1] - RAMP[0]) * DEG_M * math.tan(
        math.radians(RAMP_DEG))
    return np.tile(rise.astype(np.float32), (PPD, 1))  # lat +0.5 .. -0.5


@pytest.fixture
def route_env(tmp_path: Path, tiles_dir: Path, monkeypatch: pytest.MonkeyPatch):
    rasters = tmp_path / "rasters"
    rasters.mkdir()
    with rasterio.open(rasters / "dem.tif", "w", driver="GTiff", width=PPD, height=PPD, count=1, dtype="float32",
                       crs="+proj=longlat +R=3396190 +no_defs", transform=from_origin(0, 0.5, 1 / PPD, 1 / PPD),
                       nodata=-99999.0) as dst:
        dst.write(ramp_dem(), 1)
    catalog = tmp_path / "rasters.yaml"
    catalog.write_text(
        "datasets:\n  elevation:\n    title: Elevation\n    sources:\n"
        "      - id: fixture_dem\n        kind: local\n        path: dem.tif\n"
        "        name: Fixture ramp DEM\n        resolution_m: 593\n"
    )
    feats = tmp_path / "features"
    feats.mkdir()
    (feats / "craters.geojson").write_text(json.dumps({"type": "FeatureCollection", "features": [{
        "type": "Feature", "id": "c1", "geometry": {"type": "Point", "coordinates": [CRATER[0], 0.0]},
        "properties": {"name": "Testcrater", "category": "crater", "typeLabel": "Crater", "diameterKm": CRATER[1]},
    }]}))
    monkeypatch.setenv("DATA_SOURCE", "local")
    monkeypatch.setenv("LOCAL_TILES_DIR", str(tiles_dir))
    monkeypatch.setenv("RASTERS_DIR", str(rasters))
    monkeypatch.setenv("RASTERS_FILE", str(catalog))
    monkeypatch.setenv("FEATURES_DIR", str(feats))
    monkeypatch.setenv("POI_STORE", "memory")
    monkeypatch.setenv("ROUTE_STORE", "json")
    monkeypatch.setenv("ROUTE_STORE_FILE", str(tmp_path / "routes.json"))
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


def analyze(client, coords, mode="walking", **kw):
    r = client.post("/api/routes/analyze", json={"coordinates": coords, "mode": mode, **kw})
    assert r.status_code == 200, r.text
    return r.json()


# ------------------------------------------------------------ analyser
def test_ramp_hazard_at_the_right_distance(route_env):
    a = analyze(route_env, [[START, 0.0], [END, 0.0]])
    assert a["distanceM"] == pytest.approx((END - START) * DEG_M, rel=1e-6)
    assert a["sampleSpacingM"] == pytest.approx(593, rel=0.05)  # spacing follows the DEM resolution
    assert "Fixture ramp DEM" in a["resolution"]
    rise = (RAMP[1] - RAMP[0]) * DEG_M * math.tan(math.radians(RAMP_DEG))
    assert a["gainM"] == pytest.approx(rise, rel=0.02) and a["lossM"] == pytest.approx(0, abs=1)
    assert a["maxSlopeDeg"] == pytest.approx(RAMP_DEG, abs=1.0)

    slopes = [h for h in a["hazards"] if h["type"] == "slope"]
    assert len(slopes) == 1 and slopes[0]["severity"] == "danger"  # 30° > 25° impassable
    expect_from, expect_to = (RAMP[0] - START) * DEG_M, (RAMP[1] - START) * DEG_M
    tol = 2 * 593  # Horn's 3x3 stencil smears the edges by about one pixel each side
    assert slopes[0]["fromM"] == pytest.approx(expect_from, abs=tol)
    assert slopes[0]["toM"] == pytest.approx(expect_to, abs=tol)
    assert expect_from - tol <= (slopes[0]["lon"] - START) * DEG_M <= expect_to + tol

    # Coloured segments: red exactly around the ramp, green elsewhere.
    red = [s for s in a["segments"] if s["level"] == "danger"]
    assert red and red[0]["fromM"] == pytest.approx(expect_from, abs=tol)
    assert a["segments"][0]["level"] == "ok" and a["segments"][-1]["level"] == "ok"
    assert a["maxSeverity"] == "danger" and a["hazardCounts"]["danger"] >= 1
    # Profile is monotonic distance and carries the levels.
    d = [p["d"] for p in a["profile"]]
    assert d == sorted(d) and d[-1] == pytest.approx(a["distanceM"])


def test_crater_rims_and_no_data(route_env):
    a = analyze(route_env, [[START, 0.0], [1.2, 0.0]])  # runs off the fixture DEM east of 1.0°
    rims = sorted(h["fromM"] for h in a["hazards"] if h["type"] == "crater_rim")
    r_deg = CRATER[1] / 2 * 1000 / DEG_M
    assert len(rims) == 2
    assert rims[0] == pytest.approx((CRATER[0] - r_deg - START) * DEG_M, abs=1500)
    assert rims[1] == pytest.approx((CRATER[0] + r_deg - START) * DEG_M, abs=1500)
    nd = [h for h in a["hazards"] if h["type"] == "no_data"]
    assert len(nd) == 1 and nd[0]["fromM"] == pytest.approx((1.0 - START) * DEG_M, abs=2 * 593)
    assert any(s["noData"] for s in a["segments"])


def test_modes_change_speed_and_rules(route_env):
    walk = analyze(route_env, [[START, 0.0], [0.3, 0.0]], "walking")
    rover = analyze(route_env, [[START, 0.0], [0.3, 0.0]], "rover")
    assert rover["durationH"] < walk["durationH"]
    assert walk["durationH"] == pytest.approx(walk["distanceM"] / 1000 / 2.0, rel=0.02)  # flat: 2 km/h
    assert walk["doseMsv"] > rover["doseMsv"] > 0
    assert rover["modeLabel"] and walk["mode"] == "walking"


def test_analyze_validation(route_env):
    assert route_env.post("/api/routes/analyze", json={"coordinates": [[0, 0]]}).status_code == 422
    assert route_env.post("/api/routes/analyze", json={"coordinates": [[0.1, 0], [0.1, 0]]}).status_code == 422
    r = route_env.post("/api/routes/analyze", json={"coordinates": [[0.1, 0], [0.2, 0]], "mode": "jetpack"})
    assert r.status_code == 422 and "jetpack" in r.text
    cfg = route_env.get("/api/routes/config").json()
    assert {"walking", "rover"} <= set(cfg["modes"]) and cfg["modes"]["walking"]["slope"]["impassableDeg"] == 25


def test_runs_and_geodesy():
    assert runs(np.array([0, 1, 1, 0, 1, 0, 0, 0, 1], bool)) == [(1, 4), (8, 8)]
    assert runs(np.zeros(3, bool)) == []
    lat, lon, d, vd = densify([(0, 0), (90, 0)], 100_000)
    assert d[-1] == pytest.approx(MARS_RADIUS_M * math.pi / 2)
    assert np.allclose(lat, 0) and lon[-1] == pytest.approx(90)
    # A long east-west leg at 60° N bows towards the pole (great circle).
    lat, lon, _, _ = densify([(-60, 60), (60, 60)], 50_000)
    assert lat.max() > 65
    assert haversine_m(0, 0, 0, 1) == pytest.approx(DEG_M)


# ------------------------------------------------------------ storage
def make_input(**kw) -> RouteInput:
    base = dict(name="Test", start=RouteEnd(kind="point", lat=0, lon=0.1), end=RouteEnd(kind="poi", ref_id="p1",
                name="Camp", lat=0, lon=0.3), waypoints=[(0.2, 0.05)], created_zoom=9)
    base.update(kw)
    return RouteInput(**base)


def test_memory_and_json_repositories(tmp_path):
    mem = MemoryRouteRepository()
    r = mem.create(make_input())
    assert mem.get(r.id).name == "Test" and len(mem.list()) == 1
    mem.update(r.id, make_input(name="Renamed"))
    assert mem.get(r.id).name == "Renamed"
    mem.delete(r.id)
    with pytest.raises(RouteNotFoundError):
        mem.get(r.id)

    path = tmp_path / "routes.json"
    repo = JsonFileRouteRepository(path)
    r = repo.create(make_input())
    again = JsonFileRouteRepository(path)  # survives a restart
    got = again.get(r.id)
    assert got.coordinates() == [(0.1, 0.0), (0.2, 0.05), (0.3, 0.0)]
    assert got.end.ref_id == "p1" and got.end.kind == "poi"


# ------------------------------------------------------------ API
def test_routes_crud_contract(route_env):
    body = {
        "name": "  Across the ramp ", "notes": "test", "mode": "walking", "createdZoom": 9,
        "start": {"kind": "point", "lat": 0, "lon": START},
        "end": {"kind": "feature", "refId": "c1", "name": "Testcrater", "lat": 0, "lon": 0.6},
        "waypoints": [],
    }
    r = route_env.post("/api/routes", json=body)
    assert r.status_code == 201, r.text
    f = r.json()
    rid = f["id"]
    assert f["type"] == "Feature" and f["geometry"]["type"] == "LineString"
    assert f["geometry"]["coordinates"] == [[START, 0], [0.6, 0]]
    p = f["properties"]
    assert p["name"] == "Across the ramp" and p["end"]["refId"] == "c1"
    st = p["stats"]
    assert st["maxSeverity"] == "danger" and st["distanceM"] == pytest.approx((0.6 - START) * DEG_M, rel=1e-6)
    assert route_env.get("/api/routes").json()["features"][0]["id"] == rid

    # Edit: a detour through a waypoint re-analyses the route
    body["waypoints"] = [[0.3, 0.2]]
    body["name"] = "Detour"
    u = route_env.put(f"/api/routes/{rid}", json=body).json()
    assert len(u["geometry"]["coordinates"]) == 3 and u["properties"]["name"] == "Detour"
    assert u["properties"]["stats"]["distanceM"] > st["distanceM"]
    a = route_env.get(f"/api/routes/{rid}/analysis").json()
    assert a["vertexDistancesM"][-1] == pytest.approx(u["properties"]["stats"]["distanceM"], rel=1e-6)

    assert route_env.get("/api/health").json()["routeStore"].startswith("json")
    assert route_env.delete(f"/api/routes/{rid}").status_code == 204
    assert route_env.get(f"/api/routes/{rid}").status_code == 404
    assert route_env.put(f"/api/routes/{rid}", json=body).status_code == 404
    assert route_env.delete(f"/api/routes/{rid}").status_code == 404
    bad = dict(body, name="  ")
    assert route_env.post("/api/routes", json=bad).status_code == 422
