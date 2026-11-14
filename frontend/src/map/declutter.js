/**
 * Label decluttering (on-screen collision detection).
 *
 * Greedy placement, the standard approach of map label engines:
 *   1. candidates arrive sorted by priority (highest first);
 *   2. each one is placed only if its screen box does not overlap any
 *      box already placed (or reserved, e.g. user POIs);
 *   3. stop when `maxLabels` are placed.
 * Big/important names therefore win, and small ones re-appear as you
 * zoom in and space frees up. A uniform grid index keeps it ~O(n).
 */

const CELL = 64 // px, grid cell of the spatial index

let ctx = null
const widthCache = new Map()

/** Text width in px for a CSS font (canvas measureText, cached). */
export function measureText(text, font) {
  const key = font + '|' + text
  let w = widthCache.get(key)
  if (w === undefined) {
    if (!ctx) ctx = document.createElement('canvas').getContext('2d')
    ctx.font = font
    w = Math.ceil(ctx.measureText(text).width)
    if (widthCache.size > 5000) widthCache.clear()
    widthCache.set(key, w)
  }
  return w
}

class GridIndex {
  constructor() {
    this.cells = new Map()
  }
  *_keys(b) {
    for (let x = Math.floor(b.x1 / CELL); x <= Math.floor(b.x2 / CELL); x++)
      for (let y = Math.floor(b.y1 / CELL); y <= Math.floor(b.y2 / CELL); y++) yield x + ',' + y
  }
  hits(b) {
    for (const k of this._keys(b)) {
      for (const o of this.cells.get(k) ?? []) {
        if (b.x1 < o.x2 && b.x2 > o.x1 && b.y1 < o.y2 && b.y2 > o.y1) return true
      }
    }
    return false
  }
  add(b) {
    for (const k of this._keys(b)) {
      let list = this.cells.get(k)
      if (!list) this.cells.set(k, (list = []))
      list.push(b)
    }
  }
}

/**
 * @param candidates [{ box: {x1,y1,x2,y2}, ... }] sorted by priority desc
 * @param reserved   [{x1,y1,x2,y2}] boxes that must stay free
 * @param options    { padding = 3, maxLabels = Infinity }
 * @returns the subset of candidates that can be drawn without overlaps
 */
export function declutter(candidates, reserved = [], { padding = 3, maxLabels = Infinity } = {}) {
  const index = new GridIndex()
  for (const b of reserved) index.add(b)
  const placed = []
  for (const c of candidates) {
    if (placed.length >= maxLabels) break
    const b = {
      x1: c.box.x1 - padding,
      y1: c.box.y1 - padding,
      x2: c.box.x2 + padding,
      y2: c.box.y2 + padding,
    }
    if (index.hits(b)) continue
    index.add(b)
    placed.push(c)
  }
  return placed
}

/**
 * Longitude of the world copy closest to `centerLon`. Leaflet shows
 * several copies of the planet side by side (worldCopyJump); a feature at
 * lon -170 must be drawn at +190 when the view is centred at 175.
 */
export function nearestLon(lon, centerLon) {
  return lon + 360 * Math.round((centerLon - lon) / 360)
}
