import { useMemo } from 'react'
import { MapContainer, ScaleControl, TileLayer } from 'react-leaflet'
import 'leaflet/dist/leaflet.css'
import { apiUrl } from '../api/client'
import { createMarsCrs } from '../map/crs'

/**
 * Full-screen Mars map.
 *
 * It renders WHATEVER layers the backend announces: it does not know what
 * Viking or CTX are, nor where their tiles come from. Every Leaflet option
 * (tile size, zoom offset, native zoom range...) comes from /api/layers.
 */
export default function MarsMap({ mapConfig, layers, children }) {
  const crs = useMemo(() => createMarsCrs(mapConfig.radiusM), [mapConfig.radiusM])

  const baseLayers = useMemo(
    () => layers.filter((l) => l.group === 'base').sort((a, b) => a.zIndex - b.zIndex),
    [layers],
  )

  const { center, zoom, minZoom, maxZoom, bounds } = mapConfig

  return (
    <MapContainer
      className="mars-map"
      crs={crs}
      center={[center.lat, center.lon]}
      zoom={zoom}
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
    >
      {baseLayers.map((layer) => (
        <TileLayer
          key={layer.id}
          url={apiUrl(layer.tileUrl)}
          tileSize={layer.tileSize}
          zoomOffset={layer.zoomOffset}
          minNativeZoom={layer.minNativeZoom}
          maxNativeZoom={layer.maxNativeZoom}
          minZoom={layer.minZoom}
          maxZoom={layer.maxZoom}
          opacity={layer.opacity}
          zIndex={layer.zIndex}
          attribution={layer.attribution}
          // Keep a few more tiles around so zooming feels smoother.
          keepBuffer={4}
        />
      ))}
      <ScaleControl position="bottomleft" imperial={false} maxWidth={160} />
      {children}
    </MapContainer>
  )
}
