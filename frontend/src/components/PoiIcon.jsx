import { poiSvg } from '../map/poiIcons'

/** Round POI badge (category colour + white icon) for panels and forms. */
export default function PoiIcon({ category, color, size = 32 }) {
  return (
    <span
      className="poi-badge"
      style={{ '--poi-color': color, width: size, height: size }}
      // Static, trusted SVG strings from map/poiIcons.js (no user input).
      dangerouslySetInnerHTML={{ __html: poiSvg(category, Math.round(size * 0.62)) }}
    />
  )
}
