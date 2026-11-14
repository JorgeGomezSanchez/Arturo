import { useCallback, useEffect, useState } from 'react'
import { createRoute, deleteRoute, getRoutes, getRoutesConfig, updateRoute } from '../api/client'

/**
 * Saved routes (GeoJSON LineString features) synced with the backend
 * CRUD API, plus the routes config (travel modes, thresholds). Like
 * usePois, the backend's answer is the source of truth.
 *
 * Returns { routes, config, error, create, update, remove }.
 */
export function useRoutes() {
  const [routes, setRoutes] = useState([])
  const [config, setConfig] = useState(null)
  const [error, setError] = useState(null)

  useEffect(() => {
    getRoutes()
      .then((fc) => setRoutes(fc.features))
      .catch(setError)
    getRoutesConfig()
      .then(setConfig)
      .catch(setError)
  }, [])

  const create = useCallback(async (data) => {
    const feature = await createRoute(data)
    setRoutes((list) => [...list, feature])
    return feature
  }, [])

  const update = useCallback(async (id, data) => {
    const feature = await updateRoute(id, data)
    setRoutes((list) => list.map((r) => (r.id === id ? feature : r)))
    return feature
  }, [])

  const remove = useCallback(async (id) => {
    await deleteRoute(id)
    setRoutes((list) => list.filter((r) => r.id !== id))
  }, [])

  return { routes, config, error, create, update, remove }
}
