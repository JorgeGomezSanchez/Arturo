# Arturo — Interplanetary Survival Guide: Martian Map

> NASA Space Apps Challenge 2026 · Challenge:
> [Interplanetary Survival Guide: Martian Map](https://www.spaceappschallenge.org/2026/challenges/interplanetary-survival-guide-martian-map/?tab=details)

**Arturo** is a layered 2D map of Mars designed as a *survival guide* for
astronauts: not just a pretty viewer, but a tool to plan safe and
scientifically valuable traverses (slopes, hazards, radiation, temperature,
water and shelter) that **works without a connection to Earth**.

![Phase 1: global Mars map](docs/img/phase1-global.jpg)

| Jezero crater, CTX 5 m/px (zoom 9) | Gale crater in Mars mode (offline, local data) |
|---|---|
| ![Jezero](docs/img/phase1-jezero-ctx.jpg) | ![Gale offline](docs/img/phase1-gale-mars-mode.jpg) |

---

## Table of contents

1. [The challenge and our approach](#1-the-challenge-and-our-approach)
2. [Current status](#2-current-status)
3. [Architecture](#3-architecture)
4. [Earth mode vs Mars mode](#4-earth-mode-vs-mars-mode)
5. [Repository structure](#5-repository-structure)
6. [Running the project step by step](#6-running-the-project-step-by-step)
7. [Environment variables](#7-environment-variables)
8. [API endpoints](#8-api-endpoints)
9. [Data sources and attributions](#9-data-sources-and-attributions)
10. [Roadmap](#10-roadmap)
11. [How to add a new layer](#11-how-to-add-a-new-layer)
12. [Decisions and why](#12-decisions-and-why)
13. [Known limitations](#13-known-limitations)
14. [Contributing (commits, branches)](#14-contributing)

---

## 1. The challenge and our approach

The challenge asks for a layered map of Mars, for one region or route,
that combines data from several NASA missions and helps an astronaut plan
a safe and scientifically interesting walk.

Interactive viewers such as NASA Mars Trek already exist, but they are
built for scientists on Earth with a permanent Internet connection. Our
angle is different:

- **A survival guide, not a viewer**: routes that avoid dangerous slopes,
  radiation and temperature warnings by time and season, points of
  interest (water ice, shelter, science targets).
- **Offline-first**: a radio signal takes **4 to 24 minutes** each way
  between Mars and Earth, so depending on a remote API is not realistic.
  Everything the astronaut needs lives on the device/habitat; updates
  arrive as packs.
- **Hybrid level-of-detail model**: the whole planet at low resolution
  (always available, a few GB) plus downloadable **detail zones** at high
  resolution (rover sites like Gale and Jezero, and candidate human
  landing regions with shallow ice like Arcadia Planitia and Deuteronilus
  Mensae).

## 2. Current status

**Phase 1 — done ✅**: global Mars map with pan, zoom and level of detail
(LOD), base satellite imagery, backend tile proxy with interchangeable
data providers (Earth/Mars), disk cache that doubles as an offline pack,
detail-zones menu (auto-zoom; detailed data comes later).

See the [roadmap](#10-roadmap) for what comes next.

---

## 3. Architecture

Monorepo with two top-level folders:

- **`frontend/`** — React + Vite + Leaflet (react-leaflet). 2D only.
- **`backend/`** — Python + FastAPI. Later: rasterio, numpy, scikit-image
  for GeoTIFF queries and routing.

The **golden rule**: *the frontend only talks to our backend*. The backend
is a black box that decides where the data comes from.

```mermaid
flowchart LR
    subgraph Browser["Frontend (React + Leaflet)"]
        UI["Map UI<br/>layers, zones, HUD"]
        CLIENT["api/client.js<br/>(only place that knows the backend)"]
        UI --> CLIENT
    end

    subgraph Backend["Backend (FastAPI)"]
        API["/api/* endpoints<br/>health · map · layers · tiles · zones"]
        CAT[("Catalog<br/>layers.yaml · map.yaml")]
        SVC["TileService<br/>validate · transforms"]
        FACT{"DATA_SOURCE?<br/>(providers/factory.py)"}
        REMOTE["RemoteTileProvider"]
        CACHE["CachedTileProvider<br/>(disk cache)"]
        LOCAL["LocalTileProvider"]
        API --> CAT
        API --> SVC --> FACT
        FACT -- "remote (Earth)" --> CACHE --> REMOTE
        FACT -- "local (Mars)" --> LOCAL
    end

    CLIENT -- "HTTP /api" --> API
    REMOTE -- "HTTPS" --> NASA[("NASA Mars Trek WMTS<br/>Esri astro.arcgis.com")]
    CACHE <--> DISK1[("backend/cache/tiles")]
    LOCAL <--> DISK2[("backend/data/tiles<br/>offline packs")]
```

Key pieces:

| Piece | Where | Role |
|---|---|---|
| Layer catalog | `backend/app/catalog/layers.yaml` | Single source of truth: which layers exist, their tile grid, zoom ranges, attribution and (privately) their remote URL. |
| Map config & zones | `backend/app/catalog/map.yaml` | Initial view, zoom limits, Mars radius, detail zones. |
| `TileProvider` interface | `backend/app/providers/base.py` | `get_tile(layer, z, x, y) -> Tile`. Any source implements just this. |
| Provider factory | `backend/app/providers/factory.py` | **The one Earth/Mars switch**, driven by `DATA_SOURCE`. |
| API client | `frontend/src/api/client.js` | The only frontend file that calls the backend. |
| Map component | `frontend/src/components/MarsMap.jsx` | Renders whatever layers `/api/layers` announces, with the options it sends. |

More detail: [`backend/README.md`](backend/README.md) and
[`frontend/README.md`](frontend/README.md).

## 4. Earth mode vs Mars mode

| | 🌍 Earth mode (hackathon demo) | 🔴 Mars mode (deployment on Mars) |
|---|---|---|
| Setting | `DATA_SOURCE=remote` (default) | `DATA_SOURCE=local` |
| Where tiles come from | NASA Mars Trek / Esri over the Internet | Local folder (`LOCAL_TILES_DIR`); later a local DB or Martian network |
| Cache | Every visited tile is saved in `backend/cache/tiles` | — |
| Frontend changes | — | **none** |
| Backend changes | — | **none** (an env var). A brand-new kind of source = one new provider class + one line in the factory |

How to switch:

```bash
# in backend/.env
DATA_SOURCE=local
LOCAL_TILES_DIR=./data/tiles     # or ./cache/tiles to reuse what you browsed
```

The cache and the offline packs use **the same folder layout**
(`{layer}/{z}/{x}/{y}.{ext}`), so a demo can be: browse a zone with
Internet → cut the network → switch to Mars mode → everything you
visited keeps working. The header badge in the UI shows the active mode.
Packs can also be built in advance with `backend/scripts/prefetch_tiles.py`.

---

## 5. Repository structure

```
Arturo/
├── README.md                 ← you are here
├── docs/img/                 screenshots used in the READMEs
├── backend/                  Python API (FastAPI)
│   ├── README.md             backend docs (setup, API, architecture)
│   ├── requirements.txt      runtime dependencies
│   ├── requirements-dev.txt  + pytest
│   ├── .env.example          all settings, commented
│   ├── app/
│   │   ├── main.py           FastAPI app, CORS, routers, provider lifecycle
│   │   ├── core/config.py    settings from env vars / .env
│   │   ├── api/              endpoints: health, map, layers, tiles
│   │   ├── catalog/          layers.yaml, map.yaml and their loaders
│   │   ├── models/           Pydantic models (internal vs public contract)
│   │   ├── providers/        TileProvider + remote / local / cached + factory
│   │   └── services/         TileService + tile transforms
│   ├── scripts/              prefetch_tiles.py (offline packs)
│   ├── data/tiles/           offline packs (contents not in git)
│   └── tests/                pytest suite (offline)
└── frontend/                 Web app (React + Vite + Leaflet)
    ├── README.md             frontend docs
    ├── package.json
    ├── vite.config.js        dev server + /api proxy
    ├── .env.example
    └── src/
        ├── api/client.js     backend client (only place with the API URL)
        ├── hooks/            useBackendData
        ├── map/              Mars CRS, URL-hash helpers
        └── components/       MarsMap, ZonesPanel, Header, CoordinatesReadout, HashView
```

---

## 6. Running the project step by step

You need **two terminals**: one for the backend and one for the frontend.

### Requirements

- **Python 3.10 or newer** — https://www.python.org/downloads/
  (Windows: tick "Add Python to PATH" in the installer).
- **Node.js 20.19+ or 22.12+** (LTS recommended) — https://nodejs.org/
- **Git** — https://git-scm.com/
- Internet connection (Earth mode downloads tiles from NASA).

### 0. Clone

```bash
git clone https://github.com/JorgeGomezSanchez/Arturo.git
cd Arturo
```

### 1. Backend (terminal 1)

**Linux / macOS**

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env            # optional
uvicorn app.main:app --reload --port 8000
```

**Windows (PowerShell)**

```powershell
cd backend
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1     # if blocked: Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
pip install -r requirements.txt
copy .env.example .env           # optional
uvicorn app.main:app --reload --port 8000
```

**Windows (cmd.exe)**: same as PowerShell but activate with
`.venv\Scripts\activate.bat`.

Check: http://localhost:8000/api/health and http://localhost:8000/docs

### 2. Frontend (terminal 2) — same on every OS

```bash
cd frontend
npm install
npm run dev
```

Open **http://localhost:5173** 🚀

Tips:

- Shareable views: the URL keeps `#zoom/lat/lon`, e.g.
  http://localhost:5173/#6/-5.4/137.8 is Gale crater.
- The first visit to an area is slower (tiles come from NASA); after that
  they come from the backend's disk cache.

### 3. Tests (optional)

```bash
cd backend
pip install -r requirements-dev.txt
python -m pytest -q
```

---

## 7. Environment variables

### Backend (`backend/.env`, see `backend/.env.example`)

| Variable | Default | Description |
|---|---|---|
| `DATA_SOURCE` | `remote` | `remote` = Earth mode (NASA APIs + cache), `local` = Mars mode (disk only). |
| `LOCAL_TILES_DIR` | `./data/tiles` | Offline packs for local mode. |
| `TILE_CACHE_ENABLED` | `true` | Save downloaded tiles to disk in remote mode. |
| `TILE_CACHE_DIR` | `./cache/tiles` | Cache folder (same layout as the packs). |
| `REMOTE_TIMEOUT_S` | `15` | Timeout for NASA/Esri requests. |
| `REMOTE_USER_AGENT` | `Arturo/0.1 (...)` | User-Agent for remote requests. |
| `LAYERS_FILE` | `app/catalog/layers.yaml` | Layer catalog. |
| `MAP_FILE` | `app/catalog/map.yaml` | Map config and zones. |
| `CORS_ORIGINS` | `http://localhost:5173,...` | Allowed origins when not using the Vite proxy. |

### Frontend (`frontend/.env.local`, see `frontend/.env.example`)

| Variable | Default | Description |
|---|---|---|
| `VITE_API_URL` | *(empty = same origin)* | Backend URL as seen by the browser. Leave empty in development. |
| `VITE_DEV_BACKEND` | `http://127.0.0.1:8000` | Target of the Vite dev proxy for `/api`. |

---

## 8. API endpoints

Interactive docs at http://localhost:8000/docs.

| Method | Path | Description | Phase |
|---|---|---|---|
| GET | `/api/health` | Status, version, data source (`remote`/`local`), active provider | 1 ✅ |
| GET | `/api/map` | CRS, Mars radius, initial view, zoom limits, bounds | 1 ✅ |
| GET | `/api/layers` | Layers with Leaflet-ready options; `tileUrl` points to our backend | 1 ✅ |
| GET | `/api/layers/{id}` | One layer | 1 ✅ |
| GET | `/api/tiles/{layer}/{z}/{x}/{y}` | Tile image (404 = no data, 502 = source failed) | 1 ✅ |
| GET | `/api/zones` | Detail zones for the side menu | 1 ✅ (stub data) |
| GET | `/api/pois` | Points of interest (GeoJSON) | 1b/2 |
| GET | `/api/point?lat=&lon=` | Values at a point: elevation, slope, estimated temperature, radiation | 2 |
| POST | `/api/route` | Safe route between two points (GeoJSON + elevation profile + hazards) | 3 |

---

## 9. Data sources and attributions

| Data | Provider / credits | Used for | Link |
|---|---|---|---|
| Viking MDIM 2.1 colour mosaic, ~232 m/px | NASA / JPL / USGS, served by NASA Mars Trek | Global colour base (zoom 0-7+) | [WMTS capabilities](https://trek.nasa.gov/tiles/Mars/EQ/Mars_Viking_MDIM21_ClrMosaic_global_232m/1.0.0/WMTSCapabilities.xml) |
| CTX global mosaic, ~5 m/px | NASA / JPL / MSSS / Caltech Murray Lab / Esri; listed in NASA Mars Trek, tiles from Esri's `astro.arcgis.com` | High-resolution base (zoom 7+) | [WMTS capabilities](https://trek.nasa.gov/tiles/Mars/EQ/CTX_beta01_uncontrolled_5m_Caltech/1.0.0/WMTSCapabilities.xml) · [Esri MapServer](https://astro.arcgis.com/arcgis/rest/services/OnMars/CTX/MapServer) |
| NASA Mars Trek | NASA Solar System Treks Project (JPL) | Tile services (WMTS) | https://trek.nasa.gov/mars/ |

Planned for later phases: MOLA elevation/hillshade (MGS), THEMIS day/night
infrared mosaics (Mars Odyssey), HiRISE images and DTMs (MRO), MSL/RAD
radiation measurements (Curiosity), NASA Ames Mars climate model.

Attributions are shown in the map's bottom-right corner and are defined
per layer in `layers.yaml`.

---

## 10. Roadmap

| Phase | Goal | Main work |
|---|---|---|
| **1 ✅** | Global map | Whole-Mars 2D map with pan/zoom/LOD, base imagery (Viking + CTX), backend proxy with Earth/Mars providers, cache/offline packs, zones menu stub. |
| **1b** | More layers | Toggleable overlays: MOLA hillshade/topography, THEMIS thermal (day/night); POIs as GeoJSON (`/api/pois`) with info cards; layer switcher UI. |
| **2** | Point query | Click anywhere → elevation, slope, estimated temperature, radiation. Backend reads GeoTIFFs with rasterio (global MOLA DEM ~463 m/px; per-zone HiRISE DTMs) → `GET /api/point`. |
| **3** | Safe routes | Slope map from the DEM, hazard mask above a threshold angle, A* (scikit-image) between two points → `POST /api/route` returning GeoJSON with elevation profile, distance and hazard warnings. |
| **Extras** | Survival guide | Detail-zone packs (HiRISE) downloadable from the side menu; time/season-aware temperature and radiation warnings; offline pack manager; Service Worker for a fully offline frontend; printable traverse plan. |

---

## 11. How to add a new layer

Example: a MOLA hillshade from Mars Trek.

1. Open its capabilities, e.g.
   `https://trek.nasa.gov/tiles/Mars/EQ/<LAYER_NAME>/1.0.0/WMTSCapabilities.xml`.
   Note: `ResourceURL template`, `TileWidth` (256/512), number of
   `TileMatrix` levels, `Format`. Use **EQ** (equirectangular) layers only.
2. Add an entry to `backend/app/catalog/layers.yaml`:

   ```yaml
   - id: mola_hillshade
     name: "MOLA hillshade"
     description: "Shaded relief from MGS MOLA elevation"
     group: overlay            # toggleable (base = always visible)
     format: png
     tile_size: 256
     levels: { min: 0, max: 7 }
     display: { min_zoom: 0, max_zoom: 18 }
     opacity: 0.5
     z_index: 10
     attribution: "MOLA: NASA/JPL/GSFC · via NASA Mars Trek"
     source:
       # WMTS {TileMatrix}/{TileRow}/{TileCol}  ->  {z}/{y}/{x}
       url_template: "https://trek.nasa.gov/tiles/Mars/EQ/<LAYER_NAME>/1.0.0/default/default028mm/{z}/{y}/{x}.png"
   ```

3. Restart the backend and check `GET /api/layers` and
   `GET /api/tiles/mola_hillshade/0/0/0`.
4. Frontend: base layers appear automatically. Overlays will appear in the
   layer switcher planned for phase 1b (no per-layer frontend code).

---

## 12. Decisions and why

| Decision | Alternatives | Why |
|---|---|---|
| **Leaflet** (react-leaflet) | OpenLayers | Simpler API and smaller learning curve for a hackathon; for a single 2D map it is more than enough. The one hard part —a non-Web-Mercator projection— is solved with Leaflet's built-in `L.CRS.EPSG4326`. OpenLayers handles exotic projections better but is slower to learn. |
| **FastAPI** | Flask | Automatic interactive docs (`/docs`) so frontend and backend people can work in parallel; request validation with Pydantic; native async, ideal for proxying many tile requests at once. |
| **React + Vite**, plain JS | Vue, TypeScript | Large ecosystem and react-leaflet; Vite is the fastest dev setup; plain JS keeps it approachable for the team. |
| **Equirectangular CRS** (EPSG:4326-like grid) | Web Mercator (EPSG:3857) | NASA Mars Trek's global tiles are equirectangular with a 2×1 level 0. Using the same grid means tiles line up with no reprojection, and lat/lon readouts are real Martian coordinates. Web Mercator would also distort the poles heavily. |
| **Mars radius in the CRS** | Leaflet default | Leaflet measures distances with Earth's radius; we override it with Mars' 3396.19 km so the scale bar and m/px are correct. |
| **Hybrid LOD model** | Whole planet at full resolution / a single zone | Global low-res imagery is a few GB and works everywhere; full-res global CTX is terabytes and HiRISE doesn't cover the whole planet. So: global base always + high-res detail zones. Routing also only makes sense at high resolution. |
| **Offline-first, backend as a black box** | Frontend calling NASA directly | On Mars there's no real-time API (4-24 min light delay). Hiding the source behind `TileProvider` means the Earth demo and the Mars deployment share 100 % of the frontend and almost all the backend. |
| **Viking + CTX stacked as the base** | Only CTX / only Viking | Viking is the only truly global colour base and looks best zoomed out; CTX gives ~5 m/px detail but looks flat grey at low zoom and has gaps. Stacking both (CTX from zoom 7, gaps transparent) gives the best of each. |
| **Catalog in YAML** | Hard-coded in Python/JS | Non-developers on the team can add layers/zones; comments allowed; one place to look. |
| **Cache layout = offline pack layout** | Separate formats | Browsing in Earth mode automatically produces a pack usable in Mars mode. |

---

## 13. Known limitations

- **CTX coverage**: ~99 % of the planet between ±88° latitude, with small
  gaps (transparent; Viking shows underneath). Beyond ±88° only Viking.
- **CTX is greyscale** and "uncontrolled" (not perfectly co-registered
  with other datasets; offsets of tens to hundreds of metres are possible
  in places). Fine for visualisation; precise work will use HiRISE/DTMs.
- **Max native resolution**: CTX level 12 (map zoom 13, ~5 m/px). Zooms
  14–16 upscale it. Esri's service returns HTTP 400 above level 12.
- **Third-party availability**: Earth mode depends on trek.nasa.gov and
  astro.arcgis.com being up. Visited tiles keep working from the cache.
- **Mars mode only serves what is in the pack**: unvisited / unpacked
  tiles return 404 (the map shows what it has).
- **No Service Worker yet**: the frontend itself still needs to be served
  (it is tiny and local in Mars mode; a PWA is on the roadmap).

---

## 14. Contributing

- Branch `main` holds working code. Use feature branches
  (`feat/point-query`, `fix/...`) and pull requests when several people
  work at once.
- Commits follow [Conventional Commits](https://www.conventionalcommits.org/)
  in English: `feat(backend): ...`, `fix(frontend): ...`, `docs: ...`,
  `test: ...`, `chore: ...`, with a body explaining **what and why**.
- Keep the READMEs up to date when you change behaviour or add endpoints.
