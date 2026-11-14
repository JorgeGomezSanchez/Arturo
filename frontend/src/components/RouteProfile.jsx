import { SEVERITY_COLORS } from '../map/routes'

/**
 * Elevation profile of the analysed route (SVG). Hazard stretches are
 * shaded in their severity colour (tap one to select it), waypoints are
 * dashed vertical lines and the selected hazard is outlined. Tapping
 * anywhere else moves the cursor shown on the map.
 */
export default function RouteProfile({ analysis, selectedHazardId, cursorD, onSelectHazard, onCursor, width = 340, height = 150 }) {
  const prof = analysis.profile.filter((p) => p.elevation !== null)
  if (prof.length < 2) return <p className="muted small">No elevation data along this route.</p>
  const pad = { l: 44, r: 10, t: 10, b: 22 }
  const D = analysis.distanceM || 1
  const e0 = Math.min(...prof.map((p) => p.elevation))
  const e1 = Math.max(...prof.map((p) => p.elevation))
  const span = Math.max(e1 - e0, 20)
  const lo = e0 - span * 0.08
  const hi = e1 + span * 0.08
  const sx = (d) => pad.l + (d / D) * (width - pad.l - pad.r)
  const sy = (e) => pad.t + (1 - (e - lo) / (hi - lo)) * (height - pad.t - pad.b)
  const line = prof.map((p, i) => `${i ? 'L' : 'M'}${sx(p.d).toFixed(1)},${sy(p.elevation).toFixed(1)}`).join('')
  const area = `${line}L${sx(prof.at(-1).d).toFixed(1)},${height - pad.b}L${sx(prof[0].d).toFixed(1)},${height - pad.b}Z`
  const zones = analysis.hazards.filter((h) => h.scope === 'segment' && h.toM > h.fromM - 1)
  const kmStep = niceStep(D / 1000 / 4)
  const ticks = []
  for (let k = 0; k <= D / 1000 + 1e-9; k += kmStep) ticks.push(k)
  const cursor = cursorD != null ? analysis.profile.reduce((b, p) => (Math.abs(p.d - cursorD) < Math.abs(b.d - cursorD) ? p : b)) : null

  const pick = (evt) => {
    const svg = evt.currentTarget
    const r = svg.getBoundingClientRect()
    const x = ((evt.clientX - r.left) / r.width) * width
    const d = Math.max(0, Math.min(D, ((x - pad.l) / (width - pad.l - pad.r)) * D))
    onCursor?.(d)
  }

  return (
    <figure className="route-profile">
      <svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label="Elevation profile" onClick={pick}>
        {zones.map((h) => {
          const x0 = sx(h.fromM)
          const w = Math.max(sx(h.toM) - x0, 3)
          return (
            <rect
              key={h.id}
              x={x0 - (w === 3 ? 1.5 : 0)}
              y={pad.t}
              width={w}
              height={height - pad.t - pad.b}
              fill={SEVERITY_COLORS[h.severity]}
              className={`zone ${h.severity} ${h.id === selectedHazardId ? 'selected' : ''}`}
              onClick={(e) => {
                e.stopPropagation()
                onSelectHazard(h)
              }}
            >
              <title>{h.title}</title>
            </rect>
          )
        })}
        <line x1={pad.l} x2={width - pad.r} y1={sy(e1)} y2={sy(e1)} className="grid" />
        <line x1={pad.l} x2={width - pad.r} y1={sy(e0)} y2={sy(e0)} className="grid" />
        <text x={pad.l - 4} y={sy(e1) + 4} textAnchor="end">
          {fmtElev(e1)}
        </text>
        <text x={pad.l - 4} y={sy(e0) + 4} textAnchor="end">
          {fmtElev(e0)}
        </text>
        {analysis.vertexDistancesM.slice(1, -1).map((d, i) => (
          <line key={i} x1={sx(d)} x2={sx(d)} y1={pad.t} y2={height - pad.b} className="wp" />
        ))}
        <path d={area} className="area" />
        <path d={line} className="line" />
        {ticks.map((k) => (
          <text key={k} x={sx(k * 1000)} y={height - 6} textAnchor="middle">
            {k} km
          </text>
        ))}
        {cursor && cursor.elevation !== null && (
          <circle cx={sx(cursor.d)} cy={sy(cursor.elevation)} r={4} className="cursor" />
        )}
      </svg>
      <figcaption>
        Elevation (m, MOLA datum) by distance from A. Shaded: hazard stretches; dashed: waypoints. Tap the chart
        to locate a point on the map.
      </figcaption>
    </figure>
  )
}

function niceStep(x) {
  const p = 10 ** Math.floor(Math.log10(Math.max(x, 1e-3)))
  for (const m of [1, 2, 5, 10]) if (m * p >= x) return m * p
  return 10 * p
}

function fmtElev(e) {
  return Math.abs(e) >= 10000 ? `${(e / 1000).toFixed(1)}k` : Math.round(e).toLocaleString('en-US')
}
