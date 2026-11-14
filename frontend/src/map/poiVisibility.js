/**
 * How a user POI is drawn at the current zoom, from the zoom it was
 * created at and the backend rules (GET /api/map -> poiVisibility):
 *
 *   'full'   icon + name label
 *   'dot'    small coloured dot (tap it to open the POI)
 *   'hidden' not drawn (still listed in the POIs tab)
 *
 * With c = createdZoom and z = current zoom:
 *   c <= worldZoom                  -> 'full' always (world-view POI)
 *   z >= c - labelZoomMargin        -> 'full'
 *   z >= c - markerZoomMargin       -> 'dot'
 *   otherwise                       -> 'hidden'
 */
export function poiDisplayMode(createdZoom, zoom, rules) {
  const { labelZoomMargin = 2, markerZoomMargin = 5, worldZoom = 3 } = rules ?? {}
  if (createdZoom <= worldZoom) return 'full'
  if (zoom >= createdZoom - labelZoomMargin) return 'full'
  if (zoom >= createdZoom - markerZoomMargin) return 'dot'
  return 'hidden'
}

/** Lowest zoom at which the POI label is shown (for the UI hint). */
export function poiLabelMinZoom(createdZoom, rules) {
  const { labelZoomMargin = 2, worldZoom = 3 } = rules ?? {}
  return createdZoom <= worldZoom ? 0 : Math.max(0, createdZoom - labelZoomMargin)
}

// Screen footprint of a POI marker (see .poi-marker in App.css), used to
// keep feature labels away from user POIs.
export const POI_ICON_SIZE = 34
export const POI_DOT_SIZE = 14
