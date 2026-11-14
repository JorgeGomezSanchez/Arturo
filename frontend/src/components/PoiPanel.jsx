import PoiIcon from './PoiIcon'
import { poiLabelMinZoom } from '../map/poiVisibility'

/**
 * POIs tab: the "Add POI" entry point plus the list of every POI (also
 * the ones hidden at the current zoom). Tapping one flies to it at the
 * zoom it was created at and opens it.
 */
export default function PoiPanel({ pois, categories, rules, error, placing, onStartPlacing, onCancelPlacing, onOpen }) {
  const catById = Object.fromEntries(categories.map((c) => [c.id, c]))
  const sorted = [...pois].sort((a, b) => a.properties.createdZoom - b.properties.createdZoom)
  return (
    <div className="poi-panel">
      {placing ? (
        <button className="btn wide" onClick={onCancelPlacing}>
          Cancel placing
        </button>
      ) : (
        <button className="btn primary wide" onClick={onStartPlacing}>
          ＋ Add POI
        </button>
      )}
      <p className="muted panel-hint">
        Tap “Add POI”, then tap the map. The zoom you place it at decides from how far its label is
        visible: world-view POIs (placed zoomed out) always show, local ones only when you are close.
      </p>
      {error && <p className="form-error">Could not load POIs: {error.message}</p>}
      {sorted.length === 0 ? (
        <p className="muted panel-hint">No POIs yet.</p>
      ) : (
        <ul className="poi-list">
          {sorted.map((p) => {
            const cat = catById[p.properties.category]
            const from = poiLabelMinZoom(p.properties.createdZoom, rules)
            return (
              <li key={p.id}>
                <button className="poi-item" onClick={() => onOpen(p)}>
                  <PoiIcon category={p.properties.category} color={cat?.color} size={34} />
                  <span>
                    <strong>{p.properties.name}</strong>
                    <span className="muted small">
                      {cat?.label ?? p.properties.category} · {from === 0 ? 'world view' : `label from zoom ${from}`}
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
