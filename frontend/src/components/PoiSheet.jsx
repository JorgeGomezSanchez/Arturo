import { useState } from 'react'
import PoiIcon from './PoiIcon'
import { poiLabelMinZoom } from '../map/poiVisibility'

function formatLatLon(lat, lon) {
  const w = ((lon + 540) % 360) - 180
  return `${Math.abs(lat).toFixed(4)}° ${lat >= 0 ? 'N' : 'S'}, ${Math.abs(w).toFixed(4)}° ${w >= 0 ? 'E' : 'W'}`
}

function VisibilityHint({ createdZoom, rules }) {
  const from = poiLabelMinZoom(createdZoom, rules)
  if (from === 0) {
    return <>Placed at zoom {createdZoom}: world-view POI, its label is visible at every zoom.</>
  }
  const dotFrom = Math.max(0, createdZoom - (rules?.markerZoomMargin ?? 5))
  return (
    <>
      Placed at zoom {createdZoom}: label from zoom {from}, small dot from zoom {dotFrom}, hidden when
      zoomed out further (always listed in the POIs tab).
    </>
  )
}

/**
 * Bottom sheet to create, view, edit and delete a POI. Big touch targets:
 * category buttons are 64 px tiles, inputs 44 px tall, two-step delete
 * (no browser confirm dialog).
 *
 * mode: 'create' (draft = {lat, lon, zoom}) | 'view' | 'edit' (poi = Feature)
 */
export default function PoiSheet({ mode, draft, poi, categories, rules, onSave, onDelete, onCancel, onEdit, onDraftChange }) {
  const initial = poi
    ? { name: poi.properties.name, category: poi.properties.category, notes: poi.properties.notes }
    : { name: '', category: draft?.category ?? 'unknown', notes: '' }
  const [form, setForm] = useState(initial)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const [confirmDelete, setConfirmDelete] = useState(false)

  const lat = poi ? poi.geometry.coordinates[1] : draft.lat
  const lon = poi ? poi.geometry.coordinates[0] : draft.lon
  const createdZoom = poi ? poi.properties.createdZoom : draft.zoom
  const catById = Object.fromEntries(categories.map((c) => [c.id, c]))

  const set = (patch) => {
    const next = { ...form, ...patch }
    setForm(next)
    onDraftChange?.(next) // live preview of the draft marker
  }

  const submit = async (e) => {
    e.preventDefault()
    if (!form.name.trim()) {
      setError('Give the POI a name (it is the label shown on the map).')
      return
    }
    setBusy(true)
    setError(null)
    try {
      await onSave({ ...form, name: form.name.trim(), lat, lon, createdZoom })
    } catch (err) {
      setError(err.detail || err.message)
      setBusy(false)
    }
  }

  const remove = async () => {
    if (!confirmDelete) {
      setConfirmDelete(true)
      return
    }
    setBusy(true)
    try {
      await onDelete()
    } catch (err) {
      setError(err.detail || err.message)
      setBusy(false)
    }
  }

  if (mode === 'view') {
    const cat = catById[poi.properties.category]
    return (
      <aside className="hud poi-sheet" aria-label="Point of interest">
        <div className="poi-sheet-head">
          <PoiIcon category={poi.properties.category} color={cat?.color} size={40} />
          <div>
            <h2>{poi.properties.name}</h2>
            <div className="muted">{cat?.label ?? poi.properties.category} · {formatLatLon(lat, lon)}</div>
          </div>
        </div>
        {poi.properties.notes ? <p className="poi-notes">{poi.properties.notes}</p> : <p className="muted">No notes.</p>}
        <p className="muted small">
          <VisibilityHint createdZoom={createdZoom} rules={rules} />
        </p>
        {error && <p className="form-error">{error}</p>}
        <div className="sheet-actions">
          <button className={`btn danger ${confirmDelete ? 'confirm' : ''}`} onClick={remove} disabled={busy}>
            {confirmDelete ? 'Tap again to delete' : 'Delete'}
          </button>
          <span className="spacer" />
          <button className="btn" onClick={onCancel}>
            Close
          </button>
          <button className="btn primary" onClick={onEdit}>
            Edit
          </button>
        </div>
      </aside>
    )
  }

  return (
    <form className="hud poi-sheet" onSubmit={submit} aria-label={mode === 'create' ? 'New point of interest' : 'Edit point of interest'}>
      <h2>{mode === 'create' ? 'New point of interest' : 'Edit point of interest'}</h2>
      <div className="muted small">{formatLatLon(lat, lon)}</div>

      <fieldset className="cat-picker">
        <legend>Type</legend>
        {categories.map((c) => (
          <button
            type="button"
            key={c.id}
            className={`cat-tile ${form.category === c.id ? 'active' : ''}`}
            style={{ '--poi-color': c.color }}
            onClick={() => set({ category: c.id })}
            aria-pressed={form.category === c.id}
            title={c.description}
          >
            <PoiIcon category={c.id} color={c.color} size={30} />
            <span>{c.label}</span>
          </button>
        ))}
      </fieldset>

      <label className="field">
        <span>Name (label on the map)</span>
        <input
          value={form.name}
          maxLength={60}
          onChange={(e) => set({ name: e.target.value })}
          placeholder={catById[form.category]?.description ?? 'Name'}
          autoFocus={mode === 'create'}
          required
        />
      </label>

      <label className="field">
        <span>Notes</span>
        <textarea
          value={form.notes}
          maxLength={2000}
          rows={3}
          onChange={(e) => set({ notes: e.target.value })}
          placeholder="What is here? How to approach it? Anything the crew should know."
        />
      </label>

      <p className="muted small">
        <VisibilityHint createdZoom={createdZoom} rules={rules} />
      </p>
      {error && <p className="form-error">{error}</p>}

      <div className="sheet-actions">
        {mode === 'edit' && (
          <button type="button" className={`btn danger ${confirmDelete ? 'confirm' : ''}`} onClick={remove} disabled={busy}>
            {confirmDelete ? 'Tap again to delete' : 'Delete'}
          </button>
        )}
        <span className="spacer" />
        <button type="button" className="btn" onClick={onCancel} disabled={busy}>
          Cancel
        </button>
        <button type="submit" className="btn primary" disabled={busy}>
          {busy ? 'Saving…' : 'Save'}
        </button>
      </div>
    </form>
  )
}
