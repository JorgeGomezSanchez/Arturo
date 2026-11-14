import { useEffect, useState } from 'react'

/**
 * Compact, collapsible map credits (replaces Leaflet's attribution bar).
 *
 * Leaflet's built-in control prints every attribution on one line in the
 * bottom-right corner; with several layers on, that line wraps across the
 * whole width and covers the scale bar. Here the credits sit behind a
 * small "ⓘ Credits" button (touch target >= 36 px) and open in a panel
 * that only lists what is actually drawn:
 *   - tile layers that are switched on AND shown at the current zoom
 *     (e.g. CTX is not credited at zoom 3, where it is not drawn),
 *   - label groups that are switched on (lines from /api/map labelCredits),
 *   - Leaflet itself.
 */
export default function CreditsControl({ map, layers, layerState, labelGroups, labelState, labelCredits }) {
  const [open, setOpen] = useState(false)
  const [zoom, setZoom] = useState(() => map?.getZoom() ?? 0)

  useEffect(() => {
    if (!map) return undefined
    const update = () => setZoom(map.getZoom())
    update()
    map.on('zoomend', update)
    return () => map.off('zoomend', update)
  }, [map])

  useEffect(() => {
    if (!open) return undefined
    const onKey = (e) => e.key === 'Escape' && setOpen(false)
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open])

  const layerLines = layers
    .filter((l) => layerState.settings[l.id]?.visible && zoom >= l.minZoom && zoom <= l.maxZoom)
    .sort((a, b) => layerState.zIndexOf(b.id) - layerState.zIndexOf(a.id)) // top layer first
    .map((l) => l.attribution)
    .filter(Boolean)
  const labelLines = labelGroups.filter((g) => labelState[g.id] && labelCredits?.[g.id]).map((g) => labelCredits[g.id])
  const lines = [...new Set([...layerLines, ...labelLines])]

  return (
    <div className={`credits ${open ? 'open' : ''}`}>
      {open && (
        <div className="hud credits-panel" id="credits-panel" role="dialog" aria-label="Map credits">
          <div className="credits-head">
            <strong>Credits</strong>
            <button className="icon-btn credits-close" onClick={() => setOpen(false)} aria-label="Close credits">
              ✕
            </button>
          </div>
          {lines.length > 0 ? (
            <ul className="credits-list">
              {lines.map((line) => (
                <li key={line}>{line}</li>
              ))}
            </ul>
          ) : (
            <p className="muted">No data layer is drawn at this zoom.</p>
          )}
          <p className="muted credits-foot">
            Only the layers and labels on screen are listed. Map library:{' '}
            <a href="https://leafletjs.com/" target="_blank" rel="noreferrer">
              Leaflet
            </a>
            .
          </p>
        </div>
      )}
      <button
        className="credits-toggle"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        aria-controls="credits-panel"
        title="Data credits and attributions"
      >
        <span aria-hidden="true">ⓘ</span> Credits
      </button>
    </div>
  )
}
