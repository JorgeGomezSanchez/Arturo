import { useEffect, useState } from 'react'
import { analyzeRoute } from '../api/client'

const DEBOUNCE_MS = 300

/**
 * Live analysis of the route being edited. Re-runs (debounced, the
 * previous request aborted) whenever the vertices or the travel mode
 * change. The last answer stays available while the next one loads, so
 * the panel can dim it instead of going blank.
 *
 * coordinates = [[lon, lat], ...] or null. Returns
 * { status: 'idle'|'loading'|'ok'|'error', data, error, retry }.
 */
export function useRouteAnalysis(coordinates, mode) {
  const key = coordinates ? JSON.stringify([coordinates, mode]) : null
  const [attempt, setAttempt] = useState(0)
  const [result, setResult] = useState({ key: null, data: null })

  useEffect(() => {
    if (!key) return
    const [coords, m] = JSON.parse(key)
    const ctrl = new AbortController()
    const t = setTimeout(() => {
      analyzeRoute({ coordinates: coords, mode: m }, ctrl.signal)
        .then((data) => setResult({ key, data }))
        .catch((error) => {
          if (error.name !== 'AbortError') setResult((r) => ({ key, data: r.data, error }))
        })
    }, DEBOUNCE_MS)
    return () => {
      clearTimeout(t)
      ctrl.abort()
    }
  }, [key, attempt])

  if (!key) return { status: 'idle', data: null, error: null, retry: () => {} }
  return {
    status: result.key !== key ? 'loading' : result.error ? 'error' : 'ok',
    data: result.data,
    error: result.key === key ? result.error : null,
    retry: () => setAttempt((n) => n + 1),
  }
}
