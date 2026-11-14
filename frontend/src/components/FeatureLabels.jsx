import { useEffect, useMemo, useRef, useState } from 'react'
import L from 'leaflet'
import { Marker, Popup, useMap, useMapEvents } from 'react-leaflet'
import { getFeatures } from '../api/client'
import { declutter, measureText, nearestLon } from '../map/declutter'
import { POI_DOT_SIZE, POI_ICON_SIZE, poiDisplayMode } from '../map/poiVisibility'

const FETCH_LIMIT = 600 // candidates asked to the backend per view
const MAX_LABELS = 160 // drawn on screen at most
const PAD_FRACTION = 0.25 // fetch a bit beyond the view so panning is smooth
const REGION_CATEGORIES = new Set(['terra', 'planitia', 'vastitas', 'planum', 'albedo', 'palus'])

// Visual styles. Fonts must match .flabel-* in App.css (used to measure).
const STYLES = {
  site: { font: '700 12px system-ui, sans-serif', className: 'flabel flabel-site', marker: true },
  ez: { font: '600 12px system-ui, sans-serif', className: 'flabel flabel-ez', marker: true },
  region: { font: '600 12px system-ui, sans-serif', className: 'flabel flabel-region', marker: false, spacing: 1.5, upper: true },
  big: { font: '700 13px system-ui, sans-serif', className: 'flabel flabel-big', marker: true },
  normal: { font: '500 12px system-ui, sans-serif', className: 'flabel', marker: true },
}

function styleOf(p) {
  if (p.category === 'landing_site') return 'site'
  if (p.category === 'exploration_zone') return 'ez'
  if (REGION_CATEGORIES.has(p.category)) return 'region'
  if (p.priority >= 3) return 'big'
  return 'normal'
}

function escapeHtml(s) {
  return s.replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c])
}

const H = 18 // label height in px

/** Screen box + Leaflet icon geometry for a label anchored at point (x, y). */
function layout(text, styleKey) {
  const st = STYLES[styleKey]
  const shown = st.upper ? text.toUpperCase() : text
  const w = measureText(shown, st.font) + (st.spacing ? st.spacing * shown.length : 0)
  if (st.marker) {
    // [marker 10px][gap 4px][text] with the marker centred on the point
    return { shown, w: w + 14, anchor: [5, H / 2], dx1: -5, dx2: w + 9 }
  }
  return { shown, w, anchor: [w / 2, H / 2], dx1: -w / 2, dx2: w / 2 }
}

const iconCache = new Map()
function iconFor(id, shown, styleKey, w, anchor) {
  const key = `${id}|${styleKey}`
  let icon = iconCache.get(key)
  if (!icon) {
    const st = STYLES[styleKey]
    icon = L.divIcon({
      className: st.className,
      html: `${st.marker ? '<span class="flabel-mark"></span>' : ''}<span class="flabel-text">${escapeHtml(shown)}</span>`,
      iconSize: [Math.ceil(w), H],
      iconAnchor: anchor,
    })
    if (iconCache.size > 4000) iconCache.clear()
    iconCache.set(key, icon)
  }
  return icon
}

function viewOf(map) {
  return { zoom: map.getZoom(), bounds: map.getBounds(), center: map.getCenter(), size: map.getSize() }
}

function formatCoord(lat, lon) {
  const wrapped = ((lon + 540) % 360) - 180
  return `${Math.abs(lat).toFixed(2)}° ${lat >= 0 ? 'N' : 'S'}, ${Math.abs(wrapped).toFixed(2)}° ${wrapped >= 0 ? 'E' : 'W'}`
}

/**
 * Named-feature labels (IAU names, landing sites, exploration zones).
 *
 * 1. On every move/zoom it asks the backend for the features in (a
 *    padded version of) the view whose minZoom <= zoom, already sorted
 *    by priority. Responses are cached per (zoom, bbox) and stale
 *    requests are aborted.
 * 2. It projects them to screen pixels, measures each label and runs the
 *    greedy collision pass (map/declutter.js): important labels win,
 *    overlapping smaller ones are hidden until you zoom in. Boxes of user
 *    POIs are reserved first, so names never cover your own markers.
 * 3. Tapping a label opens a popup with the feature's details (disabled
 *    while placing a POI, so the tap goes to the map).
 */
export default function FeatureLabels({ categories, enabled, pois, poiRules, interactive = true }) {
  const map = useMap()
  const [view, setView] = useState(() => viewOf(map))
  const [features, setFeatures] = useState([])
  const [selected, setSelected] = useState(null)
  const cache = useRef(new Map())

  useMapEvents({
    moveend: () => setView(viewOf(map)),
    zoomend: () => setView(viewOf(map)),
    resize: () => setView(viewOf(map)),
  })

  // ---- 1. fetch candidates for the (padded) view ----
  const query = useMemo(() => {
    if (!enabled) return null
    const b = view.bounds
    const dLon = (b.getEast() - b.getWest()) * PAD_FRACTION
    const dLat = (b.getNorth() - b.getSouth()) * PAD_FRACTION
    // Round so that small pans reuse the cached answer.
    const step = 180 / 2 ** Math.max(view.zoom, 0) / 4
    const r = (v, f) => f(v / step) * step
    return {
      zoom: view.zoom,
      bbox: [
        r(b.getWest() - dLon, Math.floor),
        Math.max(-90, r(b.getSouth() - dLat, Math.floor)),
        r(b.getEast() + dLon, Math.ceil),
        Math.min(90, r(b.getNorth() + dLat, Math.ceil)),
      ],
      categories,
      limit: FETCH_LIMIT,
    }
  }, [enabled, view, categories])

  useEffect(() => {
    if (!query) {
      setFeatures([])
      return
    }
    const key = JSON.stringify(query)
    const hit = cache.current.get(key)
    if (hit) {
      setFeatures(hit)
      return
    }
    const ctrl = new AbortController()
    const t = setTimeout(() => {
      getFeatures(query, ctrl.signal)
        .then((fc) => {
          if (cache.current.size > 60) cache.current.clear()
          cache.current.set(key, fc.features)
          setFeatures(fc.features)
        })
        .catch((e) => {
          if (e.name !== 'AbortError') console.warn('labels:', e.message)
        })
    }, 120) // debounce bursts of move events
    return () => {
      clearTimeout(t)
      ctrl.abort()
    }
  }, [query])

  // ---- 2. project + declutter ----
  const placed = useMemo(() => {
    if (!enabled) return []
    const { x: W, y: Hh } = view.size
    const centerLon = view.center.lng
    const reserved = []
    for (const poi of pois ?? []) {
      const [lon, lat] = poi.geometry.coordinates
      const mode = poiDisplayMode(poi.properties.createdZoom, view.zoom, poiRules)
      if (mode === 'hidden') continue
      const p = map.latLngToContainerPoint([lat, nearestLon(lon, centerLon)])
      if (mode === 'dot') {
        const r = POI_DOT_SIZE / 2
        reserved.push({ x1: p.x - r, y1: p.y - r, x2: p.x + r, y2: p.y + r })
      } else {
        // icon above the point + name pill below it
        const labelW = Math.max(POI_ICON_SIZE, measureText(poi.properties.name, '600 12px system-ui, sans-serif') + 16)
        reserved.push({ x1: p.x - POI_ICON_SIZE / 2, y1: p.y - POI_ICON_SIZE, x2: p.x + POI_ICON_SIZE / 2, y2: p.y })
        reserved.push({ x1: p.x - labelW / 2, y1: p.y, x2: p.x + labelW / 2, y2: p.y + 22 })
      }
    }
    const candidates = []
    for (const f of features) {
      const [lon0, lat] = f.geometry.coordinates
      const lon = nearestLon(lon0, centerLon)
      const p = map.latLngToContainerPoint([lat, lon])
      if (p.x < -50 || p.y < -20 || p.x > W + 50 || p.y > Hh + 20) continue
      const styleKey = styleOf(f.properties)
      const lay = layout(f.properties.name, styleKey)
      candidates.push({
        f,
        lat,
        lon,
        styleKey,
        lay,
        box: { x1: p.x + lay.dx1, y1: p.y - H / 2, x2: p.x + lay.dx2, y2: p.y + H / 2 },
      })
    }
    // Backend order is already priority-desc; keep it stable.
    return declutter(candidates, reserved, { maxLabels: MAX_LABELS })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [features, view, enabled, pois, poiRules])

  if (!enabled) return null

  return (
    <>
      {placed.map(({ f, lat, lon, styleKey, lay }) => (
        <Marker
          key={f.id}
          position={[lat, lon]}
          icon={iconFor(f.id, lay.shown, styleKey, lay.w, lay.anchor)}
          interactive={interactive}
          keyboard={false}
          zIndexOffset={-1000}
          eventHandlers={{ click: () => setSelected({ f, lat, lon }) }}
        />
      ))}
      {selected && (
        <Popup
          position={[selected.lat, selected.lon]}
          eventHandlers={{ remove: () => setSelected(null) }}
          className="feature-popup"
        >
          <FeatureDetails feature={selected.f} />
        </Popup>
      )}
    </>
  )
}

function FeatureDetails({ feature }) {
  const p = feature.properties
  const [lon, lat] = feature.geometry.coordinates
  return (
    <div className="feature-details">
      <strong>{p.name}</strong>
      <div className="muted">{p.typeLabel}</div>
      <div>
        {formatCoord(lat, lon)}
        {p.diameterKm ? ` · ⌀ ${p.diameterKm >= 10 ? Math.round(p.diameterKm) : p.diameterKm.toFixed(1)} km` : ''}
      </div>
      {p.origin && <p>{p.origin}</p>}
      <div className="muted small">
        {p.source}
        {p.link && (
          <>
            {' · '}
            <a href={p.link} target="_blank" rel="noreferrer">
              details
            </a>
          </>
        )}
      </div>
    </div>
  )
}
