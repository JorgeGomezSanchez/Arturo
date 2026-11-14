import { LEVEL_COLORS, formatKm } from '../map/routes'

/**
 * Routes tab: the "New route" entry point plus the list of saved routes
 * (tap one to open and edit it).
 */
export default function RoutesPanel({ routes, config, error, picking, onNew, onCancel, onOpen, activeId }) {
  return (
    <div className="poi-panel">
      {picking ? (
        <button className="btn wide" onClick={onCancel}>
          Cancel new route
        </button>
      ) : (
        <button className="btn primary wide" onClick={onNew}>
          ↝ New route
        </button>
      )}
      <p className="muted panel-hint">
        Tap “New route”, then tap the start (A) and the end (B): a POI, a named place or any point (taps near a POI or
        label snap to it). Drag the line to avoid hazards.
      </p>
      {error && <p className="form-error">Could not load routes: {error.message}</p>}
      {routes.length === 0 ? (
        <p className="muted panel-hint">No routes yet.</p>
      ) : (
        <ul className="poi-list">
          {routes.map((r) => {
            const st = r.properties.stats
            return (
              <li key={r.id}>
                <button className={`poi-item ${r.id === activeId ? 'active' : ''}`} onClick={() => onOpen(r)}>
                  <span className="route-sev-dot" style={{ background: LEVEL_COLORS[st?.maxSeverity ?? 'ok'] }} />
                  <span>
                    <strong>{r.properties.name}</strong>
                    <span className="muted small">
                      {config?.modes[r.properties.mode]?.label ?? r.properties.mode}
                      {st ? ` · ${formatKm(st.distanceM)} · ${st.hazardCounts.danger ?? 0} danger, ${st.hazardCounts.warning ?? 0} warning` : ''}
                    </span>
                  </span>
                </button>
              </li>
            )
          })}
        </ul>
      )}
    </div>
  )
}
