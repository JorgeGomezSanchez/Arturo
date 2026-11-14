import { useEffect, useState } from 'react'
import {
  getFeatureCategories,
  getHealth,
  getLayers,
  getMapConfig,
  getPoiCategories,
  getZones,
} from '../api/client'

/**
 * Loads everything the map needs from the backend, in parallel.
 * Returns { status: "loading" | "ready" | "error", error, health,
 *           mapConfig, layers, zones, featureCategories, poiCategories }.
 */
export function useBackendData() {
  const [state, setState] = useState({ status: 'loading' })

  useEffect(() => {
    let cancelled = false
    Promise.all([
      getHealth(),
      getMapConfig(),
      getLayers(),
      getZones(),
      getFeatureCategories(),
      getPoiCategories(),
    ])
      .then(([health, mapConfig, layers, zones, featureCategories, poiCategories]) => {
        if (!cancelled)
          setState({
            status: 'ready',
            health,
            mapConfig,
            layers,
            zones,
            featureCategories,
            poiCategories,
          })
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
