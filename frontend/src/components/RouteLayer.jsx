import { useEffect, useMemo, useRef, useState } from 'react'
import L from 'leaflet'
import { CircleMarker, Marker, Polyline, Popup, useMap, useMapEvents } from 'react-leaflet'
import { nearestLon } from '../map/declutter'
import { LEVEL_COLORS, SEVERITY_COLORS, routeCoordinates, unwrapLine } from '../map/routes'

const LINE_HIT_PX = 16 // grab the line within this distance (finger friendly)
const GHOST_MIN_LEG_PX = 56 // no midpoint handle on legs shorter than this on screen
const DRAG_START_PX = 4

const handleIcon = (cls, text) =>
  L.divIcon({
    className: `route-handle ${cls}`,
    html: `<span>${text}</span>`,
    iconSize: cls === 'ghost' ? [26, 26] : [34, 34],
    iconAnchor: cls === 'ghost' ? [13, 13] : [17, 17],
  })
const ICONS = {
  a: handleIcon('end end-a', 'A'),
  b: handleIcon('end end-b', 'B'),
  wp: handleIcon('wp', ''),
  ghost: handleIcon('ghost', '+'),
}
const hazardIcons = {}
function hazardIcon(severity, selected) {
  const k = `${severity}${selected ? '-sel' : ''}`
  hazardIcons[k] ??= L.divIcon({
    className: `route-hazard-icon ${severity} ${selected ? 'selected' : ''}`,
    html: '<span><b>!</b></span>',
    iconSize: [24, 24],
    iconAnchor: [12, 12],
  })
  return hazardIcons[k]
}

/** Distance in px from point p to segment ab (all L.Point). */
function distToSegment(p, a, b) {
  const dx = b.x - a.x
  const dy = b.y - a.y
  const len2 = dx * dx + dy * dy
  const t = len2 ? Math.max(0, Math.min(1, ((p.x - a.x) * dx + (p.y - a.y) * dy) / len2)) : 0
  return { d: p.distanceTo(L.point(a.x + t * dx, a.y + t * dy)), t }
}

/**
 * Everything routes draw on the map.
 *
 * - Saved routes: thin lines (colour = worst severity), tap to open.
 * - The active route: severity-coloured segments from the analysis over a
 *   dark casing (a plain line while it is being re-analysed), hazard
 *   markers, the selected hazard highlighted and the profile cursor.
 * - Google-Maps-like editing, all touch friendly (no right-click):
 *     drag A, B or a waypoint handle to move it;
 *     drag a "+" midpoint handle, or grab the line itself anywhere, to
 *     insert a waypoint there;
 *     tap a waypoint for a popup with "Remove waypoint".
 *   Only the final drop is reported; the parent re-analyses (debounced).
 * - Picking A/B: taps go to onPick(latlng) and labels/POIs are made
 *   non-interactive by the parent so the tap reaches the map.
 */
export default function RouteLayer({
  routes,
  activeId,
  draft,
  picking,
  pickStart,
  analysis,
  selectedHazardId,
  cursor,
  editable = true,
  onPick,
  onSelectRoute,
  onMoveVertex,
  onInsertVertex,
  onRemoveWaypoint,
  onSelectHazard,
}) {
  const map = useMap()
  const [view, setView] = useState(0) // bumps on move/zoom so screen-space helpers refresh
  const [preview, setPreview] = useState(null) // { index, latlng, insert }
  const [wpPopup, setWpPopup] = useState(null) // waypoint index with the open popup
  const refLon = useRef(map.getCenter().lng)

  useMapEvents({
    moveend: () => setView((v) => v + 1),
    zoomend: () => setView((v) => v + 1),
    click: (e) => {
      if (picking) onPick(e.latlng)
    },
  })

  const coords = useMemo(() => (draft ? routeCoordinates(draft) : null), [draft])
  // Display positions (Leaflet [lat, lng]) unwrapped near the view centre.
  const vertices = useMemo(() => {
    if (!coords) return []
    refLon.current = map.getCenter().lng
    const line = unwrapLine(coords, undefined)
    const shift = nearestLon(line[0][1], refLon.current) - line[0][1]
    return line.map(([lat, lng]) => [lat, lng + shift])
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [coords, view])
  const shiftOf = (lon) => (vertices.length ? nearestLon(lon, vertices[0][1]) - lon : 0)

  const fresh = analysis?.status === 'ok' && analysis.data
  const data = fresh ? analysis.data : null
  const segments = useMemo(
    () =>
      data
        ? data.segments.map((s) => ({ ...s, line: unwrapLine(s.coordinates, vertices[0]?.[1]) }))
        : [],
    [data, vertices],
  )
  // Dense geometry of the drawn line (for hit tests and midpoints).
  const dense = useMemo(() => {
    if (!data) return null
    const line = unwrapLine(data.profile.map((p) => [p.lon, p.lat]), vertices[0]?.[1])
    return line.map((ll, i) => ({ ll, d: data.profile[i].d }))
  }, [data, vertices])

  // Legs: midpoint position + screen length, for the "+" ghost handles.
  const legs = useMemo(() => {
    if (vertices.length < 2) return []
    const out = []
    for (let i = 0; i < vertices.length - 1; i++) {
      const a = map.latLngToContainerPoint(vertices[i])
      const b = map.latLngToContainerPoint(vertices[i + 1])
      let mid = [(vertices[i][0] + vertices[i + 1][0]) / 2, (vertices[i][1] + vertices[i + 1][1]) / 2]
      if (dense && data.vertexDistancesM?.length === vertices.length) {
        const dm = (data.vertexDistancesM[i] + data.vertexDistancesM[i + 1]) / 2
        const near = dense.reduce((best, p) => (Math.abs(p.d - dm) < Math.abs(best.d - dm) ? p : best), dense[0])
        mid = near.ll
      }
      out.push({ i, mid, px: a.distanceTo(b) })
    }
    return out
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [vertices, dense, view])

  // ---- grab the line anywhere: capture pointer events on the container ----
  const live = useRef({})
  live.current = { vertices, dense, data, editable, active: !!draft && !picking, onInsertVertex }
  useEffect(() => {
    const el = map.getContainer()
    let drag = null
    const legAt = (p) => {
      const { vertices: vs, dense: dn, data: dt } = live.current
      // Hit test against the dense drawn line when analysed, else the legs.
      const pts = dn ? dn.map((x) => x.ll) : vs
      let best = null
      for (let i = 0; i < pts.length - 1; i++) {
        const a = map.latLngToContainerPoint(pts[i])
        const b = map.latLngToContainerPoint(pts[i + 1])
        const h = distToSegment(p, a, b)
        if (!best || h.d < best.d) best = { d: h.d, i, t: h.t }
      }
      if (!best || best.d > LINE_HIT_PX) return null
      if (!dn) return best.i
      const d = dn[best.i].d + best.t * (dn[best.i + 1].d - dn[best.i].d)
      const vd = dt.vertexDistancesM
      let leg = 0
      while (leg < vd.length - 2 && d > vd[leg + 1]) leg++
      return leg
    }
    const down = (e) => {
      const st = live.current
      if (!st.active || !st.editable || !e.isPrimary || e.button > 0) return
      if (e.target.closest?.('.route-handle, .route-hazard-icon, .leaflet-popup, .leaflet-control')) return
      const rect = el.getBoundingClientRect()
      const p = L.point(e.clientX - rect.left, e.clientY - rect.top)
      const leg = legAt(p)
      if (leg === null) return
      e.stopPropagation()
      e.preventDefault()
      map.dragging.disable()
      el.setPointerCapture?.(e.pointerId)
      drag = { leg, start: p, moved: false, id: e.pointerId }
    }
    const move = (e) => {
      if (!drag || e.pointerId !== drag.id) return
      const rect = el.getBoundingClientRect()
      const p = L.point(e.clientX - rect.left, e.clientY - rect.top)
      if (!drag.moved && p.distanceTo(drag.start) < DRAG_START_PX) return
      drag.moved = true
      e.stopPropagation()
      setPreview({ index: drag.leg + 1, latlng: map.containerPointToLatLng(p), insert: true })
    }
    const up = (e) => {
      if (!drag || e.pointerId !== drag.id) return
      const d = drag
      drag = null
      map.dragging.enable()
      el.releasePointerCapture?.(e.pointerId)
      setPreview(null)
      if (!d.moved) return
      e.stopPropagation()
      const rect = el.getBoundingClientRect()
      const latlng = map.containerPointToLatLng(L.point(e.clientX - rect.left, e.clientY - rect.top))
      live.current.onInsertVertex(d.leg + 1, latlng)
    }
    // Mouse "compatibility" events would start a map pan; swallow them
    // while a line drag is in progress.
    const mouse = (e) => drag && e.stopPropagation()
    el.addEventListener('pointerdown', down, true)
    el.addEventListener('pointermove', move, true)
    el.addEventListener('pointerup', up, true)
    el.addEventListener('pointercancel', up, true)
    el.addEventListener('mousedown', mouse, true)
    return () => {
      el.removeEventListener('pointerdown', down, true)
      el.removeEventListener('pointermove', move, true)
      el.removeEventListener('pointerup', up, true)
      el.removeEventListener('pointercancel', up, true)
      el.removeEventListener('mousedown', mouse, true)
      map.dragging.enable()
    }
  }, [map])

  // Close the waypoint popup when the route changes under it.
  useEffect(() => setWpPopup(null), [coords])

  // Line shown while dragging: the vertices with the preview applied.
  const previewLine = useMemo(() => {
    if (!preview) return null
    const vs = [...vertices]
    const ll = [preview.latlng.lat, preview.latlng.lng]
    if (preview.insert) vs.splice(preview.index, 0, ll)
    else vs[preview.index] = ll
    return vs
  }, [preview, vertices])

  const handleEvents = (index) => ({
    drag: (e) => setPreview({ index, latlng: e.target.getLatLng(), insert: false }),
    dragend: (e) => {
      setPreview(null)
      onMoveVertex(index, e.target.getLatLng())
    },
    click: () => {
      if (index > 0 && index < vertices.length - 1) setWpPopup(index)
    },
  })

  const hazards = data?.hazards.filter((h) => h.scope === 'segment' && h.severity !== 'info') ?? []
  const selected = data?.hazards.find((h) => h.id === selectedHazardId)
  const n = vertices.length

  return (
    <>
      {/* Saved routes that are not being edited */}
      {routes
        .filter((r) => r.id !== activeId)
        .map((r) => (
          <Polyline
            key={r.id}
            positions={unwrapLine(r.geometry.coordinates, map.getCenter().lng)}
            pathOptions={{
              color: LEVEL_COLORS[r.properties.stats?.maxSeverity ?? 'ok'],
              weight: 4,
              opacity: 0.75,
              dashArray: '8 6',
              className: 'route-saved',
            }}
            interactive={!picking && !draft}
            bubblingMouseEvents={false}
            eventHandlers={{ click: () => onSelectRoute(r) }}
          />
        ))}

      {/* A while waiting for B */}
      {picking === 'B' && pickStart && (
        <Marker position={[pickStart.lat, nearestLon(pickStart.lon, map.getCenter().lng)]} icon={ICONS.a} interactive={false} />
      )}

      {draft && (
        <>
          <Polyline
            positions={dense ? dense.map((p) => p.ll) : vertices}
            pathOptions={{ color: '#0b0d12', weight: 10, opacity: 0.7, interactive: false }}
          />
          {segments.length ? (
            segments.map((s, i) => (
              <Polyline
                key={i}
                positions={s.line}
                pathOptions={{
                  color: s.noData ? LEVEL_COLORS.noData : LEVEL_COLORS[s.level],
                  weight: 6,
                  dashArray: s.noData ? '6 8' : undefined,
                  interactive: false,
                }}
              />
            ))
          ) : (
            <Polyline positions={vertices} pathOptions={{ color: '#d8d2ca', weight: 5, dashArray: '10 8', interactive: false }} />
          )}
          {selected?.coordinates?.length > 1 && (
            <>
              <Polyline
                positions={unwrapLine(selected.coordinates, vertices[0]?.[1])}
                pathOptions={{ color: '#ffffff', weight: 14, opacity: 0.45, interactive: false, className: 'route-hazard-glow' }}
              />
              <Polyline
                positions={unwrapLine(selected.coordinates, vertices[0]?.[1])}
                pathOptions={{ color: SEVERITY_COLORS[selected.severity], weight: 7, interactive: false }}
              />
            </>
          )}
          {previewLine && (
            <Polyline positions={previewLine} pathOptions={{ color: '#ffffff', weight: 3, dashArray: '6 6', interactive: false }} />
          )}
          {hazards.map((h) => (
            <Marker
              key={h.id}
              position={[h.lat, h.lon + shiftOf(h.lon)]}
              icon={hazardIcon(h.severity, h.id === selectedHazardId)}
              zIndexOffset={h.id === selectedHazardId ? 900 : 400}
              eventHandlers={{ click: () => onSelectHazard(h) }}
              title={h.title}
            />
          ))}
          {cursor && (
            <CircleMarker
              center={[cursor.lat, cursor.lon + shiftOf(cursor.lon)]}
              radius={7}
              pathOptions={{ color: '#0b0d12', weight: 2, fillColor: '#ffd27a', fillOpacity: 1, interactive: false }}
            />
          )}
          {editable &&
            !picking &&
            n < 202 &&
            legs
              .filter((l) => l.px >= GHOST_MIN_LEG_PX)
              .map((l) => (
                <Marker
                  key={`g${l.i}-${l.mid[0]}-${l.mid[1]}`}
                  position={l.mid}
                  icon={ICONS.ghost}
                  draggable
                  zIndexOffset={600}
                  title="Drag to add a waypoint"
                  eventHandlers={{
                    drag: (e) => setPreview({ index: l.i + 1, latlng: e.target.getLatLng(), insert: true }),
                    dragend: (e) => {
                      setPreview(null)
                      onInsertVertex(l.i + 1, e.target.getLatLng())
                    },
                  }}
                />
              ))}
          {vertices.map((v, i) => (
            <Marker
              key={`v${i}-${n}`}
              position={v}
              icon={i === 0 ? ICONS.a : i === n - 1 ? ICONS.b : ICONS.wp}
              draggable={editable && !picking}
              zIndexOffset={i === 0 || i === n - 1 ? 1200 : 1100}
              title={i === 0 ? 'Start (A): drag to move' : i === n - 1 ? 'End (B): drag to move' : 'Waypoint: drag to move, tap to remove'}
              eventHandlers={handleEvents(i)}
            />
          ))}
          {wpPopup !== null && vertices[wpPopup] && (
            <Popup position={vertices[wpPopup]} className="route-wp-popup" eventHandlers={{ remove: () => setWpPopup(null) }}>
              <div className="route-wp-pop">
                <strong>Waypoint {wpPopup}</strong>
                <button
                  className="btn danger confirm"
                  onClick={() => {
                    onRemoveWaypoint(wpPopup - 1)
                    setWpPopup(null)
                  }}
                >
                  Remove waypoint
                </button>
              </div>
            </Popup>
          )}
        </>
      )}
    </>
  )
}
