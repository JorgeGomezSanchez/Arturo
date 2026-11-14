import { useEffect, useState } from 'react'
import { getHealth, getLayers, getMapConfig, getZones } from '../api/client'

/**
 * Loads everything the map needs from the backend, in parallel.
 * Returns { status: "loading" | "ready" | "error", error, health,
 *           mapConfig, layers, zones }.
 */
export function useBackendData() {
  const [state, setState] = useState({ status: 'loading' })

  useEffect(() => {
    let cancelled = false
    Promise.all([getHealth(), getMapConfig(), getLayers(), getZones()])
      .then(([health, mapConfig, layers, zones]) => {
        if (!cancelled) setState({ status: 'ready', health, mapConfig, layers, zones })
      })
      .catch((error) => {
        if (!cancelled) setState({ status: 'error', error })
      })
    return () => {
      cancelled = true
    }
  }, [])

  return state
}
