import { useEffect } from 'react'
import { useMap, useMapEvents } from 'react-leaflet'
import { formatHash, parseHash } from '../map/hash'

/**
 * Keeps the current view in the URL hash (#zoom/lat/lon), e.g.
 * http://localhost:5173/#9/-5.4000/137.8000
 *
 * Handy to share a spot with the team, and it survives page reloads.
 */
export default function HashView() {
  const map = useMap()

  // Apply the hash on load and when the user edits it by hand.
  useEffect(() => {
    const apply = () => {
      const view = parseHash()
      if (view) map.setView([view.lat, view.lon], view.zoom)
    }
    apply()
    window.addEventListener('hashchange', apply)
    return () => window.removeEventListener('hashchange', apply)
  }, [map])

  useMapEvents({
    moveend: () => {
      const c = map.getCenter().wrap()
      const hash = formatHash(map.getZoom(), c.lat, c.lng)
      if (hash !== window.location.hash) window.history.replaceState(null, '', hash)
    },
  })
  return null
}
