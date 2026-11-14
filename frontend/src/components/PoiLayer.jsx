import { useState } from 'react'
import L from 'leaflet'
import { Marker, useMap, useMapEvents } from 'react-leaflet'
import { nearestLon } from '../map/declutter'
import { poiSvg } from '../map/poiIcons'
import { POI_DOT_SIZE, POI_ICON_SIZE, poiDisplayMode } from '../map/poiVisibility'

function escapeHtml(s) {
  return s.replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c])
}

function fullIcon(name, category, color, selected) {
  return L.divIcon({
    className: `poi-marker poi-full ${selected ? 'selected' : ''}`,
    html: `<div class="poi-pin" style="--poi-color:${color}">${poiSvg(category, 20)}</div><div class="poi-name">${escapeHtml(name)}</div>`,
    iconSize: [POI_ICON_SIZE, POI_ICON_SIZE],
    iconAnchor: [POI_ICON_SIZE / 2, POI_ICON_SIZE], // tip of the pin on the point
  })
}

function dotIcon(color, selected) {
  return L.divIcon({
    className: `poi-marker poi-dot ${selected ? 'selected' : ''}`,
    html: `<div style="--poi-color:${color}"></div>`,
    iconSize: [POI_DOT_SIZE, POI_DOT_SIZE],
    iconAnchor: [POI_DOT_SIZE / 2, POI_DOT_SIZE / 2],
  })
}

/**
 * Draws user POIs following the zoom rules of map/poiVisibility.js
 * (full icon + label, small dot, or hidden), plus the draft marker while
 * a new POI is being placed. Taps call onSelect(poi).
 *
 * Also hosts the "placing" tap handler: while placing, a tap anywhere on
 * the map calls onPlace({lat, lon, zoom}). A normal tap/click is used on
 * purpose (no right-click, no long-press), so it works on touch screens.
 */
export default function PoiLayer({ pois, rules, colors, selectedId, onSelect, placing, onPlace, draft }) {
  const map = useMap()
  const [zoom, setZoom] = useState(() => map.getZoom())
  const [centerLon, setCenterLon] = useState(() => map.getCenter().lng)

  useMapEvents({
    zoomend: () => setZoom(map.getZoom()),
    moveend: () => setCenterLon(map.getCenter().lng),
    click: (e) => {
      if (!placing) return
      onPlace({ lat: e.latlng.lat, lon: e.latlng.lng, zoom: map.getZoom() })
    },
  })

  return (
    <>
      {pois.map((poi) => {
        const { name, category, createdZoom } = poi.properties
        const mode = poiDisplayMode(createdZoom, zoom, rules)
        if (mode === 'hidden') return null
        const [lon, lat] = poi.geometry.coordinates
        const color = colors[category] ?? '#999'
        const selected = poi.id === selectedId
        return (
          <Marker
            key={poi.id}
            position={[lat, nearestLon(lon, centerLon)]}
            icon={mode === 'full' ? fullIcon(name, category, color, selected) : dotIcon(color, selected)}
            zIndexOffset={mode === 'full' ? 1000 : 500}
            interactive={!placing}
            eventHandlers={{ click: () => onSelect(poi) }}
            title={name}
          />
        )
      })}
      {draft && (
        <Marker
          position={[draft.lat, draft.lon]}
          icon={fullIcon(draft.name || 'New POI', draft.category, colors[draft.category] ?? '#999', true)}
          zIndexOffset={2000}
          interactive={false}
        />
      )}
    </>
  )
}
