import { useState } from 'react'

// Display order and titles of the catalog categories. Unknown categories
// (added later in layers.yaml) still show up, at the end.
const CATEGORY_TITLES = {
  imagery: 'Imagery (base)',
  topography: 'Topography',
  thermal: 'Thermal',
  surface: 'Surface properties',
  composition: 'Composition',
  geology: 'Geology',
  hydrology: 'Hydrology',
}

function formatResolution(m) {
  if (!m) return null
  return m >= 1000 ? `~${(m / 1000).toFixed(m >= 10000 ? 0 : 1)} km/px` : `~${m} m/px`
}

function LayerRow({ layer, setting, layerState, index, count, isOverlay }) {
  const [info, setInfo] = useState(false)
  const on = setting.visible
  return (
    <li className={`layer-row ${on ? 'on' : ''}`}>
      <div className="layer-main">
        <label className="layer-toggle">
          <input
            type="checkbox"
            checked={on}
            onChange={(e) => layerState.setVisible(layer.id, e.target.checked)}
          />
          <span className="switch" aria-hidden="true" />
          <span className="layer-name">{layer.name}</span>
        </label>
        <button
          className="icon-btn"
          onClick={() => setInfo((v) => !v)}
          aria-expanded={info}
          aria-label={`About ${layer.name}`}
        >
          i
        </button>
      </div>

      {on && (
        <div className="layer-controls">
          <label className="opacity">
            <span className="muted">Opacity</span>
            <input
              type="range"
              min="0"
              max="1"
              step="0.05"
              value={setting.opacity}
              onChange={(e) => layerState.setOpacity(layer.id, Number(e.target.value))}
              aria-label={`${layer.name} opacity`}
            />
            <span className="muted pct">{Math.round(setting.opacity * 100)}%</span>
          </label>
          {isOverlay && (
            <span className="order-btns">
              <button
                className="icon-btn"
                onClick={() => layerState.move(layer.id, +1)}
                disabled={index === count - 1}
                aria-label="Move layer up (draw on top)"
                title="Draw above"
              >
                ▲
              </button>
              <button
                className="icon-btn"
                onClick={() => layerState.move(layer.id, -1)}
                disabled={index === 0}
                aria-label="Move layer down"
                title="Draw below"
              >
                ▼
              </button>
            </span>
          )}
        </div>
      )}

      {info && (
        <div className="layer-info">
          <p>{layer.description}</p>
          {layer.resolutionM ? <p className="muted">Native resolution: {formatResolution(layer.resolutionM)}</p> : null}
          <p className="muted">{layer.attribution}</p>
        </div>
      )}
    </li>
  )
}

/**
 * Layer control. 100% driven by /api/layers: a new layer in the backend
 * catalog appears here with no frontend change. Touch-friendly: whole
 * rows are tap targets, opacity is a slider, order uses ▲/▼ buttons
 * (no drag-and-drop, no hover-only controls).
 *
 * Overlays are listed top-of-stack first within each category; the ▲/▼
 * buttons change the drawing order of all overlays.
 */
export default function LayersPanel({ layers, layerState, labelGroups, labelState, onToggleLabels }) {
  const byCategory = {}
  for (const l of layers) (byCategory[l.category] ??= []).push(l)
  const categories = [
    ...Object.keys(CATEGORY_TITLES).filter((c) => byCategory[c]),
    ...Object.keys(byCategory).filter((c) => !CATEGORY_TITLES[c]),
  ]
  const { overlayOrder } = layerState
  const visibleCount = layers.filter((l) => layerState.settings[l.id]?.visible).length

  return (
    <div className="layers-panel">
      <div className="panel-head">
        <span className="muted">{visibleCount} layer(s) on</span>
        <button className="text-btn" onClick={layerState.reset}>
          Reset
        </button>
      </div>

      {labelGroups?.length > 0 && (
      <section className="layer-group">
        <h3>Map labels</h3>
        <ul className="layer-list">
          {labelGroups.map((g) => (
            <li key={g.id} className={`layer-row ${labelState[g.id] ? 'on' : ''}`}>
              <div className="layer-main">
                <label className="layer-toggle">
                  <input
                    type="checkbox"
                    checked={!!labelState[g.id]}
                    onChange={(e) => onToggleLabels(g.id, e.target.checked)}
                  />
                  <span className="switch" aria-hidden="true" />
                  <span className="layer-name">
                    {g.label} <small className="muted">· {g.count}</small>
                  </span>
                </label>
              </div>
            </li>
          ))}
        </ul>
      </section>
      )}

      {categories.map((cat) => {
        const list = [...byCategory[cat]].sort(
          (a, b) => layerState.zIndexOf(b.id) - layerState.zIndexOf(a.id),
        )
        return (
          <section key={cat} className="layer-group">
            <h3>{CATEGORY_TITLES[cat] ?? cat}</h3>
            <ul className="layer-list">
              {list.map((layer) => (
                <LayerRow
                  key={layer.id}
                  layer={layer}
                  setting={layerState.settings[layer.id]}
                  layerState={layerState}
                  isOverlay={layer.group !== 'base'}
                  index={overlayOrder.indexOf(layer.id)}
                  count={overlayOrder.length}
                />
              ))}
            </ul>
          </section>
        )
      })}
    </div>
  )
}
