/**
 * Route helpers shared by the map layer and the panel: severity colours
 * (display only; every threshold lives in the backend's routes.yaml),
 * snapping a tap to a POI or a named feature, longitude unwrapping and
 * formatting.
 */
import { getFeatures } from '../api/client'
import { nearestLon } from './declutter'

export const LEVEL_COLORS = {
  ok: '#4cc36e',
  info: '#4cc36e', // info is not a hazard on the line: drawn as ok
  warning: '#f2b134',
  danger: '#ea4b3c',
  noData: '#9a9a9a',
}

/** Colours of hazard badges/zones (info gets its own neutral blue). */
export const SEVERITY_COLORS = { info: '#7fa3c0', warning: '#f2b134', danger: '#ea4b3c' }

export const SEVERITY_LABEL = { info: 'Info', warning: 'Warning', danger: 'Danger' }

export const SNAP_PX = 28 // a tap this close to a POI or label snaps to it

/** Unwrap [[lon, lat], ...] so consecutive points never jump 360°. */
export function unwrapLine(coords, refLon) {
  const out = []
  let prev = refLon
  for (const [lon, lat] of coords) {
    const l = prev === undefined ? lon : nearestLon(lon, prev)
    out.push([lat, l])
    prev = l
  }
  return out // Leaflet [lat, lng]
}

export function wrapLon(lon) {
  return ((((lon + 180) % 360) + 360) % 360) - 180
}

export function formatLatLon(lat, lon) {
  const w = wrapLon(lon)
  return `${Math.abs(lat).toFixed(3)}° ${lat >= 0 ? 'N' : 'S'}, ${Math.abs(w).toFixed(3)}° ${w >= 0 ? 'E' : 'W'}`
}

function shortLatLon(lat, lon) {
  const w = wrapLon(lon)
  return `${Math.abs(lat).toFixed(2)}°${lat >= 0 ? 'N' : 'S'} ${Math.abs(w).toFixed(2)}°${w >= 0 ? 'E' : 'W'}`
}

export function formatKm(m) {
  if (m == null) return '–'
  return m < 1000 ? `${Math.round(m)} m` : `${(m / 1000).toFixed(m < 10000 ? 2 : 1)} km`
}

export function formatHours(h) {
  if (h == null) return '–'
  const hh = Math.floor(h)
  const mm = Math.round((h - hh) * 60)
  return hh ? `${hh} h ${String(mm).padStart(2, '0')} min` : `${mm} min`
}

/**
 * What does a tap at `latlng` mean? Nearest POI within SNAP_PX, else the
 * nearest named feature within SNAP_PX (asked to the backend, same
 * filters as the visible labels), else a free point. Returns a route end
 * { kind, refId, name, lat, lon }.
 */
export async function snapRouteEnd(map, latlng, { pois = [], categories, labelsOn }) {
  const tap = map.latLngToContainerPoint(latlng)
  const centerLon = latlng.lng
  let best = null
  for (const poi of pois) {
    const [lon, lat] = poi.geometry.coordinates
    const p = map.latLngToContainerPoint([lat, nearestLon(lon, centerLon)])
    const d = p.distanceTo(tap)
    if (d <= SNAP_PX && (!best || d < best.d)) best = { d, end: { kind: 'poi', refId: poi.id, name: poi.properties.name, lat, lon } }
  }
  if (best) return best.end

  // categories: null = every label family, [] = none
  if (labelsOn && (categories === null || categories?.length)) {
    const a = map.containerPointToLatLng([tap.x - SNAP_PX, tap.y + SNAP_PX])
    const b = map.containerPointToLatLng([tap.x + SNAP_PX, tap.y - SNAP_PX])
    try {
      const fc = await getFeatures({
        bbox: [a.lng, a.lat, b.lng, b.lat],
        zoom: map.getZoom(),
        categories: categories ?? undefined,
        limit: 30,
      })
      for (const f of fc.features) {
        const [lon, lat] = f.geometry.coordinates
        const p = map.latLngToContainerPoint([lat, nearestLon(lon, centerLon)])
        const d = p.distanceTo(tap)
        if (d <= SNAP_PX && (!best || d < best.d)) best = { d, end: { kind: 'feature', refId: f.id, name: f.properties.name, lat, lon } }
      }
    } catch (e) {
      console.warn('route snap:', e.message)
    }
    if (best) return best.end
  }
  const w = latlng.wrap()
  return { kind: 'point', refId: null, name: '', lat: w.lat, lon: w.lng }
}

/** Display name of a route end. */
export function endName(end) {
  return end?.name || (end ? formatLatLon(end.lat, end.lon) : '')
}

/** Default route name "A → B" (backend limit: 60 characters). */
export function defaultRouteName(start, end) {
  const s = (x) => (x.name ? x.name.replace(/^EZ: /, '') : shortLatLon(x.lat, x.lon))
  const name = `${s(start)} → ${s(end)}`
  return name.length > 60 ? `${name.slice(0, 59)}…` : name
}

/** [[lon, lat], ...] of A, waypoints, B. */
export function routeCoordinates(draft) {
  return [[draft.start.lon, draft.start.lat], ...draft.waypoints, [draft.end.lon, draft.end.lat]]
}
