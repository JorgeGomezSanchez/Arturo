"""Build the named-feature datasets served by ``GET /api/features``.

Downloads two public datasets ONCE (Earth side) and converts them into
small GeoJSON files under ``backend/data/features/`` that are committed
to the repo, so labels work offline in BOTH modes (remote and local):

1. IAU / USGS Gazetteer of Planetary Nomenclature, Mars center points
   (shapefile): every officially named crater, valley, mountain...
   https://planetarynames.wr.usgs.gov/GIS_Downloads
   -> ``iau_nomenclature.geojson``
2. NASA "Exploration Zones" proposed at the 2015 First Landing Site /
   Exploration Zone Workshop for Human Missions to Mars, as published by
   NASA Mars Trek (EZMars service, layer 0).
   -> ``exploration_zones.geojson``

``landing_sites.geojson`` (robotic landers and rovers) is hand-curated and
is NOT generated here.

Coordinates are written as GeoJSON [lon, lat] with planetocentric latitude
and east-positive longitude in -180..180 (same convention as the tiles).

Only geometry and descriptive fields are stored. Display rules (which
zoom a label appears at, its priority) are computed by the backend at
load time (``app/services/features.py``), so they can be tuned without
rebuilding the data.

Usage (from ``backend/``, venv active; needs ``pip install -r
requirements-dev.txt`` for pyshp)::

    python -m scripts.build_features
"""

from __future__ import annotations

import io
import json
import sys
import tempfile
import zipfile
from pathlib import Path

import httpx

from app.core.config import get_settings

GAZETTEER_ZIP = (
    "https://asc-planetarynames-data.s3.us-west-2.amazonaws.com/"
    "MARS_nomenclature_center_pts.zip"
)
EZ_QUERY = (
    "https://trek.nasa.gov/mars/trekarcgis/rest/services/EZMars/MapServer/0/query"
    "?where=1%3D1&outFields=*&returnGeometry=true&f=geojson"
)

# IAU descriptor term -> (category id, human readable label)
DESCRIPTORS: dict[str, tuple[str, str]] = {
    "Crater, craters": ("crater", "Crater"),
    "Vallis, valles": ("vallis", "Valley (vallis)"),
    "Albedo Feature": ("albedo", "Albedo feature (classical name)"),
    "Mons, montes": ("mons", "Mountain (mons)"),
    "Fossa, fossae": ("fossa", "Trough (fossa)"),
    "Mensa, mensae": ("mensa", "Mesa (mensa)"),
    "Dorsum, dorsa": ("dorsum", "Ridge (dorsum)"),
    "Planum, plana": ("planum", "Plateau (planum)"),
    "Patera, paterae": ("patera", "Volcanic crater (patera)"),
    "Chaos, chaoses": ("chaos", "Broken terrain (chaos)"),
    "Cavus, cavi": ("cavus", "Hollow (cavus)"),
    "Tholus, tholi": ("tholus", "Domed hill (tholus)"),
    "Rupes, rupēs": ("rupes", "Scarp (rupes)"),
    "Chasma, chasmata": ("chasma", "Canyon (chasma)"),
    "Collis, colles": ("collis", "Hills (collis)"),
    "Catena, catenae": ("catena", "Crater chain (catena)"),
    "Sulcus, sulci": ("sulcus", "Grooved terrain (sulcus)"),
    "Scopulus, scopuli": ("scopulus", "Irregular scarp (scopulus)"),
    "Terra, terrae": ("terra", "Highland region (terra)"),
    "Planitia, planitiae": ("planitia", "Low plain (planitia)"),
    "Labes, labēs": ("labes", "Landslide (labes)"),
    "Unda, undae": ("unda", "Dune field (unda)"),
    "Palus, paludes": ("palus", "Plain (palus)"),
    "Labyrinthus, labyrinthi": ("labyrinthus", "Valley maze (labyrinthus)"),
    "Lingula, lingulae": ("lingula", "Tongue-shaped plateau (lingula)"),
    "Serpens, serpentes": ("serpens", "Sinuous feature (serpens)"),
    "Fluctus, fluctūs": ("fluctus", "Flow terrain (fluctus)"),
    "Vastitas, vastitates": ("vastitas", "Extensive plain (vastitas)"),
    "Macula, maculae": ("macula", "Dark spot (macula)"),
}


def lon180(lon: float) -> float:
    """Any longitude -> -180..180 (east positive)."""
    lon = ((float(lon) + 180.0) % 360.0) - 180.0
    return lon


def point(fid: str, lon: float, lat: float, props: dict) -> dict:
    return {
        "type": "Feature",
        "id": fid,
        "geometry": {"type": "Point", "coordinates": [round(lon180(lon), 5), round(float(lat), 5)]},
        "properties": props,
    }


def build_gazetteer(client: httpx.Client) -> dict:
    import shapefile  # pyshp (dev dependency)

    print(f"Downloading {GAZETTEER_ZIP} ...")
    raw = client.get(GAZETTEER_ZIP).raise_for_status().content
    with tempfile.TemporaryDirectory() as tmp:
        zipfile.ZipFile(io.BytesIO(raw)).extractall(tmp)
        shp = next(Path(tmp).rglob("*.shp"))
        reader = shapefile.Reader(str(shp), encoding="utf-8")
        records = [r.as_dict() for r in reader.records()]

    features, unknown = [], set()
    for r in records:
        category, label = DESCRIPTORS.get(r["type"], ("other", r["type"]))
        if category == "other":
            unknown.add(r["type"])
        fid = "iau-" + r["link"].rstrip("/").rsplit("/", 1)[-1]
        features.append(
            point(
                fid,
                r["center_lon"],
                r["center_lat"],
                {
                    "name": r["clean_name"] or r["name"],
                    "category": category,
                    "typeLabel": label,
                    "diameterKm": round(float(r["diameter"] or 0), 3) or None,
                    "origin": r["origin"] or None,
                    "source": "IAU Gazetteer of Planetary Nomenclature (USGS)",
                    "link": r["link"].replace("http://", "https://"),
                },
            )
        )
    if unknown:
        print("  ! unknown descriptor terms (category 'other'):", sorted(unknown))
    print(f"  {len(features)} named features")
    return {"type": "FeatureCollection", "name": "iau_nomenclature", "features": features}


def build_exploration_zones(client: httpx.Client) -> dict:
    print(f"Downloading {EZ_QUERY} ...")
    data = client.get(EZ_QUERY).raise_for_status().json()
    features, seen = [], set()
    for f in data["features"]:
        p = f["properties"]
        name = p["name"].strip()
        # Placeholder rows: methodology abstracts without a site location.
        if (p["lat"], p["lon"]) == (0, 0) or name.startswith("(Method") or "No site location" in name:
            continue
        name = name.replace("(No pdf)", "").strip()
        if name.lower() in seen:  # several proposals for the same site
            continue
        seen.add(name.lower())
        link = (p.get("abstract_l") or "").strip() or None
        features.append(
            point(
                f"ez-{p['abstract']}",
                p["lon"],
                p["lat"],
                {
                    "name": f"EZ: {name}",
                    "category": "exploration_zone",
                    "typeLabel": "Candidate human exploration zone (NASA 2015)",
                    "diameterKm": 200.0,  # EZs are ~100 km radius regions
                    "origin": "Proposed at the 2015 NASA First Landing Site / Exploration Zone Workshop for Human Missions to Mars.",
                    "source": "NASA Mars Trek (EZMars) / 2015 EZ Workshop",
                    "link": link.replace("http://", "https://") if link else None,
                },
            )
        )
    print(f"  {len(features)} exploration zones")
    return {"type": "FeatureCollection", "name": "exploration_zones", "features": features}


def write(fc: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # Compact but line-per-feature, so git diffs stay readable.
    with open(path, "w", encoding="utf-8") as fh:
        fh.write('{"type":"FeatureCollection","name":%s,"features":[\n' % json.dumps(fc["name"]))
        fh.write(",\n".join(json.dumps(f, ensure_ascii=False, separators=(",", ":")) for f in fc["features"]))
        fh.write("\n]}\n")
    print(f"  -> {path} ({path.stat().st_size / 1024:.0f} KB)")


def main() -> int:
    out_dir = get_settings().features_dir
    with httpx.Client(timeout=120, follow_redirects=True,
                      headers={"User-Agent": get_settings().remote_user_agent}) as client:
        write(build_gazetteer(client), out_dir / "iau_nomenclature.geojson")
        write(build_exploration_zones(client), out_dir / "exploration_zones.geojson")
    return 0


if __name__ == "__main__":
    sys.exit(main())
