import { useCallback, useEffect, useMemo, useState } from 'react'

const STORAGE_KEY = 'arturo.layers.v1'

function loadSaved() {
  try {
    return JSON.parse(window.localStorage.getItem(STORAGE_KEY)) ?? {}
  } catch {
    return {}
  }
}

/**
 * User choices for every layer of the catalog: visible / opacity, plus the
 * stacking order of overlays. Defaults come from the backend catalog
 * (defaultVisible, opacity, zIndex); choices persist in localStorage so a
 * reload keeps the same map. Unknown or removed layer ids are ignored, so
 * catalog changes never break a saved state.
 *
 * Returns {
 *   settings: { [id]: { visible, opacity } },
 *   overlayOrder: [id, ...]  bottom -> top,
 *   zIndexOf(id), setVisible(id, bool), setOpacity(id, 0..1),
 *   move(id, +1|-1), reset()
 * }
 */
export function useLayerState(layers) {
  const defaults = useMemo(() => {
    const settings = {}
    for (const l of layers) settings[l.id] = { visible: l.defaultVisible, opacity: l.opacity }
    const overlayOrder = layers
      .filter((l) => l.group !== 'base')
      .sort((a, b) => a.zIndex - b.zIndex)
      .map((l) => l.id)
    return { settings, overlayOrder }
  }, [layers])

  const [state, setState] = useState(() => {
    const saved = loadSaved()
    const settings = { ...defaults.settings }
    for (const [id, s] of Object.entries(saved.settings ?? {})) {
      if (settings[id]) settings[id] = { ...settings[id], ...s }
    }
    const known = new Set(defaults.overlayOrder)
    const savedOrder = (saved.overlayOrder ?? []).filter((id) => known.has(id))
    const overlayOrder = [...savedOrder, ...defaults.overlayOrder.filter((id) => !savedOrder.includes(id))]
    return { settings, overlayOrder }
  })

  useEffect(() => {
    try {
      window.localStorage.setItem(STORAGE_KEY, JSON.stringify(state))
    } catch {
      /* private mode / quota: not critical */
    }
  }, [state])

  const update = useCallback(
    (id, patch) =>
      setState((s) => ({ ...s, settings: { ...s.settings, [id]: { ...s.settings[id], ...patch } } })),
    [],
  )

  const move = useCallback((id, delta) => {
    setState((s) => {
      const order = [...s.overlayOrder]
      const i = order.indexOf(id)
      const j = i + delta
      if (i < 0 || j < 0 || j >= order.length) return s
      ;[order[i], order[j]] = [order[j], order[i]]
      return { ...s, overlayOrder: order }
    })
  }, [])

  const byId = useMemo(() => Object.fromEntries(layers.map((l) => [l.id, l])), [layers])

  // Base layers keep their catalog zIndex (1..9); overlays are stacked
  // from 10 upwards following the user's order.
  const zIndexOf = useCallback(
    (id) => {
      const i = state.overlayOrder.indexOf(id)
      return i < 0 ? byId[id]?.zIndex ?? 1 : 10 + i
    },
    [state.overlayOrder, byId],
  )

  return {
    settings: state.settings,
    overlayOrder: state.overlayOrder,
    zIndexOf,
    setVisible: (id, visible) => update(id, { visible }),
    setOpacity: (id, opacity) => update(id, { opacity }),
    move,
    reset: () => setState(defaults),
  }
}
