import { useState } from 'react'
import { useMapEvents } from 'react-leaflet'
import { metersPerPixel } from '../map/crs'

function formatLat(lat) {
  return `${Math.abs(lat).toFixed(4)}° ${lat >= 0 ? 'N' : 'S'}`
}

function formatLon(lon) {
  return `${Math.abs(lon).toFixed(4)}° ${lon >= 0 ? 'E' : 'W'}`
}

function formatDistance(m) {
  return m >= 1000 ? `${(m / 1000).toFixed(1)} km` : `${m.toFixed(1)} m`
}

/**
 * Bottom-right readout: cursor latitude/longitude (planetocentric,
 * east-positive, like NASA Mars Trek), current zoom and approximate
 * ground resolution.
 */
export default function CoordinatesReadout({ radiusM }) {
  const [cursor, setCursor] = useState(null)
  const map = useMapEvents({
    mousemove: (e) => setCursor(e.latlng.wrap()), // wrap lon to -180..180
    mouseout: () => setCursor(null),
    zoomend: () => setZoom(map.getZoom()),
  })
  const [zoom, setZoom] = useState(() => map.getZoom())

  return (
    <div className="hud coords-readout">
      <div>{cursor ? `${formatLat(cursor.lat)}  ${formatLon(cursor.lng)}` : '—'}</div>
      <div className="muted">
        zoom {zoom} · ~{formatDistance(metersPerPixel(radiusM, zoom))}/px
      </div>
    </div>
  )
}
