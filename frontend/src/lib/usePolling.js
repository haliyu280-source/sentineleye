import { useCallback, useEffect, useRef, useState } from 'react'

// Loads data now and then every `seconds`, keeping the last good result if a refresh fails.
// Pages that poll different resources (e.g. another server) are remounted with a new `key`.
export function usePolling(load, seconds) {
  const [data, setData] = useState(null)
  const [error, setError] = useState(null)
  const [loading, setLoading] = useState(true)
  const [updatedAt, setUpdatedAt] = useState(null)
  const loadRef = useRef(load)
  const inFlight = useRef(false)

  useEffect(() => {
    loadRef.current = load
  })

  const refresh = useCallback(async () => {
    if (inFlight.current) return
    inFlight.current = true
    setLoading(true)
    try {
      setData(await loadRef.current())
      setError(null)
      setUpdatedAt(new Date())
    } catch (err) {
      setError(err)
    } finally {
      inFlight.current = false
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    const first = setTimeout(refresh, 0)
    const timer = setInterval(refresh, seconds * 1000)
    return () => {
      clearTimeout(first)
      clearInterval(timer)
    }
  }, [refresh, seconds])

  return { data, error, loading, updatedAt, refresh }
}
