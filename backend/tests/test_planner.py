"""Automatic route planning on a synthetic ridge with one pass.

Fixture DEM (0.01° pixels, ~593 m): a north-south ridge along 0.5° E with
40° flanks (impassable on foot: > 25°), interrupted by a flat pass
between 0.10° and 0.18° N. A route from 0.2° E to 0.8° E along the
equator must go through the pass. Offline; nothing committed is used."""

from __future__ import annotations

import importlib
import math
from pathlib import Path

import numpy as np
import pytest
import rasterio
from fastapi.testclient import TestClient
from rasterio.transform import from_origin

from app.rasters.base import MARS_RADIUS_M
from app.services.route_planner import SkimageMcpPlanner, speed_factor

PPD = 100
DEG_M = MARS_RADIUS_M * math.pi / 180
RIDGE_LON, RIDGE_HALF = 0.5, 0.03  # degrees
PASS = (0.10, 0.18)  # latitudes of the gap in the ridge
A, B = [0.2, 0.0], [0.8, 0.0]


def ridge_dem() -> np.ndarray:
    lons = (np.arange(PPD) + 0.5) / PPD
    lats = 0.5 - (np.arange(PPD) + 0.5) / PPD
    h = np.maximum(0.0, (RIDGE_HALF - np.abs(lons - RIDGE_LON)) * DEG_M * math.tan(math.radians(40)))
    z = np.tile(h, (PPD, 1))
    z[(lats > PASS[0]) & (lats < PASS[1]), :] = 0.0
    return z.astype(np.float32)


@pytest.fixture
def client(tmp_path: Path, tiles_dir: Path, monkeypatch: pytest.MonkeyPatch):
    rasters = tmp_path / "rasters"
    rasters.mkdir()
    with rasterio.open(rasters / "dem.tif", "w", driver="GTiff", width=PPD, height=PPD, count=1, dtype="float32",
                       crs="+proj=longlat +R=3396190 +no_defs", transform=from_origin(0, 0.5, 1 / PPD, 1 / PPD),
                       nodata=-99999.0) as dst:
        dst.write(ridge_dem(), 1)
    catalog = tmp_path / "rasters.yaml"
    catalog.write_text(
        "datasets:\n  elevation:\n    title: Elevation\n    sources:\n"
        "      - id: fixture_dem\n        kind: local\n        path: dem.tif\n"
        "        name: Fixture ridge DEM\n        resolution_m: 593\n"
    )
    feats = tmp_path / "features"
    feats.mkdir()
    for k, v in {"DATA_SOURCE": "local", "LOCAL_TILES_DIR": str(tiles_dir), "RASTERS_DIR": str(rasters),
                 "RASTERS_FILE": str(catalog), "FEATURES_DIR": str(feats), "POI_STORE": "memory",
                 "ROUTE_STORE": "memory"}.items():
        monkeypatch.setenv(k, v)
    from app.catalog import map_config, registry, routes_config
    from app.core import config

    config.get_settings.cache_clear()
    registry.get_registry.cache_clear()
    map_config._raw.cache_clear()
    routes_config.load_routes_config.cache_clear()
    import app.main

    importlib.reload(app.main)
    with TestClient(app.main.app) as c:
        yield c
    config.get_settings.cache_clear()
    routes_config.load_routes_config.cache_clear()


def plan(client, body, status=200):
    r = client.post("/api/routes/plan", json=body)
    assert r.status_code == status, r.text
    return r.json()


def lat_at_lon(coords, lon):
    for (x0, y0), (x1, y1) in zip(coords, coords[1:]):
        if (x0 - lon) * (x1 - lon) <= 0 and x0 != x1:
            return y0 + (y1 - y0) * (lon - x0) / (x1 - x0)
    return None


def test_plan_goes_through_the_pass(client):
    body = {"start": A, "end": B, "mode": "walking", "weights": {"marginFraction": 0.5}}
    res = plan(client, body)
    straight = res["straight"]
    assert straight["maxSeverity"] == "danger" and straight["maxSlopeDeg"] > 25  # straight over the ridge

    wps = res["waypoints"]
    assert 1 <= len(wps) <= 25
    line = [A, *wps, B]
    crossing = lat_at_lon(line, RIDGE_LON)
    assert PASS[0] < crossing < PASS[1], (crossing, wps)

    a = res["analysis"]
    assert a["vertices"] == [pytest.approx(v) for v in line]
    assert a["maxSlopeDeg"] < 25
    assert not any(h["type"] == "slope" and h["severity"] == "danger" for h in a["hazards"])
    assert a["distanceM"] > straight["distanceM"]

    info = res["info"]
    assert info["planner"].startswith("scikit-image")
    assert info["resolutionM"] == pytest.approx(593) and info["coarsened"] == 1
    assert "Fixture ridge DEM" in info["data"]
    assert 0 < info["excludedShare"] < 0.5
    assert info["pathCells"] > len(wps) + 1
    assert set(info["timingsMs"]) == {"grid", "search", "simplify", "analysis"}


def test_planned_route_saves_as_a_normal_route(client):
    res = plan(client, {"start": A, "end": B, "weights": {"marginFraction": 0.5}})
    body = {"name": "Through the pass", "start": {"kind": "point", "lat": A[1], "lon": A[0]},
            "end": {"kind": "point", "lat": B[1], "lon": B[0]}, "waypoints": res["waypoints"]}
    r = client.post("/api/routes", json=body)
    assert r.status_code == 201
    assert r.json()["properties"]["stats"]["maxSlopeDeg"] < 25


def test_no_path_when_the_pass_is_outside_the_search_area(client):
    err = plan(client, {"start": A, "end": B, "weights": {"marginFraction": 0.05}}, 422)["detail"]
    assert err["reason"] == "no_path"
    assert "slopes ≥ 25°" in err["message"]
    assert err["reachableTouchesEdge"] is True
    assert err["gapM"] > 0 and err["closestReachable"][0] < RIDGE_LON


def test_rover_and_walking_both_avoid_the_ridge(client):
    for mode in ("walking", "rover"):
        res = plan(client, {"start": A, "end": B, "mode": mode, "weights": {"marginFraction": 0.5}})
        assert res["analysis"]["mode"] == mode
        assert PASS[0] < lat_at_lon([A, *res["waypoints"], B], RIDGE_LON) < PASS[1]


def test_blocked_ends_and_limits(client):
    on_flank = [RIDGE_LON - 0.015, -0.3]  # on the 40° flank
    err = plan(client, {"start": on_flank, "end": B}, 422)["detail"]
    assert err["reason"] == "a_blocked" and err["slopeDeg"] > 25
    err = plan(client, {"start": A, "end": on_flank}, 422)["detail"]
    assert err["reason"] == "b_blocked"
    assert plan(client, {"start": [170, 0], "end": [-170, 0]}, 422)["detail"]["reason"] == "antimeridian"
    assert plan(client, {"start": [0, 0], "end": [60, 0]}, 422)["detail"]["reason"] == "too_long"
    assert plan(client, {"start": [0, 79.95], "end": [0.5, 79.99]}, 422)["detail"]["reason"] == "polar"
    assert plan(client, {"start": A, "end": A}, 422)["detail"]["reason"] == "same_point"
    assert plan(client, {"start": A, "end": B, "mode": "jetpack"}, 422)["detail"]["reason"] == "unknown_mode"
    assert client.post("/api/routes/plan", json={"start": A, "end": B, "weights": {"difficultMultiplier": 0}}
                       ).status_code == 422


def test_large_areas_are_coarsened_and_flat_ground_stays_straight(client):
    client.app.state.route_analyzer.config.planning.max_cells = 300
    res = plan(client, {"start": [0.05, -0.3], "end": [0.35, -0.3]})
    assert res["info"]["coarsened"] > 1 and res["info"]["resolutionM"] > 593
    assert any("coarsened" in n for n in res["info"]["notes"])
    assert res["waypoints"] == []  # flat: the straight line is the best path


def test_skimage_planner_and_cost_model():
    cost = np.ones((5, 5))
    cost[:4, 2] = np.inf  # a wall with a gap at the bottom row
    path, cum = SkimageMcpPlanner().search(cost, (0, 0), (0, 4), (1.0, 1.0))
    assert path is not None and (4, 2) in [tuple(c) for c in path.cells]
    assert path.cumulative[0] == 0 and path.total == pytest.approx(cum[0, 4])
    cost[4, 2] = np.inf
    path, cum = SkimageMcpPlanner().search(cost, (0, 0), (0, 4), (1.0, 1.0))
    assert path is None and np.isinf(cum[0, 4]) and np.isfinite(cum[4, 0])

    class Mode:
        speed_model = "tobler"

    f = speed_factor(np.array([0.0, 10.0, 20.0]), Mode)
    assert f[0] == pytest.approx(1.0) and f[1] == pytest.approx(math.exp(-3.5 * math.tan(math.radians(10))))
    assert f[0] > f[1] > f[2]
