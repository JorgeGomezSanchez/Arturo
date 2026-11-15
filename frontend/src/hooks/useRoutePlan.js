import { useCallback, useEffect, useRef, useState } from 'react'
import { planRoute } from '../api/client'

/**
 * Automatic planning of the route being edited (POST /api/routes/plan).
 *
 * plan = null | { status: 'loading' | 'ok' | 'error', result, error,
 * prevWaypoints } where result = { waypoints, analysis, straight, info }
 * and prevWaypoints lets the user undo. A new run or clear() aborts the
 * request in flight.
 */
export function useRoutePlan() {
  const [plan, setPlan] = useState(null)
  const ctrl = useRef(null)

  const clear = useCallback(() => {
    ctrl.current?.abort()
    ctrl.current = null
    setPlan(null)
  }, [])

  /** draft = route draft; onWaypoints(waypoints) is called on success. */
  const run = useCallback(async (draft, { weights, onWaypoints } = {}) => {
    ctrl.current?.abort()
    const c = new AbortController()
    ctrl.current = c
    const prevWaypoints = draft.waypoints
    setPlan({ status: 'loading', prevWaypoints })
    try {
      const result = await planRoute(
        {
          start: [draft.start.lon, draft.start.lat],
          end: [draft.end.lon, draft.end.lat],
          mode: draft.mode,
          weights,
        },
        c.signal,
      )
      if (c.signal.aborted) return
      setPlan({ status: 'ok', result, prevWaypoints })
      onWaypoints?.(result.waypoints)
    } catch (error) {
      if (error.name === 'AbortError' || c.signal.aborted) return
      setPlan({ status: 'error', error, prevWaypoints })
    }
  }, [])

  useEffect(() => () => ctrl.current?.abort(), [])

  return { plan, run, clear }
}
