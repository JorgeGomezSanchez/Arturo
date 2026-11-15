"""End-to-end tests of the public API contract (what the frontend uses)."""

from __future__ import annotations

import io
import struct

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


def test_unreadable_ctx_tile_is_404_not_500(client, tiles_dir):
    # Signature looks like a PNG but the payload is junk: still a 404, not a 500.
    (tiles_dir / "ctx_global_5m" / "3" / "4" / "3.png").write_bytes(
        b"\x89PNG\r\n\x1a\n" + b"this is not a PNG"
    )
    assert client.get("/api/tiles/ctx_global_5m/3/4/3").status_code == 404


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


def _truncate_png(data: bytes) -> bytes:
    """Drop IEND and cut the last IDAT so the file is incomplete."""
    pos = 8
    out = data[:8]
    last_idat_at = None
    while pos + 8 <= len(data):
        length = struct.unpack(">I", data[pos:pos + 4])[0]
        ctype = data[pos + 4:pos + 8]
        end = pos + 8 + length + 4
        if ctype == b"IEND":
            break
        if ctype == b"IDAT":
            last_idat_at = len(out)
        out += data[pos:end]
        pos = end
    if last_idat_at is None:
        return out[: max(len(out) // 2, 16)]
    last_len = struct.unpack(">I", out[last_idat_at:last_idat_at + 4])[0]
    return out[: last_idat_at + 8 + max(last_len // 2, 1)]


def test_truncated_tile_is_filled_from_parent(client, tiles_dir):
    """A truncated CTX tile is repaired with the parent and served as 200.

    Parent 4/0/0 has a distinctive bottom-right quadrant (value 180).
    Child 5/1/1 is that quadrant; its PNG is cut short so only the top
    rows decode. The response must keep those native rows and fill the
    rest from the upscaled parent (180), then make no-data transparent
    only where pixels are actually 0.
    """
    parent = Image.new("L", (512, 512), 80)
    parent.paste(180, (256, 256, 512, 512))
    parent_dir = tiles_dir / "ctx_global_5m" / "4" / "0"
    parent_dir.mkdir(parents=True)
    parent.save(parent_dir / "0.png")

    # Weakly compressible so cutting the last IDAT drops many rows.
    child = Image.new("L", (512, 512))
    pix = child.load()
    for y in range(512):
        for x in range(512):
            pix[x, y] = 40 + ((x + y * 3) % 80)
    buf = io.BytesIO()
    child.save(buf, format="PNG")
    child_dir = tiles_dir / "ctx_global_5m" / "5" / "1"
    child_dir.mkdir(parents=True)
    (child_dir / "1.png").write_bytes(_truncate_png(buf.getvalue()))

    r = client.get("/api/tiles/ctx_global_5m/5/1/1")
    assert r.status_code == 200, r.text
    img = Image.open(io.BytesIO(r.content))
    img.load()
    # Re-encoded, well-formed PNG the browser can display.
    assert img.format == "PNG"
    # Top: recovered native data (around 40-119), not the parent fill.
    top = img.convert("L").getpixel((256, 4))
    assert 40 <= top <= 119, top
    # Bottom: filled from the parent's SE quadrant (180). Alpha is opaque
    # because 180 is not nodata.
    bottom = img.convert("LA").getpixel((256, 500))
    assert abs(bottom[0] - 180) <= 5, bottom
    assert bottom[1] == 255
    assert r.headers["x-tile-origin"].endswith("+parent")


def test_missing_tile_is_synthesized_from_parent(client, tiles_dir):
    """A tile that is not in the pack is upscaled from its parent (200)."""
    parent = Image.new("L", (512, 512), 90)
    parent.paste(150, (0, 0, 256, 256))  # NW quadrant
    parent_dir = tiles_dir / "ctx_global_5m" / "4" / "0"
    parent_dir.mkdir(parents=True)
    parent.save(parent_dir / "0.png")

    r = client.get("/api/tiles/ctx_global_5m/5/0/0")
    assert r.status_code == 200
    img = Image.open(io.BytesIO(r.content))
    img.load()
    # Child 5/0/0 is the NW quadrant of 4/0/0, so ~150.
    value = img.convert("L").getpixel((256, 256))
    assert abs(value - 150) <= 5, value
