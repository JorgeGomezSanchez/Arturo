/**
 * Arturo backend client.
 *
 * This is the ONLY file that knows how to reach the backend. The rest of
 * the app calls these functions and never talks to NASA (or anything
 * else) directly. Whether the backend gets its data from Earth APIs or
 * from a local Martian store is invisible from here.
 *
 * Base URL: VITE_API_URL (see .env.example). Empty by default, meaning
 * "same origin": in development the Vite proxy forwards /api to FastAPI.
 */

const API_URL = (import.meta.env.VITE_API_URL ?? '').replace(/\/$/, '')

/** Absolute URL for a backend path such as "/api/layers". */
export function apiUrl(path) {
  return `${API_URL}${path}`
}

async function getJson(path) {
  const res = await fetch(apiUrl(path))
  if (!res.ok) {
    throw new Error(`GET ${path} -> HTTP ${res.status}`)
  }
  return res.json()
}

/** Backend status: { status, version, dataSource: "remote"|"local", ... } */
export const getHealth = () => getJson('/api/health')

/** Map settings: CRS, radius, initial view, zoom limits, bounds. */
export const getMapConfig = () => getJson('/api/map')

/**
 * Available layers. Each one already carries Leaflet-ready options
 * (tileUrl, tileSize, zoomOffset, min/maxNativeZoom, ...).
 */
export const getLayers = () => getJson('/api/layers')

/** Detail zones for the side menu. */
export const getZones = () => getJson('/api/zones')
