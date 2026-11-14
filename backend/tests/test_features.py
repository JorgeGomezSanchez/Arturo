"""Named features: display rules, bbox wrapping and the /api/features contract.

Uses the real GeoJSON files shipped in data/features (offline)."""

from __future__ import annotations

import pytest

from app.repositories.features import lon_ranges
from app.services.features import min_zoom_for, pixels_across, priority_for

R = 3396190.0


def test_min_zoom_grows_as_features_get_smaller():
    big = min_zoom_for("crater", 2300, R)    # Hellas-size
    gale = min_zoom_for("crater", 154, R)
    small = min_zoom_for("crater", 10, R)
    assert big < gale < small
    # The rule: at min_zoom the feature is at least 24 px across, not before.
    assert pixels_across(154, gale, R) >= 24 > pixels_across(154, gale - 1, R)


def test_category_overrides_and_priority():
    assert min_zoom_for("landing_site", None, R) == 1
    assert min_zoom_for("crater", None, R) == 7  # unknown size -> default
    assert priority_for("landing_site", None) > priority_for("crater", 2300)
    assert priority_for("crater", 200) > priority_for("crater", 20)


@pytest.mark.parametrize(
    "west,east,expected",
    [
        (-10, 10, [(-10, 10)]),
        (170, 200, [(170, 180), (-180, -160)]),   # Leaflet unwrapped
        (170, -170, [(170, 180), (-180, -170)]),  # GeoJSON antimeridian
        (-540, 540, [(-180, 180)]),               # whole world
        (190, 200, [(-170, -160)]),               # fully on the next copy
    ],
)
def test_lon_ranges(west, east, expected):
    assert lon_ranges(west, east) == expected


def test_features_endpoint_filters_by_zoom_and_bbox(client):
    far = client.get("/api/features", params={"zoom": 1, "limit": 5000}).json()
    near = client.get("/api/features", params={"zoom": 6, "limit": 5000}).json()
    assert far["type"] == "FeatureCollection"
    assert 0 < far["total"] < near["total"]
    assert all(f["properties"]["minZoom"] <= 1 for f in far["features"])

    gale = client.get("/api/features", params={"bbox": "136,-7,139,-4", "zoom": 6}).json()
    names = [f["properties"]["name"] for f in gale["features"]]
    assert "Gale" in names and "Curiosity (MSL)" in names
    # Highest priority first: the landing site beats the crater.
    assert names.index("Curiosity (MSL)") < names.index("Gale")
    lon, lat = next(f for f in gale["features"] if f["properties"]["name"] == "Gale")["geometry"]["coordinates"]
    assert 136 < lon < 139 and -7 < lat < -4


def test_features_across_antimeridian(client):
    r = client.get("/api/features", params={"bbox": "170,-20,190,20", "zoom": 5}).json()
    lons = [f["geometry"]["coordinates"][0] for f in r["features"]]
    assert any(l > 170 for l in lons) and any(l < -170 for l in lons)


def test_features_limit_categories_and_detail(client):
    r = client.get("/api/features", params={"categories": "landing_site", "limit": 3}).json()
    assert len(r["features"]) == 3 and r["total"] >= 10
    assert {f["properties"]["category"] for f in r["features"]} == {"landing_site"}

    cats = {c["id"]: c for c in client.get("/api/features/categories").json()}
    assert cats["crater"]["count"] > 1000 and "exploration_zone" in cats

    one = client.get("/api/features/site-curiosity").json()
    assert one["properties"]["name"].startswith("Curiosity")
    assert client.get("/api/features/nope").status_code == 404
    assert client.get("/api/features", params={"bbox": "1,2,3"}).status_code == 422
