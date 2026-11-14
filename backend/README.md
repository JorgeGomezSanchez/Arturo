# Arturo — backend (FastAPI)

Python API that serves everything the map needs. **The frontend only talks
to this API.** Where the data really comes from (NASA APIs over the
Internet, or files on disk in a Martian habitat) is an internal detail
that the frontend never sees.

- Python **3.10+** (tested on 3.10 and 3.13)
- [FastAPI](https://fastapi.tiangolo.com/) + [Uvicorn](https://www.uvicorn.org/)
- Interactive API docs (Swagger) at **http://localhost:8000/docs** while it runs

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
9. [Tests](#9-tests)
10. [How to extend](#10-how-to-extend)
11. [Troubleshooting](#11-troubleshooting)

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

- http://localhost:8000/api/health → `{"status": "ok", "dataSource": "remote", ...}`
- http://localhost:8000/docs → interactive documentation
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
| `CORS_ORIGINS` | `http://localhost:5173,http://127.0.0.1:5173` | Allowed browser origins if the frontend is served from another origin without the Vite proxy. |

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

All routes live under `/api`. JSON uses camelCase.

| Method | Path | Description |
|---|---|---|
| GET | `/api/health` | Status, version, `dataSource` (`remote`/`local`) and active provider. |
| GET | `/api/map` | Map configuration: body, Mars radius, CRS, initial view, zoom limits, bounds. |
| GET | `/api/layers` | List of layers, ready for Leaflet (see below). |
| GET | `/api/layers/{layer_id}` | One layer (404 if unknown). |
| GET | `/api/tiles/{layer_id}/{z}/{x}/{y}` | Tile image. `z` = native source level, `x` = column from -180°, `y` = row from +90°. 404 = no data there, 502 = the source failed. |
| GET | `/api/zones` | Detail zones for the side menu. |

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
  "attribution": "CTX: NASA/JPL/MSSS/Caltech Murray Lab/Esri · via NASA Mars Trek"
}
```

Note that `tileUrl` **always points to our backend**. The real source URL
stays private in `layers.yaml`.

Tile responses carry `Cache-Control: public, max-age=604800, immutable`
and a debug header `X-Tile-Origin: remote | cache | local`.

Planned for later phases (not implemented yet): `GET /api/pois`,
`GET /api/point?lat=&lon=` (values of every data layer at a point, read
from GeoTIFFs) and `POST /api/route` (A* route over slope/hazards).

---

## 5. Internal architecture

```
backend/
├── app/
│   ├── main.py              # creates the FastAPI app, CORS, routers, provider lifecycle
│   ├── core/config.py       # Settings (env vars / .env)
│   ├── api/                 # HTTP layer only (thin): health, layers, tiles, map
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
│   └── services/
│       ├── tiles.py         # TileService: validate → provider → transforms
│       └── transforms.py    # post-processing (e.g. transparent no-data)
├── scripts/prefetch_tiles.py  # builds offline tile packs
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

### Phase 1 layers (both form the base map)

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

Coordinates: planetocentric latitude, longitude −180…180 east-positive
(Mars Trek convention).

---

## 8. Offline tile packs

`scripts/prefetch_tiles.py` downloads tiles into the layout read by the
local provider (`{out}/{layer}/{z}/{x}/{y}.{ext}`). Already present tiles
are skipped, so it can be resumed.

```bash
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

## 9. Tests

```bash
pip install -r requirements-dev.txt
python -m pytest -q
```

The suite runs the backend in Mars mode over synthetic tiles: it **never
touches the network**, and every run proves the app works offline. It
covers the public API contract (`/api/layers` shape, tile URLs pointing
to us, 404s, CTX transparency), the cache, and grid validation.

---

## 10. How to extend

### Add a new raster layer (e.g. MOLA hillshade, THEMIS)

1. Find its WMTS capabilities in [Mars Trek](https://trek.nasa.gov/mars/)
   (`https://trek.nasa.gov/tiles/Mars/EQ/<LAYER>/1.0.0/WMTSCapabilities.xml`)
   and read the `ResourceURL template`, tile size, number of levels and
   format. Make sure it is an **EQ** (equirectangular) layer.
2. Add an entry to `app/catalog/layers.yaml` (`group: overlay` for a
   toggleable layer). Convert `{TileMatrix}/{TileRow}/{TileCol}` to
   `{z}/{y}/{x}`.
3. Restart the backend. `GET /api/layers` now lists it. Done on the
   backend side.

### Add a new data source (e.g. a Martian network or a database)

1. Create `app/providers/my_source.py` with a class implementing
   `TileProvider.get_tile()`.
2. Add a value to `data_source` in `core/config.py` and a branch in
   `providers/factory.py`.
3. Nothing else changes: not the endpoints, not the services, not the
   frontend.

### Add a detail zone

Add an entry under `zones:` in `app/catalog/map.yaml`.

---

## 11. Troubleshooting

| Problem | Fix |
|---|---|
| `ModuleNotFoundError: app` | Run uvicorn from the `backend/` folder. |
| PowerShell won't activate the venv | `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` |
| Tiles return 502 | No Internet or NASA/Esri is down. Already visited tiles still work from the cache; or switch to `DATA_SOURCE=local`. |
| Tiles return 404 | Normal outside a source's coverage/levels (e.g. CTX near the poles); the Viking base shows underneath. In local mode: the tile is not in the pack. |
| Port 8000 busy | `uvicorn app.main:app --port 8001` and set `VITE_DEV_BACKEND=http://127.0.0.1:8001` in the frontend. |
| Want to clear the cache | Delete `backend/cache/`. |
