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

/** Error thrown for non-2xx answers; carries the HTTP status and detail. */
export class ApiError extends Error {
  constructor(method, path, status, detail) {
    super(`${method} ${path} -> HTTP ${status}${detail ? `: ${detail}` : ''}`)
    this.status = status
    this.detail = detail
  }
}

async function request(method, path, { body, signal, query } = {}) {
  const qs = query
    ? '?' +
      new URLSearchParams(
        Object.entries(query).filter(([, v]) => v !== undefined && v !== null && v !== ''),
      ).toString()
    : ''
  const res = await fetch(apiUrl(path + qs), {
    method,
    signal,
    headers: body ? { 'Content-Type': 'application/json' } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  })
  if (!res.ok) {
    let detail = ''
    try {
      const payload = await res.json()
      detail = typeof payload.detail === 'string' ? payload.detail : JSON.stringify(payload.detail)
    } catch {
      /* not JSON */
    }
    throw new ApiError(method, path, res.status, detail)
  }
  return res.status === 204 ? null : res.json()
}

const getJson = (path, opts) => request('GET', path, opts)

/** Backend status: { status, version, dataSource: "remote"|"local", ... } */
export const getHealth = () => getJson('/api/health')

/** Map settings: CRS, radius, initial view, zoom limits, bounds, poiVisibility. */
export const getMapConfig = () => getJson('/api/map')

/**
 * Available layers. Each one already carries Leaflet-ready options
 * (tileUrl, tileSize, zoomOffset, min/maxNativeZoom, ...) plus its
 * category, coverage, blend mode and legend.
 */
export const getLayers = () => getJson('/api/layers')

/** Detail zones for the side menu. */
export const getZones = () => getJson('/api/zones')

/**
 * Named features (labels) for a view, highest priority first.
 * bbox = [west, south, east, north] (longitudes may be unwrapped).
 */
export const getFeatures = ({ bbox, zoom, categories, limit }, signal) =>
  getJson('/api/features', {
    signal,
    query: {
      bbox: bbox?.map((v) => v.toFixed(4)).join(','),
      zoom,
      categories: categories?.join(','),
      limit,
    },
  })

/** Feature categories with labels and counts. */
export const getFeatureCategories = () => getJson('/api/features/categories')

/** Selectable POI types: [{ id, label, description, color }]. */
export const getPoiCategories = () => getJson('/api/pois/categories')

/** All user POIs as a GeoJSON FeatureCollection. */
export const getPois = () => getJson('/api/pois')

/**
 * Create a POI. data = { name, category, notes, lat, lon, createdZoom }.
 * Returns the stored GeoJSON Feature.
 */
export const createPoi = (data) => request('POST', '/api/pois', { body: data })

/** Replace a POI's fields (same shape as createPoi). */
export const updatePoi = (id, data) =>
  request('PUT', `/api/pois/${encodeURIComponent(id)}`, { body: data })

/** Delete a POI. */
export const deletePoi = (id) => request('DELETE', `/api/pois/${encodeURIComponent(id)}`)
