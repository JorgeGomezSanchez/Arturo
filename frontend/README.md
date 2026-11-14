# Arturo — frontend (React + Vite + Leaflet)

Web app that shows the Mars map. It is deliberately "dumb" about data:
**it only talks to the Arturo backend** and renders whatever the backend
announces. It does not know what Viking, CTX or NASA Mars Trek are.

- [React 19](https://react.dev/) + [Vite](https://vite.dev/)
- [Leaflet 1.9](https://leafletjs.com/) via [react-leaflet 5](https://react-leaflet.js.org/)
- Plain JavaScript (no TypeScript) to keep the learning curve low
- Node.js **20.19+ or 22.12+** (required by Vite; tested with Node 24)

---

## 1. Quick start

The backend must be running first (see [`../backend/README.md`](../backend/README.md)),
by default on `http://127.0.0.1:8000`.

### Linux / macOS / Windows (same commands)

```bash
cd frontend
npm install        # once, and whenever package.json changes
npm run dev        # dev server at http://localhost:5173
```

Open **http://localhost:5173**. You should see the whole planet in colour.

Other scripts:

| Command | What it does |
|---|---|
| `npm run dev` | Development server with hot reload. |
| `npm run build` | Production build into `dist/`. |
| `npm run preview` | Serves the `dist/` build locally to test it. |
| `npm run lint` | Lints the code with oxlint. |

---

## 2. Configuration

Copy `.env.example` to `.env.local` (git-ignored) only if you need to
change something. Vite only exposes variables starting with `VITE_`.

| Variable | Default | What it does |
|---|---|---|
| `VITE_API_URL` | *(empty)* | Backend base URL **as seen by the browser**. Empty = same origin: in development the Vite proxy forwards `/api` to the backend, so nothing needs to be set and there are no CORS issues. Set it only if the backend lives elsewhere (e.g. `http://192.168.1.50:8000`). |
| `VITE_DEV_BACKEND` | `http://127.0.0.1:8000` | Where the **Vite dev server** proxies `/api` (development only). |

---

## 3. How it works

On startup the app loads, in parallel:

| Request | Used for |
|---|---|
| `GET /api/health` | Header badge: "Earth mode · NASA APIs" or "Mars mode · local data". |
| `GET /api/map` | CRS, Mars radius, initial view, zoom limits, bounds. |
| `GET /api/layers` | Which tile layers to draw and all their Leaflet options. |
| `GET /api/zones` | Entries of the "Detail zones" side menu. |

Then, for each base layer, it creates a Leaflet `TileLayer` with the
options **exactly as the backend sends them** (`tileUrl`, `tileSize`,
`zoomOffset`, `minNativeZoom`, `maxNativeZoom`, `minZoom`, `maxZoom`,
`opacity`, `zIndex`, `attribution`). Tiles are requested to
`/api/tiles/{layer}/{z}/{x}/{y}` on our backend.

Consequences:

- **Adding or changing a layer never requires frontend changes**: edit
  `backend/app/catalog/layers.yaml`.
- **Switching the backend from Earth (NASA APIs) to Mars (local data)
  never requires frontend changes.**

### Projection (CRS)

NASA Mars Trek tiles are **equirectangular**: longitude/latitude map
linearly to x/y and level 0 is 2 × 1 tiles. That is exactly Leaflet's
built-in `L.CRS.EPSG4326` grid (not the default Web Mercator used by
Google/OSM maps), so tiles align and the coordinates shown are real
Martian latitude/longitude.

`src/map/crs.js` clones `L.CRS.EPSG4326` and replaces Earth's radius
(6371 km) with Mars' radius from `/api/map` (3396.19 km). Leaflet uses
that radius for distances, so without this the scale bar would be ~1.9×
wrong.

### Level of detail (LOD)

Leaflet only downloads the tiles visible at the current zoom. With the
phase 1 catalog:

- zoom 1–6: Viking MDIM 2.1 colour mosaic (~232 m/px, whole planet),
- zoom 7–13: CTX mosaic (~5 m/px) on top; CTX gaps are transparent so
  Viking shows through,
- zoom 14–16: the last CTX level is upscaled.

---

## 4. Features (phase 1)

- Whole-Mars 2D map with pan, zoom and LOD.
- Cursor latitude/longitude readout (planetocentric, east-positive),
  current zoom and approximate m/px.
- Metric scale bar using the Mars radius.
- Shareable URL: the view is kept in the hash as `#zoom/lat/lon`, e.g.
  `http://localhost:5173/#6/-5.4/137.8` (Gale crater).
- "Detail zones" side menu: click a zone to fly to it. Phase 1 zones
  are a stub ("Detail data coming soon").
- Earth/Mars mode badge.
- Data attributions (NASA/JPL/USGS, MSSS, Caltech Murray Lab, Esri).

---

## 5. Code structure

```
frontend/
├── index.html
├── vite.config.js            # dev server + /api proxy to the backend
├── .env.example
├── public/favicon.svg
└── src/
    ├── main.jsx              # React entry point
    ├── App.jsx               # loading/error screens + layout
    ├── App.css / index.css   # styles (dark HUD over the map)
    ├── api/client.js         # THE ONLY file that knows the backend URL
    ├── hooks/useBackendData.js   # loads health, map, layers, zones
    ├── map/
    │   ├── crs.js            # Mars CRS (EPSG4326 grid + Mars radius), m/px helper
    │   └── hash.js           # #zoom/lat/lon helpers
    └── components/
        ├── MarsMap.jsx       # MapContainer + TileLayers from /api/layers
        ├── CoordinatesReadout.jsx
        ├── HashView.jsx      # keeps the view in the URL hash
        ├── Header.jsx        # title + Earth/Mars badge
        └── ZonesPanel.jsx    # detail-zones side menu
```

Rules of thumb for the team:

1. Never put a NASA/Esri URL in the frontend. If you need new data, add
   it to the backend and expose it through `/api`.
2. All backend calls go through `src/api/client.js`.
3. Map-related helpers that are not components go in `src/map/`.

---

## 6. Troubleshooting

| Problem | Fix |
|---|---|
| "Could not reach the Arturo backend" | Start the backend (`uvicorn app.main:app --port 8000` in `backend/`). Check `VITE_DEV_BACKEND` if you use another port. |
| Grey/black map, no tiles | Open the browser DevTools → Network and look at `/api/tiles/...` responses. 502 = backend can't reach NASA (no Internet?): use cached tiles or Mars mode. |
| Some black/empty squares at high zoom | CTX has small gaps; Viking should show through. Near the poles (beyond ±88°) only Viking exists. |
| `npm install` fails on old Node | Install Node 20.19+ or 22.12+ (https://nodejs.org). |
