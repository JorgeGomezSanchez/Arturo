import { useEffect, useRef } from 'react'
import L from 'leaflet'
import { Marker, useMap, useMapEvents } from 'react-leaflet'

const DOUBLE_TAP_MS = 280 // wait this long so a double-tap zoom is not a query
const PANEL_W = 400 // desktop side panel width + margin (App.css .point-panel)
const SHEET_TOP = 0.38 // phones: the bottom sheet covers the lower 62 %

/** Pan just enough that the queried point is not hidden under the panel. */
function keepVisible(map, point) {
  const size = map.getSize()
  const p = map.latLngToContainerPoint([point.lat, point.lon])
  const phone = window.matchMedia?.('(max-width: 700px)').matches
  let dx = 0
  let dy = 0
  if (phone) {
    const limit = size.y * SHEET_TOP - 24
    if (p.y > limit) dy = p.y - size.y * SHEET_TOP * 0.55
  } else if (p.x > size.x - PANEL_W) {
    dx = p.x - (size.x - PANEL_W) / 2
  }
  if (dx || dy) map.panBy([dx, dy], { animate: true })
}

const markerIcon = L.divIcon({
  className: 'point-marker',
  html: '<span class="point-marker-ring"></span><span class="point-marker-dot"></span>',
  iconSize: [36, 36],
  iconAnchor: [18, 18],
})

/**
 * Map tap/click -> onQuery({lat, lon}) and the marker at the queried point.
 *
 * Conflicts avoided:
 * - disabled while the POI layer is placing (or editing) a POI (`enabled`);
 * - taps on labels and POI markers never reach the map (Leaflet markers
 *   do not bubble), so they keep opening their own popup/sheet;
 * - the tap that closes an open label popup only closes it;
 * - double-click / double-tap zooms without opening the panel;
 * - drags (panning) never fire a click.
 */
export default function PointQuery({ enabled, point, onQuery }) {
  const map = useMap()
  const timer = useRef(null)
  const popupClosedAt = useRef(0)

  useMapEvents({
    popupclose: () => {
      popupClosedAt.current = performance.now()
    },
    click: (e) => {
      if (!enabled) return
      if (performance.now() - popupClosedAt.current < 100) return
      const { lat, lng } = e.latlng.wrap()
      clearTimeout(timer.current)
      timer.current = setTimeout(() => onQuery({ lat, lon: lng }), DOUBLE_TAP_MS)
    },
    dblclick: () => clearTimeout(timer.current),
    zoomstart: () => clearTimeout(timer.current),
  })
  useEffect(() => () => clearTimeout(timer.current), [])
  useEffect(() => {
    if (point) keepVisible(map, point)
  }, [map, point])

  if (!point) return null
  return <Marker position={[point.lat, point.lon]} icon={markerIcon} interactive={false} zIndexOffset={3000} />
}
