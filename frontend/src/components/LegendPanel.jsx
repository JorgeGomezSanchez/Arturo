import { useState } from 'react'

const CATEGORICAL_PREVIEW = 8

function Gradient({ legend }) {
  const colors = legend.stops.map((s) => s.color)
  const background =
    colors.length === 1 ? colors[0] : `linear-gradient(to right, ${colors.join(', ')})`
  return (
    <div className="legend-gradient">
      <div className="legend-bar" style={{ background }} />
      <div className="legend-ends">
        <span>{legend.minLabel}</span>
        <span>{legend.maxLabel}</span>
      </div>
      {legend.stops.some((s) => s.label) && (
        <ul className="legend-swatches">
          {legend.stops
            .filter((s) => s.label)
            .map((s) => (
              <li key={s.color + s.label}>
                <span className="swatch" style={{ background: s.color }} />
                {s.label}
              </li>
            ))}
        </ul>
      )}
    </div>
  )
}

function Swatches({ legend }) {
  const [all, setAll] = useState(false)
  const many = legend.stops.length > CATEGORICAL_PREVIEW + 2
  const stops = many && !all ? legend.stops.slice(0, CATEGORICAL_PREVIEW) : legend.stops
  return (
    <>
      <ul className={`legend-swatches ${legend.type}`}>
        {stops.map((s, i) => (
          <li key={i}>
            <span className={`swatch ${legend.type === 'symbol' ? 'line' : ''}`} style={{ background: s.color }} />
            {s.label}
          </li>
        ))}
      </ul>
      {many && (
        <button className="text-btn" onClick={() => setAll((v) => !v)}>
          {all ? 'Show fewer' : `Show all ${legend.stops.length} classes`}
        </button>
      )}
    </>
  )
}

function LegendCard({ layer }) {
  const { legend } = layer
  const [open, setOpen] = useState(true)
  return (
    <section className="legend-card">
      <button className="legend-title" onClick={() => setOpen((v) => !v)} aria-expanded={open}>
        <span>
          <strong>{legend.title || layer.name}</strong>
          {legend.units ? <span className="muted"> ({legend.units})</span> : null}
        </span>
        <span className="muted">{open ? '▾' : '▸'}</span>
      </button>
      {open && (
        <>
          <div className="muted legend-layer">{layer.name}</div>
          {legend.type === 'gradient' ? <Gradient legend={legend} /> : <Swatches legend={legend} />}
          {!legend.quantitative && (
            <div className="legend-badge" title="The data provider does not publish an exact colour-to-value scale for these tiles">
              Qualitative scale · read as relative values
            </div>
          )}
          {legend.notes?.length > 0 && (
            <ul className="legend-notes">
              {legend.notes.map((n, i) => (
                <li key={i}>{n}</li>
              ))}
            </ul>
          )}
          {legend.sources?.length > 0 && (
            <div className="legend-sources">
              Sources:{' '}
              {legend.sources.map((s, i) => (
                <span key={i}>
                  {i > 0 && ' · '}
                  {s.url ? (
                    <a href={s.url} target="_blank" rel="noreferrer">
                      {s.name}
                    </a>
                  ) : (
                    s.name
                  )}
                </span>
              ))}
            </div>
          )}
        </>
      )}
    </section>
  )
}

/**
 * Legends of the layers currently ON, top of the stack first. Purely a
 * renderer of the backend's `legend` metadata (layers.yaml): it knows
 * nothing about MOLA, THEMIS or geology.
 */
export default function LegendPanel({ layers, layerState }) {
  const [open, setOpen] = useState(true)
  const shown = layers
    .filter((l) => l.legend && layerState.settings[l.id]?.visible)
    .sort((a, b) => layerState.zIndexOf(b.id) - layerState.zIndexOf(a.id))
  if (shown.length === 0) return null

  return (
    <aside className={`hud legend-panel ${open ? 'open' : 'closed'}`}>
      <button className="panel-toggle" onClick={() => setOpen((v) => !v)} aria-expanded={open}>
        <span>Legend</span>
        <span className="muted">
          {shown.length} {open ? '▾' : '▸'}
        </span>
      </button>
      {open && (
        <div className="legend-scroll">
          {shown.map((l) => (
            <LegendCard key={l.id} layer={l} />
          ))}
        </div>
      )}
    </aside>
  )
}
