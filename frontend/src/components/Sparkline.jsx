/**
 * Tiny SVG line chart for an item's `series` (e.g. temperature over a
 * sol). Generic: x/y numbers only, optional vertical marker at `markX`.
 */
export default function Sparkline({ series, unit, xLabel, markX, width = 300, height = 84 }) {
  if (!series?.length) return null
  const pad = { l: 34, r: 8, t: 8, b: 18 }
  const xs = series.map((p) => p.x)
  const ys = series.map((p) => p.y)
  const x0 = Math.min(...xs)
  const x1 = Math.max(...xs)
  const y0 = Math.min(...ys)
  const y1 = Math.max(...ys)
  const sx = (x) => pad.l + ((x - x0) / (x1 - x0 || 1)) * (width - pad.l - pad.r)
  const sy = (y) => pad.t + (1 - (y - y0) / (y1 - y0 || 1)) * (height - pad.t - pad.b)
  const d = series.map((p, i) => `${i ? 'L' : 'M'}${sx(p.x).toFixed(1)},${sy(p.y).toFixed(1)}`).join('')
  const ticks = [0, 6, 12, 18, 24].filter((t) => t >= x0 && t <= x1)
  const showMark = markX != null && markX >= x0 && markX <= x1
  return (
    <figure className="sparkline-wrap">
      <svg className="sparkline" viewBox={`0 0 ${width} ${height}`} role="img" aria-label={`${unit} by ${xLabel}`}>
        <line x1={pad.l} x2={width - pad.r} y1={sy(y1)} y2={sy(y1)} className="grid" />
        <line x1={pad.l} x2={width - pad.r} y1={sy(y0)} y2={sy(y0)} className="grid" />
        <text x={pad.l - 4} y={sy(y1) + 4} textAnchor="end">
          {Math.round(y1)}
        </text>
        <text x={pad.l - 4} y={sy(y0) + 4} textAnchor="end">
          {Math.round(y0)}
        </text>
        {ticks.map((t) => (
          <text key={t} x={sx(t)} y={height - 4} textAnchor="middle">
            {t}h
          </text>
        ))}
        {showMark && <line x1={sx(markX)} x2={sx(markX)} y1={pad.t} y2={height - pad.b} className="mark" />}
        <path d={d} className="line" />
      </svg>
      <figcaption>
        {unit} over one sol, by {xLabel}
        {showMark ? ' · dashed line = now' : ''}
      </figcaption>
    </figure>
  )
}
