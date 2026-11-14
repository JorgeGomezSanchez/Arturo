"""End-to-end tests of the public API contract (what the frontend uses)."""

from __future__ import annotations

import io

from PIL import Image


def test_health_reports_local_mode(client):
    body = client.get("/api/health").json()
    assert body["status"] == "ok"
    assert body["dataSource"] == "local"
    assert body["tileProvider"].startswith("local")


def test_layers_contract(client):
    layers = {l["id"]: l for l in client.get("/api/layers").json()}
    assert set(layers) >= {"viking_mdim21_color", "ctx_global_5m"}

    viking = layers["viking_mdim21_color"]
    # The tile URL ALWAYS points to our backend, never to NASA.
    assert viking["tileUrl"] == "/api/tiles/viking_mdim21_color/{z}/{x}/{y}"
    assert (viking["tileSize"], viking["zoomOffset"], viking["maxNativeZoom"]) == (256, 0, 7)

    ctx = layers["ctx_global_5m"]
    # 512 px tiles: source level N == map zoom N+1
    assert (ctx["tileSize"], ctx["zoomOffset"], ctx["maxNativeZoom"]) == (512, -1, 13)
    # Private source details are never exposed
    assert "source" not in ctx and "urlTemplate" not in str(ctx)


def test_unknown_layer_404(client):
    assert client.get("/api/layers/nope").status_code == 404
    assert client.get("/api/tiles/nope/0/0/0").status_code == 404


def test_tile_from_local_pack(client):
    r = client.get("/api/tiles/viking_mdim21_color/0/1/0")
    assert r.status_code == 200
    assert r.headers["content-type"] == "image/jpeg"
    assert r.headers["x-tile-origin"] == "local"


def test_tile_missing_or_off_grid_is_404(client):
    assert client.get("/api/tiles/viking_mdim21_color/0/0/0").status_code == 404  # not in pack
    assert client.get("/api/tiles/viking_mdim21_color/0/2/0").status_code == 404  # x out of grid
    assert client.get("/api/tiles/viking_mdim21_color/8/0/0").status_code == 404  # above max level


def test_ctx_nodata_becomes_transparent(client):
    r = client.get("/api/tiles/ctx_global_5m/3/4/2")
    assert r.status_code == 200 and r.headers["content-type"] == "image/png"
    img = Image.open(io.BytesIO(r.content))
    assert img.mode in ("LA", "RGBA")
    assert img.getpixel((10, 10))[-1] == 0      # black gap -> transparent
    assert img.getpixel((400, 400))[-1] == 255  # data -> opaque


def test_map_and_zones(client):
    m = client.get("/api/map").json()
    assert m["crs"] == "EPSG4326" and m["body"] == "Mars"
    zones = {z["id"]: z for z in client.get("/api/zones").json()}
    assert "gale" in zones and zones["gale"]["center"]["lat"] < 0


def test_root_is_an_api_index(client):
    body = client.get("/").json()
    assert body["docs"] == "/docs" and body["api"] == "/api"


def test_map_exposes_label_credits(client):
    credits = client.get("/api/map").json()["labelCredits"]
    assert set(credits) == {"names", "landing_site", "exploration_zone"}
    assert "IAU" in credits["names"]
