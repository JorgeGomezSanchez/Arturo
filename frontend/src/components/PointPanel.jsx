import { useEffect, useState } from 'react'
import { getPoint } from '../api/client'
import Sparkline from './Sparkline'

// Season presets for the temperature estimate (northern-hemisphere names;
// the backend reports the local season for the point).
const LS_OPTIONS = [
  { value: '', label: 'Today on Mars' },
  { value: 0, label: 'Ls 0° · northern spring equinox' },
  { value: 45, label: 'Ls 45°' },
  { value: 90, label: 'Ls 90° · northern summer solstice' },
  { value: 135, label: 'Ls 135°' },
  { value: 180, label: 'Ls 180° · northern autumn equinox' },
  { value: 225, label: 'Ls 225°' },
  { value: 251, label: 'Ls 251° · perihelion (warmest sun)' },
  { value: 270, label: 'Ls 270° · northern winter solstice' },
  { value: 315, label: 'Ls 315°' },
]

function formatLatLon(lat, lon) {
  return `${Math.abs(lat).toFixed(4)}° ${lat >= 0 ? 'N' : 'S'}, ${Math.abs(lon).toFixed(4)}° ${lon >= 0 ? 'E' : 'W'}`
}

function formatValue(item) {
  if (item.noData || item.value === null || item.value === undefined) return 'No data'
  if (typeof item.value === 'number') {
    const p = item.precision ?? 0
    return item.value.toLocaleString('en-US', { minimumFractionDigits: p, maximumFractionDigits: p })
  }
  return item.value
}

function hoursOf(hhmm) {
  if (!hhmm) return null
  const [h, m] = hhmm.split(':').map(Number)
  return h + m / 60
}

function Item({ item, nowHours }) {
  const hasDetails = item.method || item.notes
  const text = typeof item.value === 'string' && !item.noData
  const row = (
    <div className={`pitem-row ${text ? 'text' : ''}`}>
      <span className="pitem-label">{item.label}</span>
      <span className={`pitem-value ${item.noData ? 'nodata' : ''}`}>
        {formatValue(item)}
        {!item.noData && item.unit && <span className="pitem-unit"> {item.unit}</span>}
        {item.estimate && !item.noData && (
          <span className="badge est" title="Modelled value, not a measurement">
            est.
          </span>
        )}
      </span>
    </div>
  )
  const meta =
    item.source || item.resolution ? (
      <div className="pitem-meta">
        {item.source}
        {item.source && item.resolution ? ' · ' : ''}
        {item.resolution}
      </div>
    ) : null
  return (
    <li className="pitem">
      {hasDetails ? (
        <details>
          <summary>
            {row}
            {meta}
          </summary>
          <div className="pitem-details">
            {item.notes && <p>{item.notes}</p>}
            {item.method && (
              <p>
                <strong>Method:</strong> {item.method}
              </p>
            )}
          </div>
        </details>
      ) : (
        <div className="pitem-plain">
          {row}
          {meta}
        </div>
      )}
      {item.series && (
        <Sparkline series={item.series} unit={item.unit} xLabel={item.seriesX || 'x'} markX={nowHours} />
      )}
    </li>
  )
}

/**
 * Generic renderer of GET /api/point: sections of items, whatever the
 * backend sends (no value is hard-coded here). Side panel on desktop,
 * bottom sheet on phones (CSS). Changing the season re-queries.
 *
 * target = { lat, lon, title?, onBack? }
 */
export default function PointPanel({ target, onClose }) {
  const [ls, setLs] = useState('')
  const [attempt, setAttempt] = useState(0)
  // Last answer (kept on screen, dimmed, while the next one loads).
  const [result, setResult] = useState({ key: null })
  const key = `${target.lat},${target.lon},${ls},${attempt}`

  useEffect(() => {
    const ctrl = new AbortController()
    getPoint({ lat: target.lat, lon: target.lon, ls: ls === '' ? undefined : ls }, ctrl.signal)
      .then((data) => setResult({ key, data }))
      .catch((error) => {
        if (error.name !== 'AbortError') setResult((r) => ({ key, data: r.data, error }))
      })
    return () => ctrl.abort()
  }, [target.lat, target.lon, ls, key])

  const state = {
    status: result.key !== key ? 'loading' : result.error ? 'error' : 'ok',
    data: result.data,
    error: result.error,
  }

  useEffect(() => {
    const onKey = (e) => e.key === 'Escape' && onClose()
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  const data = state.data
  const q = data?.query
  const fresh = state.status === 'ok'
  const nowHours = q && q.lsSource === 'current' ? hoursOf(q.localSolarTime) : null

  return (
    <aside className="hud point-panel" aria-label="Location information" aria-busy={state.status === 'loading'}>
      <div className="sheet-grip" aria-hidden="true" />
      <header className="point-head">
        <div>
          <h2>{target.title || 'This location'}</h2>
          <div className="muted small">{formatLatLon(target.lat, target.lon)}</div>
        </div>
        <button className="icon-btn close" onClick={onClose} aria-label="Close location panel">
          ✕
        </button>
      </header>
      <div className="point-controls">
        {target.onBack && (
          <button className="btn" onClick={target.onBack}>
            ← POI
          </button>
        )}
        <label className="ls-select">
          <span className="muted small">Season for estimates</span>
          <select value={ls} onChange={(e) => setLs(e.target.value === '' ? '' : Number(e.target.value))}>
            {LS_OPTIONS.map((o) => (
              <option key={o.label} value={o.value}>
                {o.value === '' && q?.lsSource === 'current' ? `Today on Mars (Ls ${Math.round(q.ls)}°)` : o.label}
              </option>
            ))}
          </select>
        </label>
      </div>

      <div className="point-body">
        {state.status === 'loading' && !data && (
          <div className="point-loading" role="status">
            <span className="spinner" /> Reading the maps at this point…
          </div>
        )}
        {state.status === 'error' && (
          <div className="point-error" role="alert">
            <p>Could not load the data for this point.</p>
            <code>{String(state.error?.message ?? state.error)}</code>
            <button className="btn" onClick={() => setAttempt((n) => n + 1)}>
              Retry
            </button>
          </div>
        )}
        {data && (
          <div className={fresh ? '' : 'stale'}>
            {data.sections.map((s) => (
              <section key={s.id} className="psection">
                <h3>{s.title}</h3>
                <ul>
                  {s.items.map((it) => (
                    <Item key={it.id} item={it} nowHours={nowHours} />
                  ))}
                </ul>
              </section>
            ))}
            <p className="muted small point-foot">
              Values come from the backend ({q.dataSource}). Tap a row for its method and notes. “est.” = modelled
              estimate, not a measurement.
            </p>
          </div>
        )}
      </div>
    </aside>
  )
}
