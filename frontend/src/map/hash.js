/**
 * URL hash <-> map view helpers. Format: #zoom/lat/lon
 * e.g. #9/-5.4000/137.8000
 */
export function parseHash(hash = window.location.hash) {
  const parts = hash.replace('#', '').split('/').map(Number)
  if (parts.length !== 3 || !parts.every(Number.isFinite)) return null
  const [zoom, lat, lon] = parts
  return { zoom, lat, lon }
}

export function formatHash(zoom, lat, lon) {
  return `#${zoom}/${lat.toFixed(4)}/${lon.toFixed(4)}`
}
