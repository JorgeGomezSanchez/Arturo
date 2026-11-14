import { useMemo } from 'react'
import { MapContainer, ScaleControl, TileLayer, ZoomControl } from 'react-leaflet'
import 'leaflet/dist/leaflet.css'
import { apiUrl } from '../api/client'
import { createMarsCrs } from '../map/crs'
import CoordinatesReadout from './CoordinatesReadout'
import HashView from './HashView'
import { parseHash } from '../map/hash'

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

  const { minZoom, maxZoom, bounds } = mapConfig
  // Initial view: the URL hash if present (#zoom/lat/lon), else the backend default.
  const initial = useMemo(() => {
    const fromHash = parseHash()
    return fromHash ?? { zoom: mapConfig.zoom, lat: mapConfig.center.lat, lon: mapConfig.center.lon }
  }, [mapConfig])

  return (
    <MapContainer
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
      <CoordinatesReadout radiusM={mapConfig.radiusM} />
      <HashView />
      {children}
    </MapContainer>
  )
}
