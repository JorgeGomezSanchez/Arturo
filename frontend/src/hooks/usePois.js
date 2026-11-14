import { useCallback, useEffect, useState } from 'react'
import { createPoi, deletePoi, getPois, updatePoi } from '../api/client'

/**
 * User POIs held in React state and synced with the backend CRUD API.
 * Every mutation goes to the backend first and the state is updated with
 * the backend's answer (the backend is the source of truth: ids,
 * timestamps, normalised longitude).
 *
 * Returns { pois: [GeoJSON Feature], error, reload, create, update, remove }.
 */
export function usePois() {
  const [pois, setPois] = useState([])
  const [error, setError] = useState(null)

  const reload = useCallback(() => {
    getPois()
      .then((fc) => {
        setPois(fc.features)
        setError(null)
      })
      .catch(setError)
  }, [])

  useEffect(reload, [reload])

  const create = useCallback(async (data) => {
    const feature = await createPoi(data)
    setPois((list) => [...list, feature])
    return feature
  }, [])

  const update = useCallback(async (id, data) => {
    const feature = await updatePoi(id, data)
    setPois((list) => list.map((p) => (p.id === id ? feature : p)))
    return feature
  }, [])

  const remove = useCallback(async (id) => {
    await deletePoi(id)
    setPois((list) => list.filter((p) => p.id !== id))
  }, [])

  return { pois, error, reload, create, update, remove }
}
