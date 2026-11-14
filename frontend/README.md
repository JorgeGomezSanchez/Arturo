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
| `GET /api/features/categories` | Label groups and counts for the Layers panel. |
| `GET /api/pois/categories` | POI icon types and colours. |

After that it calls, as needed:

| Request | When |
|---|---|
| `GET /api/features?bbox=&zoom=&limit=600` | When the view changes (debounced 120 ms; results cached per view). |
| `GET /api/pois` | Once at startup and after each change. |
| `POST` / `PUT` / `DELETE /api/pois…` | When you create, edit or delete a POI. |

Then, for each layer, it creates a Leaflet `TileLayer` with the
options **exactly as the backend sends them** (`tileUrl`, `tileSize`,
`zoomOffset`, `minNativeZoom`, `maxNativeZoom`, `minZoom`, `maxZoom`,
`opacity`, `zIndex`). Tiles are requested to
`/api/tiles/{layer}/{z}/{x}/{y}` on our backend.

Consequences:

- **Adding or changing a layer never requires frontend changes**: edit
  `backend/app/catalog/layers.yaml`.
- **Switching the backend from Earth (NASA APIs) to Mars (local data)
  never requires frontend changes.**

On top of the backend options, the frontend adds only what the user
chose: visibility, opacity and order (see *Layers panel* below). It also
uses the layer's `coverage` as Leaflet `bounds` (no requests outside
THEMIS ±65° or CTX ±88°) and its `blendMode` as a CSS class
(`mix-blend-mode: multiply` for the shaded relief).

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

### Layers panel and legends

- `hooks/useLayerState.js` keeps, per layer, `visible`, `opacity` and the
  order of the overlays. It starts from the backend's `defaultVisible`
  and `opacity`, and saves the user's choices in `localStorage`
  (`arturo.layers.v1`). Unknown or removed layers are ignored, so a
  catalogue change never breaks a saved state. Overlays get
  `zIndex = 10 + position`, always above the base imagery. *Reset*
  restores the defaults.
- `components/LayersPanel.jsx` groups layers by `category` (imagery,
  topography, thermal, surface, composition, geology, hydrology). Each
  row has a large switch, an opacity slider, ▲/▼ buttons to reorder, and
  ⓘ to open its legend. Every control is a real button or slider, at
  least 32–40 px, with no hover-only or right-click actions, so it is
  usable on a touch screen.
- `components/LegendPanel.jsx` (top right) shows the legends of the
  visible layers. It renders `gradient` (colour bar + end labels),
  `categorical` (scrollable list of colour swatches), `channels` (R/G/B
  meanings) and `symbol`. When `quantitative` is `false` it shows a
  *"Qualitative scale – read as relative values"* badge. It always lists
  the notes and the linked sources.

### Map labels and decluttering

`components/FeatureLabels.jsx` draws the IAU names, landing sites and
exploration zones:

1. On every view change (120 ms debounce) it asks the backend for up to
   600 candidates in the visible area plus 25 % padding, for the current
   zoom. The backend has already removed the features that are too small
   for this zoom, and sorts the rest by importance.
2. `map/declutter.js` measures each label's text with a canvas
   (`measureText`, cached) and places labels **greedily in priority
   order**. A label is drawn only if its box (text + dot + 4 px margin)
   does not overlap a box that is already placed. A 64 px grid index
   keeps this fast. At most 160 labels are drawn.
3. The boxes of the user's POIs are **reserved first**, so a feature
   label never covers your own markers.
4. Longitudes are shifted to the copy of the world nearest to the view
   (`nearestLon`), so labels near ±180° are placed correctly.

Result: zoomed out you see regions, big craters and landing sites; zoom
in and smaller names appear as space frees up. Styles: landing sites
(bold, orange), exploration zones (light blue), regions (spaced capitals,
no dot), big features (bold) and normal. Click a label to see its type,
diameter, name origin, source and a link. The Layers panel has switches
for the three label groups (`hooks/useLabelState.js`, saved as
`arturo.labels.v1`).

### Points of interest (POIs)

There is no right-click and no long-press, so it works the same with a
mouse, a touch screen or a gloved finger:

1. Tap the **＋ POI** button (bottom right). A banner says "Tap the map
   to place a point of interest" (`Esc` or *Cancel* stops).
2. Tap the map. A sheet opens with the icon type (resource, shelter,
   hazard, vehicle, unknown, as big buttons), the **name** (the visible
   tag, required, ≤ 60 characters) and **notes**. The current zoom is
   saved as `createdZoom`.
3. Tap a POI marker to see it, then *Edit* or *Delete*. Delete asks for
   confirmation in the same sheet (two steps).

The **POIs** tab lists every POI (world-view ones first, sorted by
`createdZoom`) with its icon and a note on when it shows ("world view" or
"label from zoom N"). Tap one
to fly to it.

Visibility (`map/poiVisibility.js`, numbers from `/api/map` →
`poiVisibility`):

- `createdZoom ≤ 3` → **world-view POI**: icon + name at every zoom.
- otherwise, **local POI**: icon + name when `zoom ≥ createdZoom − 2`,
  a small coloured dot when `zoom ≥ createdZoom − 5`, hidden below that.

The App keeps a small state machine (`idle → placing → create | view →
edit`) in `App.jsx`. All POI calls go through `hooks/usePois.js` →
`api/client.js`.

### Layout

`components/Sidebar.jsx` has three tabs: **Layers**, **POIs** and
**Zones**, and can be collapsed (▸). On screens ≤ 700 px it starts
collapsed and leaves room for the zoom buttons, and the legend panel
moves to the bottom of the screen.

The page itself never scrolls: `.app` is `position: fixed; inset: 0`
with `overflow: clip`, and `html`/`body` have `overflow: hidden`. Panels
scroll inside themselves (`.tab-content`, legend, credits). If you add an
absolutely positioned element inside a panel, keep a positioned ancestor
inside the scrolling element (as `.layer-toggle` does for its hidden
checkbox). Otherwise it escapes the panel's scroll area and can bring
back a page scrollbar, and the page jumps when it receives focus.

**Credits** (`components/CreditsControl.jsx`): Leaflet's attribution bar
is turned off because, with several layers on, it wrapped over the scale
bar. Instead, a small **ⓘ Credits** pill sits in the bottom-right corner
(the scale bar has the bottom-left corner to itself). It opens a panel
that lists the credits of the layers switched on *and drawn at the current
zoom*, the credit lines of the label groups that are on (`/api/map` →
`labelCredits`) and Leaflet. Close it with ✕, the pill or `Esc`. The
bottom-right stack, from the bottom up, is: Credits (12 px), coordinates
readout (56 px), **＋ POI** (124 px). The legend panel always ends above
it.

---

## 4. Features

Phase 1b:

- 16 layers, each one toggleable, with opacity and order, and a legend.
- ~2,100 decluttered labels (IAU names, landing sites, exploration zones).
- Manual POIs: create, view, edit and delete, with zoom-dependent
  visibility.
- Phone-friendly layout.

Phase 1:

- Whole-Mars 2D map with pan, zoom and LOD.
- Cursor latitude/longitude readout (planetocentric, east-positive),
  current zoom and approximate m/px.
- Metric scale bar using the Mars radius.
- Shareable URL: the view is kept in the hash as `#zoom/lat/lon`, e.g.
  `http://localhost:5173/#6/-5.4/137.8` (Gale crater).
- "Detail zones" side menu: click a zone to fly to it. Phase 1 zones
  are a stub ("Detail data coming soon").
- Earth/Mars mode badge.
- Data credits (NASA/JPL/USGS, MSSS, Caltech Murray Lab, Esri…) in the
  **ⓘ Credits** panel (see *Layout*).

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
    ├── hooks/
    │   ├── useBackendData.js # loads health, map, layers, zones, label and POI categories
    │   ├── useLayerState.js  # visible / opacity / order per layer (localStorage)
    │   ├── useLabelState.js  # which label groups are on (localStorage)
    │   └── usePois.js        # POI list + create / update / delete
    ├── map/
    │   ├── crs.js            # Mars CRS (EPSG4326 grid + Mars radius), m/px helper
    │   ├── hash.js           # #zoom/lat/lon helpers
    │   ├── declutter.js      # measureText, grid index, greedy label placement
    │   ├── poiIcons.js       # SVG icons per POI type
    │   └── poiVisibility.js  # createdZoom → full / dot / hidden
    └── components/
        ├── MarsMap.jsx       # MapContainer + TileLayers from /api/layers
        ├── Sidebar.jsx       # tabs: Layers / POIs / Zones, collapsible
        ├── LayersPanel.jsx   # switches, opacity, order, label groups
        ├── LegendPanel.jsx   # legends of the visible layers
        ├── FeatureLabels.jsx # fetch + declutter + draw map labels
        ├── PoiLayer.jsx      # POI markers (icon + name, dot, hidden)
        ├── PoiIcon.jsx       # icon used in lists and forms
        ├── PoiSheet.jsx      # create / view / edit / delete sheet
        ├── PoiPanel.jsx      # POIs tab (list, fly-to)
        ├── CoordinatesReadout.jsx
        ├── HashView.jsx      # keeps the view in the URL hash
        ├── Header.jsx        # title + Earth/Mars badge
        └── ZonesPanel.jsx    # detail-zones list (Zones tab)
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
| No labels | Check the switches under *Map labels* in the Layers tab, and `GET /api/features/categories` on the backend. |
| A layer is on but nothing shows | Its data may not exist at this place or zoom (THEMIS ±65°, coarse TES layers); check its opacity; in Mars mode it may not be in the offline pack. |
| Layer settings look wrong after an update | Press *Reset* in the Layers tab (or clear `arturo.layers.v1` in localStorage). |
| An error message in the POI sheet | The backend is down or rejected the input (the name is required, ≤ 60 characters). The message comes from the API. |
| `npm install` fails on old Node | Install Node 20.19+ or 22.12+ (https://nodejs.org). |
