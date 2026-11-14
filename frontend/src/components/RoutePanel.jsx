import { useEffect, useRef, useState } from 'react'
import RouteProfile from './RouteProfile'
import { SEVERITY_COLORS, SEVERITY_LABEL, endName, formatHours, formatKm } from '../map/routes'

const KIND_LABEL = { poi: 'POI', feature: 'Named place', point: 'Map point' }

function HazardItem({ h, selected, onSelect }) {
  const ref = useRef(null)
  useEffect(() => {
    if (selected) ref.current?.scrollIntoView({ block: 'nearest', behavior: 'smooth' })
  }, [selected])
  const where = h.scope === 'route' ? 'Whole route' : h.toM - h.fromM < 1 ? `at ${formatKm(h.fromM)}` : `${formatKm(h.fromM)} – ${formatKm(h.toM)}`
  return (
    <li>
      <button ref={ref} className={`hazard-item ${h.severity} ${selected ? 'selected' : ''}`} onClick={() => onSelect(h)}>
        <span className="hazard-sev" style={{ '--sev': SEVERITY_COLORS[h.severity] }}>
          {SEVERITY_LABEL[h.severity]}
        </span>
        <span className="hazard-main">
          <strong>{h.title}</strong>
          <span className="muted small">
            {where}
            {h.value != null && ` · ${Number(h.value).toLocaleString('en-US', { maximumFractionDigits: h.value < 10 ? 1 : 0 })} ${h.unit}`}
            {h.threshold != null && ` (limit ${h.threshold} ${h.unit})`}
          </span>
          {selected && <span className="hazard-desc">{h.description}</span>}
        </span>
      </button>
    </li>
  )
}

/**
 * Details of the route being created or edited: name, travel mode,
 * notes, summary statistics, elevation profile and the hazard list (tap
 * one to fly to it on the map). Side panel on desktop, bottom sheet on
 * phones. Every number comes from the backend analysis.
 */
export default function RoutePanel({
  draft,
  saved,
  dirty,
  config,
  analysis,
  selectedHazardId,
  cursorD,
  onChange,
  onSelectHazard,
  onCursor,
  onSave,
  onDelete,
  onClose,
}) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const [confirmDelete, setConfirmDelete] = useState(false)
  const [collapsed, setCollapsed] = useState(false)
  const data = analysis.data
  const stale = analysis.status !== 'ok'
  const modes = config ? Object.values(config.modes) : []

  const save = async () => {
    setBusy(true)
    setError(null)
    try {
      await onSave()
    } catch (e) {
      setError(e.detail || e.message)
    } finally {
      setBusy(false)
    }
  }
  const remove = async () => {
    if (!confirmDelete) return setConfirmDelete(true)
    setBusy(true)
    try {
      await onDelete()
    } catch (e) {
      setError(e.detail || e.message)
      setBusy(false)
    }
  }

  const hazards = data?.hazards ?? []
  const counts = data?.hazardCounts ?? {}

  return (
    <aside
      className={`hud point-panel route-panel ${collapsed ? 'collapsed' : ''}`}
      aria-label="Route details"
      aria-busy={analysis.status === 'loading'}
    >
      <button className="sheet-grip-btn" onClick={() => setCollapsed((c) => !c)} aria-label={collapsed ? 'Expand route panel' : 'Collapse route panel'}>
        <span className="sheet-grip" aria-hidden="true" />
      </button>
      <header className="point-head">
        <div className="route-title">
          <input
            className="route-name"
            value={draft.name}
            maxLength={60}
            onChange={(e) => onChange({ name: e.target.value })}
            aria-label="Route name"
          />
          <div className="muted small route-ends">
            <span className="end-chip a">A</span> {endName(draft.start)}
            <span className="muted"> ({KIND_LABEL[draft.start.kind]})</span>
            <br />
            <span className="end-chip b">B</span> {endName(draft.end)}
            <span className="muted"> ({KIND_LABEL[draft.end.kind]})</span>
          </div>
        </div>
        <button className="icon-btn close" onClick={onClose} aria-label="Close route">
          ✕
        </button>
      </header>

      <div className="route-summary">
        {analysis.status === 'loading' && (
          <div className="route-busy" role="status">
            <span className="spinner" /> Analysing…
          </div>
        )}
        {data ? (
          <dl className={`route-stats ${stale ? 'stale' : ''}`}>
            <div>
              <dt>Distance</dt>
              <dd>{formatKm(data.distanceM)}</dd>
            </div>
            <div>
              <dt>Duration</dt>
              <dd>{formatHours(data.durationH)}</dd>
            </div>
            <div>
              <dt>Gain / loss</dt>
              <dd>
                +{Math.round(data.gainM)} / −{Math.round(data.lossM)} m
              </dd>
            </div>
            <div>
              <dt>Radiation</dt>
              <dd>{data.doseMsv.toFixed(2)} mSv</dd>
            </div>
            <div>
              <dt>Max slope</dt>
              <dd>{data.maxSlopeDeg != null ? `${data.maxSlopeDeg.toFixed(1)}°` : '–'}</dd>
            </div>
            <div>
              <dt>Hazards</dt>
              <dd className="hazard-counts">
                {['danger', 'warning', 'info'].map((k) =>
                  counts[k] ? (
                    <span key={k} style={{ color: SEVERITY_COLORS[k] }} title={SEVERITY_LABEL[k]}>
                      {counts[k]} {k === 'warning' ? 'warn' : k}
                    </span>
                  ) : null,
                )}
                {!counts.danger && !counts.warning && !counts.info && <span style={{ color: '#4cc36e' }}>none</span>}
              </dd>
            </div>
          </dl>
        ) : (
          analysis.status !== 'error' && <p className="muted">Analysing the route…</p>
        )}
      </div>

      {!collapsed && (
        <div className="point-body route-body">
          {analysis.status === 'error' && (
            <div className="point-error" role="alert">
              <p>Could not analyse this route.</p>
              <code>{analysis.error?.detail || analysis.error?.message}</code>
              <button className="btn" onClick={analysis.retry}>
                Retry
              </button>
            </div>
          )}
          <div className="route-form">
            <label>
              <span className="muted small">Travel mode</span>
              <select value={draft.mode} onChange={(e) => onChange({ mode: e.target.value })}>
                {modes.map((m) => (
                  <option key={m.id} value={m.id}>
                    {m.label} · {m.speedKmh} km/h
                  </option>
                ))}
              </select>
            </label>
            <div className="route-actions">
              <button className="btn primary" onClick={save} disabled={busy || !draft.name.trim() || (saved && !dirty)}>
                {saved ? (dirty ? 'Save changes' : 'Saved') : 'Save route'}
              </button>
              {saved && (
                <button className={`btn danger ${confirmDelete ? 'confirm' : ''}`} onClick={remove} disabled={busy}>
                  {confirmDelete ? 'Tap again to delete' : 'Delete'}
                </button>
              )}
            </div>
            {error && <p className="form-error">{error}</p>}
          </div>
          <p className="muted small route-hint">
            Drag the line or a <b>+</b> handle to add a waypoint, drag A, B or a waypoint to move it, tap a waypoint
            to remove it. Hazards are recomputed after every change.
          </p>

          {data && (
            <div className={stale ? 'stale' : ''}>
              <section className="psection">
                <h3>Elevation profile</h3>
                <RouteProfile
                  analysis={data}
                  selectedHazardId={selectedHazardId}
                  cursorD={cursorD}
                  onSelectHazard={onSelectHazard}
                  onCursor={onCursor}
                />
              </section>
              <section className="psection">
                <h3>Hazards ({hazards.length})</h3>
                {hazards.length === 0 ? (
                  <p className="muted">No hazard over the configured thresholds.</p>
                ) : (
                  <ul className="hazard-list">
                    {hazards.map((h) => (
                      <HazardItem key={h.id} h={h} selected={h.id === selectedHazardId} onSelect={onSelectHazard} />
                    ))}
                  </ul>
                )}
              </section>
              <section className="psection">
                <h3>Data used</h3>
                <p className="small">{data.resolution}</p>
                <p className="muted small">
                  {data.modeLabel}; night minimum {data.nightMinC != null ? `${Math.round(data.nightMinC)} °C` : 'n/a'} at Ls{' '}
                  {Math.round(data.ls)}°.
                </p>
                <details className="small">
                  <summary>Method and assumptions</summary>
                  <p>{data.method}</p>
                </details>
              </section>
            </div>
          )}
          <label className="route-notes">
            <span className="muted small">Notes</span>
            <textarea rows={3} maxLength={2000} value={draft.notes} onChange={(e) => onChange({ notes: e.target.value })} />
          </label>
        </div>
      )}
    </aside>
  )
}
