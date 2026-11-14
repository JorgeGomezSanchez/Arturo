import L from 'leaflet'

/**
 * Coordinate Reference System for Mars.
 *
 * NASA Mars Trek tiles are equirectangular ("plate carrée"): longitude and
 * latitude map linearly to x and y, and level 0 is 2 tiles wide x 1 tall.
 * That is exactly Leaflet's built-in L.CRS.EPSG4326 grid, so tiles line up
 * and the lat/lon we read are real Martian coordinates.
 *
 * The only change: EPSG4326 inherits Earth's radius (6371 km), which
 * Leaflet uses to measure distances (scale bar). We override it with the
 * Mars radius sent by the backend, otherwise the scale bar would be ~1.9x
 * wrong.
 */
export function createMarsCrs(radiusM) {
  return L.Util.extend({}, L.CRS.EPSG4326, {
    code: 'IAU2000:49900-EQ', // informative only
    R: radiusM,
  })
}

/** Approximate ground resolution (metres per screen pixel) at the equator. */
export function metersPerPixel(radiusM, zoom) {
  // At zoom z the full 360° circumference spans 512 * 2^z pixels.
  return (2 * Math.PI * radiusM) / (512 * 2 ** zoom)
}
