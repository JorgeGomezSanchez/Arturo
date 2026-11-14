import { useState } from 'react'

const STATUS_LABEL = {
  available: 'Detailed data',
  planned: 'Detail data coming soon',
}

/**
 * Side menu with the detail zones announced by GET /api/zones.
 * Tapping a zone flies the map to it. Rendered inside the sidebar's
 * "Zones" tab.
 *
 * Phase 1: zones are a stub (status "planned"): auto-zoom works, but the
 * detailed layers (HiRISE, DTM, POIs, routes) arrive in later phases.
 * New zones appear here just by adding them to backend map.yaml.
 */
export default function ZonesPanel({ map, zones, mapConfig }) {
  const [activeId, setActiveId] = useState(null)

  const flyToZone = (zone) => {
    if (!map) return
    const { south, west, north, east } = zone.bounds
    setActiveId(zone.id)
    map.flyToBounds(
      [
        [south, west],
        [north, east],
      ],
      { duration: 1.5 },
    )
  }

  const flyHome = () => {
    if (!map) return
    setActiveId(null)
    map.flyTo([mapConfig.center.lat, mapConfig.center.lon], mapConfig.zoom, { duration: 1.5 })
  }

  return (
    <div className="zones-panel">
      <p className="muted panel-hint">Tap a zone to fly there.</p>
      <ul className="zones-list">
          <li>
            <button className="zone-item" onClick={flyHome}>
              <strong>Whole planet</strong>
              <span className="muted">Global view</span>
            </button>
          </li>
          {zones.map((zone) => (
            <li key={zone.id}>
              <button
                className={`zone-item ${activeId === zone.id ? 'active' : ''}`}
                onClick={() => flyToZone(zone)}
                title={zone.description}
              >
                <strong>{zone.name}</strong>
                <span className="muted">
                  {zone.center.lat.toFixed(1)}°, {zone.center.lon.toFixed(1)}°
                </span>
                <span className={`zone-status status-${zone.status}`}>
                  {STATUS_LABEL[zone.status] ?? zone.status}
                </span>
              </button>
            </li>
          ))}
      </ul>
    </div>
  )
}
