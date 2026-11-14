"""POI CRUD over HTTP (GeoJSON contract used by the frontend)."""

from __future__ import annotations

import json

BODY = {"name": "Lava tube", "category": "shelter", "notes": "Entrance ~3 m wide", "lat": -5.1, "lon": 137.9, "createdZoom": 11}


def test_categories_and_visibility_rules_come_from_backend(client):
    cats = [c["id"] for c in client.get("/api/pois/categories").json()]
    assert cats == ["resource", "shelter", "hazard", "vehicle", "unknown"]
    vis = client.get("/api/map").json()["poiVisibility"]
    assert vis["labelZoomMargin"] < vis["markerZoomMargin"]


def test_poi_crud_flow(client, tiles_dir):
    assert client.get("/api/pois").json() == {"type": "FeatureCollection", "features": []}

    created = client.post("/api/pois", json=BODY)
    assert created.status_code == 201
    feat = created.json()
    poi_id = feat["id"]
    assert feat["type"] == "Feature" and feat["geometry"]["coordinates"] == [137.9, -5.1]
    assert feat["properties"]["createdZoom"] == 11 and feat["properties"]["category"] == "shelter"

    # Persisted to the configured JSON file
    stored = json.loads((tiles_dir.parent / "pois.json").read_text())
    assert stored["pois"][0]["id"] == poi_id

    upd = client.put(f"/api/pois/{poi_id}", json={**BODY, "name": "Lava tube A", "category": "hazard"}).json()
    assert upd["properties"]["name"] == "Lava tube A" and upd["properties"]["category"] == "hazard"
    assert upd["properties"]["createdAt"] == feat["properties"]["createdAt"]

    assert client.get(f"/api/pois/{poi_id}").json()["properties"]["name"] == "Lava tube A"
    inside = client.get("/api/pois", params={"bbox": "137,-6,138,-5"}).json()["features"]
    outside = client.get("/api/pois", params={"bbox": "0,0,10,10"}).json()["features"]
    assert len(inside) == 1 and outside == []

    assert client.delete(f"/api/pois/{poi_id}").status_code == 204
    assert client.get(f"/api/pois/{poi_id}").status_code == 404
    assert client.delete(f"/api/pois/{poi_id}").status_code == 404
    assert client.put(f"/api/pois/{poi_id}", json=BODY).status_code == 404


def test_poi_validation_errors(client):
    assert client.post("/api/pois", json={**BODY, "category": "pizza"}).status_code == 422
    assert client.post("/api/pois", json={**BODY, "name": " "}).status_code == 422
    assert client.post("/api/pois", json={k: v for k, v in BODY.items() if k != "createdZoom"}).status_code == 422


def test_health_reports_poi_store(client):
    assert client.get("/api/health").json()["poiStore"].startswith("json")
