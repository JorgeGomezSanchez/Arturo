/**
 * POI icons as inline SVG (24x24 viewBox, drawn in white on the category
 * colour). Keyed by the POI category ids announced by the backend
 * (GET /api/pois/categories). An unknown id falls back to 'unknown', so a
 * new backend category still renders.
 *
 * Kept as strings because Leaflet divIcons take HTML; React components
 * use them through <PoiIcon/> (components/PoiIcon.jsx).
 */
const BG = 'var(--poi-color, #555)'

export const POI_ICON_SVG = {
  // Droplet: water ice, minerals, supplies
  resource: `<path fill="#fff" d="M12 2.5S5.5 9.6 5.5 14.2a6.5 6.5 0 0 0 13 0C18.5 9.6 12 2.5 12 2.5z"/><path fill="${BG}" d="M9.2 14.6a2.8 2.8 0 0 0 2.8 2.8v1.6a4.4 4.4 0 0 1-4.4-4.4z"/>`,
  // Dome habitat with a door
  shelter: `<path fill="#fff" d="M2.5 19.5h19v-1.2a9.5 9.5 0 0 0-19 0z"/><rect fill="${BG}" x="10" y="14.5" width="4" height="5" rx="1"/><rect fill="#fff" x="1.5" y="19.5" width="21" height="1.6" rx=".8"/>`,
  // Warning triangle
  hazard: `<path fill="#fff" d="M12 2.2 1.2 21h21.6z"/><rect fill="${BG}" x="10.9" y="8.5" width="2.2" height="7" rx="1"/><circle fill="${BG}" cx="12" cy="18" r="1.3"/>`,
  // Rover: mast camera, body, three wheels
  vehicle: `<rect fill="#fff" x="7" y="2.5" width="5" height="2.6" rx=".6"/><rect fill="#fff" x="8.6" y="4.5" width="1.8" height="4"/><path fill="#fff" d="M3.5 8.5h12.2l4.3 5.2v2.3H3.5z"/><circle fill="#fff" cx="6" cy="18.3" r="2.5"/><circle fill="#fff" cx="12" cy="18.3" r="2.5"/><circle fill="#fff" cx="18" cy="18.3" r="2.5"/>`,
  // Question mark
  unknown: `<text x="12" y="18.5" fill="#fff" font-family="system-ui, sans-serif" font-size="18" font-weight="800" text-anchor="middle">?</text>`,
}

export function poiSvg(category, size = 20) {
  const body = POI_ICON_SVG[category] ?? POI_ICON_SVG.unknown
  return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" width="${size}" height="${size}" aria-hidden="true">${body}</svg>`
}
