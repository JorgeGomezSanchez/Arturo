# Arturo — backend (FastAPI)

Python API that serves everything the map needs. **The frontend only talks
to this API.** Where the data really comes from (NASA APIs over the
Internet, or files on disk in a Martian habitat) is an internal detail
that the frontend never sees.

- Python **3.10+** (tested on 3.10 and 3.13)
- [FastAPI](https://fastapi.tiangolo.com/) + [Uvicorn](https://www.uvicorn.org/)
- Interactive API docs (Swagger) at **http://localhost:8000/docs** while it runs
- Serves: map tiles for 16 Mars layers, layer metadata and legends, map
  labels (IAU names, landing sites, exploration zones) and user points of
  interest (POIs).

---

## Table of contents

1. [Quick start](#1-quick-start)
2. [Configuration (environment variables)](#2-configuration-environment-variables)
3. [Earth mode vs Mars mode](#3-earth-mode-vs-mars-mode)
4. [API endpoints](#4-api-endpoints)
5. [Internal architecture](#5-internal-architecture)
6. [Layer catalog (`layers.yaml`)](#6-layer-catalog-layersyaml)
7. [Map config and zones (`map.yaml`)](#7-map-config-and-zones-mapyaml)
8. [Offline tile packs](#8-offline-tile-packs)
9. [Map labels (`/api/features`)](#9-map-labels-apifeatures)
10. [Points of interest (`/api/pois`)](#10-points-of-interest-apipois)
11. [Tests](#11-tests)
12. [How to extend](#12-how-to-extend)
13. [Troubleshooting](#13-troubleshooting)

---

## 1. Quick start

All commands are run **from the `backend/` folder**.

### Linux / macOS

```bash
cd backend
python3 -m venv .venv              # create a virtual environment (once)
source .venv/bin/activate          # activate it (every new terminal)
pip install -r requirements.txt    # install dependencies (once / when they change)
cp .env.example .env               # optional: local configuration
uvicorn app.main:app --reload --port 8000
```

### Windows (PowerShell)

```powershell
cd backend
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1       # if blocked: Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
pip install -r requirements.txt
copy .env.example .env             # optional
uvicorn app.main:app --reload --port 8000
```

### fish shell

Same as Linux/macOS, but activate the venv with:

```fish
source .venv/bin/activate.fish
```

### Windows (cmd.exe)

```bat
cd backend
py -3 -m venv .venv
.venv\Scripts\activate.bat
pip install -r requirements.txt
copy .env.example .env
uvicorn app.main:app --reload --port 8000
```

Check it works:

- http://localhost:8000/ → a small JSON index (`api`, `docs`, `health`…).
  Older versions answered `404` here on purpose (everything lives under
  `/api`); a root route was added because the 404 confused people.
- http://localhost:8000/api/health → `{"status": "ok", "dataSource": "remote", "poiStore": "json (...)", ...}`
- http://localhost:8000/docs → **interactive documentation** (Swagger UI):
  try every endpoint from the browser. ReDoc: `/redoc`. Raw schema:
  `/openapi.json`.
- http://localhost:8000/api/tiles/viking_mdim21_color/0/0/0 → a Mars image

`--reload` restarts the server whenever you save a `.py` file (development
only). Add `--host 0.0.0.0` to reach it from other devices on your network.

---

## 2. Configuration (environment variables)

Every setting can be given as an environment variable or in `backend/.env`
(copy `.env.example`). Relative paths are resolved against `backend/`, not
against the folder you launch from.

| Variable | Default | What it does |
|---|---|---|
| `DATA_SOURCE` | `remote` | **Earth/Mars switch.** `remote` = download from NASA Mars Trek / Esri. `local` = read only from `LOCAL_TILES_DIR`, no network. |
| `LOCAL_TILES_DIR` | `./data/tiles` | Offline tile packs used in `local` mode. |
| `TILE_CACHE_ENABLED` | `true` | In `remote` mode, store every downloaded tile on disk. |
| `TILE_CACHE_DIR` | `./cache/tiles` | Where the cache lives (same layout as `LOCAL_TILES_DIR`). |
| `REMOTE_TIMEOUT_S` | `15` | HTTP timeout when calling NASA / Esri. |
| `REMOTE_USER_AGENT` | `Arturo/0.1 (...)` | User-Agent sent to remote servers. |
| `LAYERS_FILE` | `app/catalog/layers.yaml` | Layer catalog. |
| `MAP_FILE` | `app/catalog/map.yaml` | Map configuration and detail zones. |
| `FEATURES_DIR` | `./data/features` | Folder of label GeoJSON files. Every `*.geojson` in it is loaded at startup. |
| `POI_STORE` | `json` | `json` = POIs saved in a file (survive restarts); `memory` = kept in RAM only (tests, demos). |
| `POI_STORE_FILE` | `./data/pois/pois.json` | File used by the JSON store. Created on first write; not in git. |
| `CORS_ORIGINS` | `http://localhost:5173,http://127.0.0.1:5173` | Allowed browser origins if the frontend is served from another origin without the Vite proxy. Methods GET, POST, PUT and DELETE are allowed. |

---

## 3. Earth mode vs Mars mode

On Mars there is no "real-time Internet": a radio signal takes **4 to 24
minutes** each way between Mars and Earth. So the app is designed
**offline-first**: everything the astronaut needs must be on the device or
in the habitat, and updates arrive as packs from time to time.

| | Earth mode (hackathon demo) | Mars mode (future) |
|---|---|---|
| `DATA_SOURCE` | `remote` | `local` |
| Tiles come from | NASA Mars Trek WMTS / Esri, over the Internet | `LOCAL_TILES_DIR` on disk (later: local DB, Martian network…) |
| Disk cache | Yes: every visited tile is stored in `cache/tiles` | Not needed |
| Frontend changes | — | **None** |
| Backend code changes | — | **None** (only the env var) |
| Labels | Local GeoJSON in `data/features` | Same files (always offline) |
| POIs | `PoiRepository` (JSON file) | Same (later: a database or a store synced between habitats) |

Switching:

```bash
# Linux/macOS
DATA_SOURCE=local uvicorn app.main:app --port 8000
# Windows PowerShell
$env:DATA_SOURCE="local"; uvicorn app.main:app --port 8000
# or simply edit DATA_SOURCE in backend/.env
```

Because the cache and the local packs share the same folder layout, you
can **browse in Earth mode and then go offline**: point
`LOCAL_TILES_DIR=./cache/tiles` (or copy `cache/tiles/*` into
`data/tiles/`) and set `DATA_SOURCE=local`. The header badge in the UI
switches from "Earth mode · NASA APIs" to "Mars mode · local data".

---

## 4. API endpoints

All routes live under `/api` (plus `/` as an index and `/docs`). JSON uses
camelCase.

| Method | Path | Description |
|---|---|---|
| GET | `/` | JSON index with links to `/docs`, `/api/health`, … |
| GET | `/api/health` | Status, version, `dataSource` (`remote`/`local`) and active provider. |
| GET | `/api/map` | Map configuration: body, Mars radius, CRS, initial view, zoom limits, bounds. |
| GET | `/api/layers` | List of layers, ready for Leaflet (see below). |
| GET | `/api/layers/{layer_id}` | One layer (404 if unknown). |
| GET | `/api/tiles/{layer_id}/{z}/{x}/{y}` | Tile image. `z` = native source level, `x` = column from -180°, `y` = row from +90°. 404 = no data there, 502 = the source failed. |
| GET | `/api/zones` | Detail zones for the side menu. |
| GET | `/api/features` | Map labels as a GeoJSON FeatureCollection. Query: `bbox=west,south,east,north` (degrees; `west > east` crosses the ±180° line), `zoom` (required), `categories` (comma list, optional), `limit` (1–5000, default 500). Only features whose `minZoom ≤ zoom` are returned, most important first; `total` = how many matched before `limit`. See [§9](#9-map-labels-apifeatures). |
| GET | `/api/features/categories` | Label categories (`crater`, `vallis`, `landing_site`, …) with a readable label and a count. |
| GET | `/api/features/{id}` | One label (404 if unknown). |
| GET | `/api/pois` | User POIs as a GeoJSON FeatureCollection. Optional `bbox`. |
| POST | `/api/pois` | Create a POI. Body: `{name, category, notes, lat, lon, createdZoom}` → `201` + Feature. `422` on invalid input. |
| GET | `/api/pois/{id}` | One POI (404 if unknown). |
| PUT | `/api/pois/{id}` | Replace a POI's fields (same body as POST). Keeps `id` and `createdAt`, updates `updatedAt`. |
| DELETE | `/api/pois/{id}` | Delete → `204` (404 if unknown). |
| GET | `/api/pois/categories` | The 5 POI icon types with label, description and colour. |

Example `GET /api/layers` item:

```json
{
  "id": "ctx_global_5m",
  "name": "CTX global (5 m/pixel)",
  "group": "base",
  "tileUrl": "/api/tiles/ctx_global_5m/{z}/{x}/{y}",
  "tileSize": 512,
  "zoomOffset": -1,
  "minNativeZoom": 1,
  "maxNativeZoom": 13,
  "minZoom": 7,
  "maxZoom": 18,
  "opacity": 1.0,
  "zIndex": 2,
  "attribution": "CTX: NASA/JPL/MSSS/Caltech Murray Lab/Esri · via NASA Mars Trek",
  "category": "imagery",
  "defaultVisible": true,
  "blendMode": null,
  "coverage": { "south": -88, "west": -180, "north": 88, "east": 180 },
  "resolutionM": 5,
  "legend": null
}
```

Every layer can carry a `legend` (see [§6](#legends)), so the frontend
needs no per-layer code.

Note that `tileUrl` **always points to our backend**. The real source URL
stays private in `layers.yaml`.

Tile responses carry `Cache-Control: public, max-age=604800, immutable`
and a debug header `X-Tile-Origin: remote | cache | local`.

Planned for later phases (not implemented yet):
`GET /api/point?lat=&lon=` (values of every data layer at a point, read
from GeoTIFFs) and `POST /api/route` (A* route over slope/hazards).

---

## 5. Internal architecture

```
backend/
├── app/
│   ├── main.py              # creates the FastAPI app, CORS, routers, provider lifecycle
│   ├── core/config.py       # Settings (env vars / .env)
│   ├── api/                 # HTTP layer only (thin): health, layers, tiles, map, features, pois
│   ├── catalog/
│   │   ├── layers.yaml      # WHICH layers exist and where they come from
│   │   ├── map.yaml         # initial view, zoom limits, detail zones
│   │   ├── registry.py      # loads/validates layers.yaml
│   │   └── map_config.py    # loads map.yaml
│   ├── models/              # Pydantic models (internal config vs public contract)
│   ├── providers/           # WHERE tiles come from (the black box)
│   │   ├── base.py          # TileProvider interface + Tile + errors
│   │   ├── remote.py        # RemoteTileProvider  (Earth: NASA/Esri over HTTP)
│   │   ├── local.py         # LocalTileProvider   (Mars: folder on disk)
│   │   ├── cached.py        # CachedTileProvider  (disk cache decorator)
│   │   └── factory.py       # build_tile_provider(): the Earth/Mars switch
│   ├── repositories/
│   │   ├── features.py      # FeatureRepository + GeoJSON-folder implementation
│   │   └── pois.py          # PoiRepository + memory / JSON-file implementations
│   └── services/
│       ├── tiles.py         # TileService: validate → provider → transforms
│       ├── transforms.py    # post-processing (e.g. transparent no-data)
│       └── features.py      # label ranking: minZoom and priority per feature
├── scripts/
│   ├── prefetch_tiles.py    # builds offline tile packs
│   └── build_features.py    # rebuilds the label GeoJSON from USGS / Mars Trek
├── data/features/           # label GeoJSON (in git, ~0.8 MB) + README with sources
├── data/pois/               # user POIs (pois.json, not in git)
├── data/tiles/              # offline packs (contents not in git)
├── cache/                   # remote-mode tile cache (not in git)
└── tests/                   # pytest, fully offline
```

Request flow for a tile:

```
GET /api/tiles/ctx_global_5m/9/902/269
  └─ api/tiles.py            (HTTP: parse params, map errors to 404/502)
     └─ TileService          (layer exists? tile inside the grid?)
        └─ TileProvider      (chosen by DATA_SOURCE at startup)
           ├─ CachedTileProvider → on disk? return it : ask inner + save
           │    └─ RemoteTileProvider → GET astro.arcgis.com/.../9/269/902
           └─ LocalTileProvider  → read data/tiles/ctx_global_5m/9/902/269.png
        └─ transforms        (CTX: black no-data pixels → transparent)
```

### The provider interface

```python
class TileProvider(ABC):
    name: str

    async def get_tile(self, layer: LayerConfig, z: int, x: int, y: int) -> Tile:
        """Return the tile or raise TileNotFoundError / TileProviderError."""

    async def close(self) -> None: ...
```

- `TileNotFoundError` → HTTP 404 ("no data here"; the map just shows the
  layer underneath).
- `TileProviderError` → HTTP 502 ("the source failed").

The **only** place that decides which implementation to use is
`providers/factory.py`:

```python
def build_tile_provider(settings):
    if settings.data_source == "local":
        return LocalTileProvider(settings.local_tiles_dir)
    provider = RemoteTileProvider(...)
    if settings.tile_cache_enabled:
        provider = CachedTileProvider(provider, settings.tile_cache_dir)
    return provider
```

---

## 6. Layer catalog (`layers.yaml`)

`app/catalog/layers.yaml` is the single source of truth about layers. The
file itself documents every field. Key ideas:

- **Shared tile grid**: equirectangular (lat/lon), origin at (-180°, 90°),
  level 0 = 2 × 1 tiles, each level doubles. This is NASA Mars Trek's WMTS
  `default028mm` tile matrix set.
- `tile_size` 256 or 512. A 512 px source is exposed with `zoomOffset: -1`
  (source level N = map zoom N + 1) so it lines up with 256 px layers.
- `levels` = native levels of the source; `display` = map zooms where the
  layer is shown.
- `source.url_template` = remote URL with `{z}` `{x}` `{y}` (only used in
  remote mode, never exposed).
- `transform.nodata_to_transparent` = make pure-black pixels transparent.

- `category` = section in the frontend panel; `default_visible`;
  `blend_mode` (e.g. `multiply` for the shaded relief, so it darkens the
  layers below instead of covering them); `coverage` (lat/lon box, the
  frontend does not request tiles outside it); `resolution_m`; `legend`.

### All layers (16)

Every layer was checked for: tiles served at each declared level, correct
`{z}/{y}/{x}` order, and alignment with Viking. Alignment was measured by
phase correlation at map zoom 6: 0–1 px for THEMIS, MOLA and the
hillshade.

| id | Category | What it is | Res. | Levels | Legend |
|---|---|---|---|---|---|
| `viking_mdim21_color` | imagery (base) | Viking MDIM 2.1 colour mosaic | 232 m | 0–7 | — |
| `ctx_global_5m` | imagery (base) | CTX mosaic (Caltech/Esri), ±88° | 5 m | 0–12 | — |
| `mola_color_hillshade` | topography | MOLA colour-coded elevation + hillshade | 463 m | 0–7 | gradient, qualitative |
| `mola_hrsc_color_hillshade` | topography | MOLA+HRSC blended DEM, colour + hillshade | 200 m | 0–8 | gradient, qualitative |
| `mola_hrsc_hillshade` | topography | MOLA+HRSC grey shaded relief (`multiply`) | 200 m | 0–8 | gradient (sun-lit → shadow) |
| `themis_day_ir` | thermal | THEMIS daytime IR controlled mosaic, ±65° | 100 m | 0–9 | gradient, qualitative |
| `themis_night_ir` | thermal | THEMIS night-time IR controlled mosaic, ±65° | 100 m | 0–9 | gradient, qualitative |
| `tes_thermal_inertia` | thermal | TES thermal inertia (Putzig et al. 2005) | ~3 km | 0–1 | gradient, qualitative |
| `tes_albedo` | surface | TES bolometric albedo | ~7.4 km | 0–1 | gradient, qualitative |
| `tes_dust_cover_index` | surface | TES dust cover index (Ruff & Christensen 2002) | ~3.5 km | 0–2 | gradient, qualitative |
| `mola_roughness` | surface | MOLA roughness at 3 baselines in RGB (Kreslavsky & Head 2000) | ~7.5 km | 0–1 | channels |
| `tes_high_ca_pyroxene` | composition | TES high-Ca pyroxene abundance (Bandfield 2002) | ~16 km | 0–1 | gradient, qualitative |
| `tes_plagioclase` | composition | TES plagioclase abundance | ~16 km | 0–1 | gradient, qualitative |
| `tes_sheet_silicates_glass` | composition | TES sheet silicates / high-Si glass | ~16 km | 0–1 | gradient, qualitative |
| `geologic_map_sim3292` | geology | Geologic map of Mars, USGS SIM 3292 (Tanaka et al. 2014) | 1:20M | 0–11 | categorical, 44 units (quantitative) |
| `valley_networks` | hydrology | Valley networks (Hynek et al. 2010) | vector → tiles | 0–8 | symbol |

**Rejected candidates** (searched in the Mars Trek product catalogue):

| Product | Why not |
|---|---|
| `TES_Dust` | Same data as `tes_ruffdust` at a lower resolution. |
| MOLA greyscale DEM (8-bit PNG tiles) | 8-bit quantised heights and redundant with the colour DEM. Exact heights will come from the GeoTIFF in phase 2. |
| MOC wide-angle atlas | Low contrast, redundant with Viking, and ~2 px off at zoom 6. |
| `Dune_Field` | The tile service timed out every time. |
| Vector "feature" products (alluvial fans, gullies, glacier-like forms, aqueous minerals…) | They have no WMTS tiles (404). They could be added later as GeoJSON labels. |
| Exploration zones as a layer | Added as label features instead (searchable, clickable, offline). |

### Legends

The `legend` block in `layers.yaml` is sent unchanged (camelCase) in
`/api/layers`:

| Field | Meaning |
|---|---|
| `type` | `gradient` (colour ramp), `categorical` (list of classes), `channels` (what R/G/B mean), `symbol` (what a line/shape means). |
| `title`, `units` | What the colours represent. |
| `quantitative` | `true` only when the source documents real values for the colours. Otherwise the frontend shows a *"Qualitative scale – read as relative values"* badge. |
| `minLabel`, `maxLabel` | Text at the ends of a gradient (e.g. "Low thermal inertia (dust)"). |
| `stops` | `{color, label?, value?}`. For gradients, sampled from real tiles; for the geologic map, the 44 units read from the ArcGIS `MapServer/legend`. |
| `notes` | Plain-language explanation, including what is **not** known. |
| `sources` | Name + URL (product pages, papers with DOIs checked via Crossref). |

Mars Trek does not publish the colour ramp for most products. In those
cases we do not invent numbers. The direction of the ramp was checked
against well-known places (e.g. Tharsis and Arabia are dusty and bright,
Syrtis Major is dark and dust-poor), and the legend's notes say this.

### Base layers in detail

| id | Source | Resolution | Coverage | Levels | Shown at map zoom |
|---|---|---|---|---|---|
| `viking_mdim21_color` | [Viking MDIM 2.1 colour mosaic](https://trek.nasa.gov/tiles/Mars/EQ/Mars_Viking_MDIM21_ClrMosaic_global_232m/1.0.0/WMTSCapabilities.xml) (NASA/JPL/USGS) via Mars Trek | ~232 m/px | Whole planet, poles included | 0–7 (256 px, JPEG) | 0–18 (upscaled above 7) |
| `ctx_global_5m` | [CTX global mosaic](https://trek.nasa.gov/tiles/Mars/EQ/CTX_beta01_uncontrolled_5m_Caltech/1.0.0/WMTSCapabilities.xml) (NASA/JPL/MSSS/Caltech Murray Lab/Esri); Mars Trek's WMTS points to `astro.arcgis.com` | ~5 m/px | ~±88° latitude, small gaps | 0–12 (512 px, greyscale PNG) | 7–18 (native up to 13) |

Why two layers: Viking is the only truly global colour base and looks
great zoomed out, but it is blurry up close. CTX is the best global
high-resolution imagery, but at low zoom it is normalised to flat grey and
it has gaps; we show it from zoom 7 and make its gaps transparent so
Viking fills them.

---

## 7. Map config and zones (`map.yaml`)

`app/catalog/map.yaml` holds:

- `map`: body, Mars radius (3,396,190 m, used by the scale bar), CRS
  (`EPSG4326`), initial centre and zoom, min/max zoom, bounds.
- `zones`: detail zones for the side menu (`id`, `name`, `description`,
  `status` = `planned` | `available`, `center`, `bounds`, `tags`).
- `poi_categories`: the 5 POI icon types (`id`, `label`, `description`,
  `color`). Served by `/api/pois/categories`.
- `poi_visibility`: the zoom rules for POIs (`label_zoom_margin`,
  `marker_zoom_margin`, `world_zoom`). Sent in `/api/map` as
  `poiVisibility`. See [§10](#10-points-of-interest-apipois).
- `label_credits`: one credit line per label group (`names`,
  `landing_site`, `exploration_zone`). Sent in `/api/map` as
  `labelCredits`; the frontend's Credits panel shows a line while that
  group of labels is on.

Coordinates: planetocentric latitude, longitude −180…180 east-positive
(Mars Trek convention).

---

## 8. Offline tile packs

`scripts/prefetch_tiles.py` downloads tiles into the layout read by the
local provider (`{out}/{layer}/{z}/{x}/{y}.{ext}`). Already present tiles
are skipped, so it can be resumed.

```bash
# Every layer, whole planet, levels 0-3 (~89 MB) — a good "global" offline pack
python -m scripts.prefetch_tiles --layer all --max-level 3

# Several layers (comma list)
python -m scripts.prefetch_tiles --layer viking_mdim21_color,mola_hrsc_color_hillshade --max-level 5

# Whole planet, Viking, levels 0-4 (~680 tiles, ~35 MB)
python -m scripts.prefetch_tiles --layer viking_mdim21_color --max-level 4

# Gale crater, CTX, levels 6-10 (note --bbox= when it starts with "-")
python -m scripts.prefetch_tiles --layer ctx_global_5m \
    --min-level 6 --max-level 10 --bbox=-6.9,136.3,-3.9,139.3

# then
DATA_SOURCE=local uvicorn app.main:app --port 8000
```

Rough sizes: Viking ≈ 50 KB/tile (whole planet: level 5 ≈ 2.7k tiles
total ≈ 140 MB; level 7 ≈ 44k tiles ≈ 2 GB). CTX at full resolution for
the whole planet is terabytes, which is why detail is packed **per zone**.

---

## 9. Map labels (`/api/features`)

### Data

| File | Features | Source |
|---|---|---|
| `data/features/iau_nomenclature.geojson` | 2,055 IAU-approved names (craters, valles, montes, plana, albedo features…) with diameter, type and name origin | [USGS Gazetteer of Planetary Nomenclature](https://planetarynames.wr.usgs.gov/GIS_Downloads), `MARS_nomenclature_center_pts` shapefile |
| `data/features/exploration_zones.geojson` | 43 candidate human exploration zones (2015 NASA workshop) | Mars Trek `EZMars` MapServer, layer 0 |
| `data/features/landing_sites.geojson` | 11 robotic landing sites (Viking 1/2 … Zhurong) | Hand-curated from mission publications; see `data/features/README.md` |

The files are **pre-built and committed**, so labels work offline with no
download. To rebuild the first two from the original sources:

```bash
pip install -r requirements-dev.txt      # needs pyshp
python -m scripts.build_features
```

### Ranking (`services/features.py`)

Every feature gets two numbers when it is loaded:

- **`minZoom`**: the first zoom where it may appear. For a feature with a
  diameter it is the zoom where the feature is at least `LABEL_MIN_PX` =
  24 screen pixels wide. Landing sites start at zoom 1 and exploration
  zones at 3. Features with no diameter start at 7. Albedo features get
  +1, because they are vague regions.
- **`priority`**: `log10(diameter km)` plus a bonus: landing sites +5;
  exploration zones, terrae, planitiae and vastitates +0.3; plana and
  montes +0.2; albedo features −0.5.

`GET /api/features?bbox&zoom` filters by bbox (split into two longitude
ranges when it crosses ±180°) and `minZoom ≤ zoom`, then sorts by
priority. The frontend then removes labels that would overlap on screen
(see the frontend README). The server cannot do this step because it
does not know font sizes or the screen.

## 10. Points of interest (`/api/pois`)

### Model

```json
{
  "type": "Feature",
  "id": "5c09ff935acb422c9768d752b0b54a50",
  "geometry": { "type": "Point", "coordinates": [138.0597, -4.8175] },
  "properties": {
    "name": "Lava tube camp",
    "category": "shelter",
    "notes": "Overhang on the crater rim. Room for 2 rovers.",
    "createdZoom": 7,
    "createdAt": "2026-11-14T15:16:33Z",
    "updatedAt": "2026-11-14T15:16:33Z"
  }
}
```

Validation (`models/poi.py`): `name` 1–60 characters (trimmed; it is the
visible tag), `category` ∈ `resource | shelter | hazard | vehicle |
unknown`, `notes` ≤ 2000 characters, `lat` −90…90, `lon` wrapped into
−180…180 only if outside that range, coordinates rounded to 7 decimals
(~1 cm), `createdZoom` 0–24.

### Zoom rules (`map.yaml` → `poi_visibility`)

`createdZoom` is the map zoom when the POI was placed:

| Case | Rule (defaults) | Shown as |
|---|---|---|
| World-view POI | `createdZoom ≤ world_zoom` (3) | Icon + name at every zoom |
| Local POI, near its zoom | `zoom ≥ createdZoom − label_zoom_margin` (2) | Icon + name |
| Local POI, further out | `zoom ≥ createdZoom − marker_zoom_margin` (5) | Small coloured dot |
| Local POI, far out | otherwise | Hidden (still in the POIs list) |

The backend only stores and serves the rules; the frontend applies them.
Changing the numbers in `map.yaml` changes the behaviour with no code
change.

### Storage abstraction (`repositories/pois.py`)

```python
class PoiRepository(ABC):
    def list(self) -> list[Poi]: ...
    def get(self, poi_id: str) -> Poi: ...                 # raises PoiNotFoundError
    def create(self, data: PoiInput) -> Poi: ...
    def update(self, poi_id: str, data: PoiInput) -> Poi: ...  # raises PoiNotFoundError
    def delete(self, poi_id: str) -> None: ...             # raises PoiNotFoundError
```

The bbox filter of `GET /api/pois` is applied in the API layer, so a
store only needs these 5 methods. `PoiNotFoundError` becomes HTTP 404.

- `MemoryPoiRepository`: a dict in RAM (`POI_STORE=memory`).
- `JsonFilePoiRepository`: `{"version": 1, "pois": [...]}` in
  `POI_STORE_FILE`. Writes are protected by a lock and are atomic (write a
  temp file, then rename), so a crash never leaves a half-written file.
- `build_poi_repository(settings)` picks one. A SQLite/PostGIS store or a
  store synced between habitats = one new class + one branch there.

---

## 11. Tests

```bash
pip install -r requirements-dev.txt
python -m pytest -q
```

The suite runs the backend in Mars mode over synthetic tiles: it **never
touches the network**, and every run proves the app works offline. It
covers the public API contract (`/api/layers` shape, tile URLs pointing
to us, 404s, CTX transparency), the cache, grid validation, the whole
catalogue (every layer has a legend that matches its type, coverage is
valid), labels (bbox, crossing ±180°, zoom filter, ranking, categories),
POI storage (memory and JSON file, persistence across restarts) and the
POI API (CRUD, validation errors, bbox filter). POIs are written to a
temporary file during tests.

---

## 12. How to extend

### Add a new raster layer (e.g. MOLA hillshade, THEMIS)

1. Find its WMTS capabilities in [Mars Trek](https://trek.nasa.gov/mars/)
   (`https://trek.nasa.gov/tiles/Mars/EQ/<LAYER>/1.0.0/WMTSCapabilities.xml`)
   and read the `ResourceURL template`, tile size, number of levels and
   format. Make sure it is an **EQ** (equirectangular) layer.
2. Add an entry to `app/catalog/layers.yaml` (`group: overlay` for a
   toggleable layer). Convert `{TileMatrix}/{TileRow}/{TileCol}` to
   `{z}/{y}/{x}`.
3. Fill in `category`, `resolution_m`, `coverage` if it is not global,
   and a **truthful** `legend` (`quantitative: false` unless the source
   documents the values; add `sources`).
4. Restart the backend. `GET /api/layers` now lists it, and the frontend
   shows it in the Layers panel with its legend. Check alignment against
   Viking at a high zoom.

### Add a new data source (e.g. a Martian network or a database)

1. Create `app/providers/my_source.py` with a class implementing
   `TileProvider.get_tile()`.
2. Add a value to `data_source` in `core/config.py` and a branch in
   `providers/factory.py`.
3. Nothing else changes: not the endpoints, not the services, not the
   frontend.

### Add a detail zone

Add an entry under `zones:` in `app/catalog/map.yaml`.

### Add labels

Drop another `*.geojson` (Point features with at least `name` and
`category`) into `data/features/`. Optionally add a rule for the new
category in `services/features.py` (`minZoom`, priority bonus).

### Store POIs somewhere else

Implement `PoiRepository` (5 methods) and add a branch in
`build_poi_repository()`. The API and the frontend don't change.

---

## 13. Troubleshooting

| Problem | Fix |
|---|---|
| `ModuleNotFoundError: app` | Run uvicorn from the `backend/` folder. |
| PowerShell won't activate the venv | `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` |
| Tiles return 502 | No Internet or NASA/Esri is down. Already visited tiles still work from the cache; or switch to `DATA_SOURCE=local`. |
| Tiles return 404 | Normal outside a source's coverage/levels (e.g. CTX near the poles); the Viking base shows underneath. In local mode: the tile is not in the pack. |
| Port 8000 busy | `uvicorn app.main:app --port 8001` and set `VITE_DEV_BACKEND=http://127.0.0.1:8001` in the frontend. |
| Want to clear the cache | Delete `backend/cache/`. |
| `http://localhost:8000/` used to give 404 | Fixed: it now returns an index. Use `/docs` to explore the API. |
| `source .venv/bin/activate` fails in fish | Use `source .venv/bin/activate.fish`. |
| No labels on the map | Check `GET /api/features/categories`. If counts are 0, `FEATURES_DIR` points to the wrong folder. |
| POIs vanish on restart | `POI_STORE=memory` is set; use `json`. |
| `build_features.py` fails with `No module named shapefile` | `pip install -r requirements-dev.txt` (pyshp). |
