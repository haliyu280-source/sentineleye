import { useCallback, useEffect, useRef, useState } from 'react'

export const REFRESH_SECONDS = 10

async function fetchHealth() {
  let response
  try {
    response = await fetch('/api/health', { cache: 'no-store' })
  } catch {
    throw new Error('Cannot reach the SentinelEye backend')
  }

  const body = await response.json().catch(() => null)
  if (!response.ok) {
    throw new Error(body?.error ?? `Backend returned HTTP ${response.status}`)
  }
  if (!body || typeof body.status !== 'string') {
    throw new Error('Unexpected response from backend')
  }
  return body
}

// Polls /api/health every REFRESH_SECONDS. Keeps the last good reading when a
// request fails, and never starts a new request while one is still running.
export function useHealth() {
  const [data, setData] = useState(null)
  const [error, setError] = useState(null)
  const [checkedAt, setCheckedAt] = useState(null)
  const [loading, setLoading] = useState(true)
  const [nextAt, setNextAt] = useState(null)
  const [now, setNow] = useState(() => Date.now())
  const inFlight = useRef(false)
  const timer = useRef(null)

  const refresh = useCallback(async () => {
    if (inFlight.current) return
    inFlight.current = true
    clearTimeout(timer.current)
    setLoading(true)

    try {
      setData(await fetchHealth())
      setError(null)
      setCheckedAt(new Date())
    } catch (err) {
      setError(err.message)
    } finally {
      inFlight.current = false
      setLoading(false)
      setNextAt(Date.now() + REFRESH_SECONDS * 1000)
      timer.current = setTimeout(() => refreshRef.current(), REFRESH_SECONDS * 1000)
    }
  }, [])

  const refreshRef = useRef(refresh)
  useEffect(() => {
    refreshRef.current = refresh
  }, [refresh])

  // Start polling on mount; stop on unmount
  useEffect(() => {
    const start = setTimeout(refresh, 0)
    return () => {
      clearTimeout(start)
      clearTimeout(timer.current)
    }
  }, [refresh])

  // One-second tick for the countdown display only
  useEffect(() => {
    const tick = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(tick)
  }, [])

  const secondsLeft = nextAt ? Math.max(0, Math.ceil((nextAt - now) / 1000)) : REFRESH_SECONDS

  return { data, error, checkedAt, loading, secondsLeft, refresh }
}
