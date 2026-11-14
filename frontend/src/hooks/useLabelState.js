import { useCallback, useEffect, useMemo, useState } from 'react'

const STORAGE_KEY = 'arturo.labels.v1'

// Label groups shown as switches in the Layers tab. Category ids come
// from GET /api/features/categories; everything that is not a landing
// site or an exploration zone is an IAU place name.
const SPECIAL = {
  landing_site: 'Landing sites (robotic)',
  exploration_zone: 'Human exploration zones (NASA 2015)',
}

/**
 * Which families of map labels are on. Returns
 * { groups: [{id, label, count}], state: {id: bool}, toggle(id, on),
 *   anyOn, categories: null (= all) | [category ids] }.
 */
export function useLabelState(featureCategories) {
  const groups = useMemo(() => {
    const names = featureCategories.filter((c) => !SPECIAL[c.id])
    return [
      { id: 'names', label: 'Place names (IAU)', count: names.reduce((n, c) => n + c.count, 0), categories: names.map((c) => c.id) },
      ...Object.entries(SPECIAL)
        .map(([id, label]) => ({ id, label, count: featureCategories.find((c) => c.id === id)?.count ?? 0, categories: [id] }))
        .filter((g) => g.count > 0),
    ]
  }, [featureCategories])

  const [state, setState] = useState(() => {
    let saved = {}
    try {
      saved = JSON.parse(window.localStorage.getItem(STORAGE_KEY)) ?? {}
    } catch {
      /* ignore */
    }
    return Object.fromEntries(groups.map((g) => [g.id, saved[g.id] ?? true]))
  })

  useEffect(() => {
    try {
      window.localStorage.setItem(STORAGE_KEY, JSON.stringify(state))
    } catch {
      /* ignore */
    }
  }, [state])

  const toggle = useCallback((id, on) => setState((s) => ({ ...s, [id]: on })), [])

  const on = groups.filter((g) => state[g.id])
  const categories = useMemo(
    () => (on.length === groups.length ? null : on.flatMap((g) => g.categories)),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [state, groups],
  )

  return { groups, state, toggle, anyOn: on.length > 0, categories }
}
