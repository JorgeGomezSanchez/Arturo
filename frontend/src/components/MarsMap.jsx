import { useMemo } from 'react'
import { MapContainer, ScaleControl, TileLayer, ZoomControl } from 'react-leaflet'
import 'leaflet/dist/leaflet.css'
import { apiUrl } from '../api/client'
import { createMarsCrs } from '../map/crs'
import CoordinatesReadout from './CoordinatesReadout'
import HashView from './HashView'
import { parseHash } from '../map/hash'

const WHOLE_PLANET = { south: -90, west: -180, north: 90, east: 180 }

function leafletBounds(coverage) {
  // Only pass bounds when the layer does NOT cover the whole planet, so
  // Leaflet skips requests for tiles that cannot exist (e.g. THEMIS poles).
  const c = coverage ?? WHOLE_PLANET
  const whole = c.south <= -90 && c.north >= 90 && c.west <= -180 && c.east >= 180
  return whole
    ? undefined
    : [
        [c.south, c.west],
        [c.north, c.east],
      ]
}

/**
 * Full-screen Mars map.
 *
 * It renders WHATEVER layers the backend announces: it does not know what
 * Viking, CTX or THEMIS are, nor where their tiles come from. Every
 * Leaflet option (tile size, zoom offset, native zoom range, coverage,
 * blend mode...) comes from /api/layers; visibility, opacity and order
 * come from the user's layer state.
 */
export default function MarsMap({ mapConfig, layers, layerState, onMapReady, children }) {
  const crs = useMemo(() => createMarsCrs(mapConfig.radiusM), [mapConfig.radiusM])

  const { minZoom, maxZoom, bounds } = mapConfig
  // Initial view: the URL hash if present (#zoom/lat/lon), else the backend default.
  const initial = useMemo(() => {
    const fromHash = parseHash()
    return fromHash ?? { zoom: mapConfig.zoom, lat: mapConfig.center.lat, lon: mapConfig.center.lon }
  }, [mapConfig])

  const visibleLayers = layers.filter((l) => layerState.settings[l.id]?.visible)

  return (
    <MapContainer
      ref={onMapReady}
      className="mars-map"
      crs={crs}
      center={[initial.lat, initial.lon]}
      zoom={initial.zoom}
      minZoom={minZoom}
      maxZoom={maxZoom}
      // Clamp vertical panning to the poles; longitude wraps around freely
      // (it's a planet), so the horizontal limit is generous.
      maxBounds={[
        [bounds.south, bounds.west - 360],
        [bounds.north, bounds.east + 360],
      ]}
      maxBoundsViscosity={1.0}
      worldCopyJump
      zoomSnap={1}
      zoomControl={false}
      attributionControl
    >
      <ZoomControl position="topright" />
      {visibleLayers.map((layer) => (
        <TileLayer
          key={layer.id}
          url={apiUrl(layer.tileUrl)}
          tileSize={layer.tileSize}
          zoomOffset={layer.zoomOffset}
          minNativeZoom={layer.minNativeZoom}
          maxNativeZoom={layer.maxNativeZoom}
          minZoom={layer.minZoom}
          maxZoom={layer.maxZoom}
          bounds={leafletBounds(layer.coverage)}
          opacity={layerState.settings[layer.id].opacity}
          zIndex={layerState.zIndexOf(layer.id)}
          className={layer.blendMode && layer.blendMode !== 'normal' ? `blend-${layer.blendMode}` : ''}
          attribution={layer.attribution}
          // Keep a few more tiles around so zooming feels smoother.
          keepBuffer={4}
        />
      ))}
      <ScaleControl position="bottomleft" imperial={false} maxWidth={160} />
      <CoordinatesReadout radiusM={mapConfig.radiusM} />
      <HashView />
      {children}
    </MapContainer>
  )
}
