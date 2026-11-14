# Named features (`data/features/`)

Small, static GeoJSON files with the names shown as map labels and served
by `GET /api/features`. Unlike tile packs they **are committed** (≈ 750 KB
in total), so labels work offline in both modes (`remote` and `local`).

| File | Content | Origin | How to update |
|------|---------|--------|---------------|
| `iau_nomenclature.geojson` | 2,055 officially named Mars features (craters, valles, montes, albedo features…) with diameter, IAU descriptor type and name origin | [IAU / USGS Gazetteer of Planetary Nomenclature](https://planetarynames.wr.usgs.gov/GIS_Downloads), *MARS_nomenclature_center_pts* shapefile | `python -m scripts.build_features` |
| `exploration_zones.geojson` | 43 candidate **human** Exploration Zones (deduplicated by name) | NASA 2015 *First Landing Site / Exploration Zone Workshop for Human Missions to Mars*, via NASA Mars Trek (`EZMars` service) | `python -m scripts.build_features` |
| `landing_sites.geojson` | 11 robotic landers/rovers (Viking 1/2, Mars 3, Pathfinder, Spirit, Opportunity, Phoenix, Curiosity, InSight, Perseverance, Zhurong) | Hand-curated from mission landing coordinates (rounded, ~0.1°) | Edit by hand |

Conventions: GeoJSON `[lon, lat]`, **planetocentric** latitude,
**east-positive** longitude in −180…180 (same as the tiles and the
Gazetteer, converted from its 0…360 longitudes).

Feature properties: `name`, `category` (e.g. `crater`, `vallis`, `mons`,
`landing_site`, `exploration_zone`), `typeLabel`, `diameterKm` (may be
null), `origin` (what the name honours / short description), `source`,
`link`.

Display rules (minimum zoom and label priority) are **not** stored here:
the backend computes them at load time from category and diameter
(`app/services/features.py`), so they can be tuned without rebuilding.

Licensing: USGS and NASA data are public domain; please keep the credits
(“IAU WGPSN / USGS Gazetteer of Planetary Nomenclature”, “NASA Mars Trek”).
